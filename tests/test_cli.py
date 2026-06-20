from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(args: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATENT_LOOP_ROOT"] = str(root)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "patent_loop_harness.cli", *args],
        cwd=str(root),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )


class PatentLoopHarnessCliTests(unittest.TestCase):
    def test_config_only_custom_field_does_not_fall_back_to_battery_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "patent_loop.toml").write_text(
                """
[field]
name = "semiconductor packaging control software"
description = "Semiconductor package inspection software for recipe activation gates and package trace verification."
""".strip()
                + "\n",
                encoding="utf-8",
            )
            seed = run_cli(
                [
                    "seed",
                    "--title",
                    "Package trace recipe activation gate",
                    "--hypothesis",
                    (
                        "Semiconductor package inspection software sends an echo challenge, "
                        "computes a residual signature, checks calibration version mismatch "
                        "and replay freshness, and fail-closed blocks stale recipe activation "
                        "at a package process control gate."
                    ),
                ],
                root,
            )
            self.assertEqual(seed.returncode, 0, seed.stderr + seed.stdout)
            self.assertIn('"field": "semiconductor packaging control software"', seed.stdout)

    def test_custom_field_seed_and_dry_run_use_bundled_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = run_cli(
                [
                    "seed",
                    "--field",
                    "semiconductor packaging control software",
                    "--field-domain",
                    "advanced packaging inspection",
                    "--field-term",
                    "package",
                    "--title",
                    "Package warpage echo recipe activation gate",
                    "--hypothesis",
                    (
                        "Semiconductor package inspection software commands a warpage-map echo "
                        "challenge, computes a residual signature, checks calibration version "
                        "mismatch and replay freshness, and fail-closed excludes stale recipe "
                        "contribution at a process recipe activation gate."
                    ),
                ],
                root,
            )
            self.assertEqual(seed.returncode, 0, seed.stderr + seed.stdout)
            self.assertIn('"created": true', seed.stdout)

            dry_run = run_cli(
                [
                    "run",
                    "--dry-run",
                    "--stage-only",
                    "idea",
                    "--field",
                    "semiconductor packaging control software",
                    "--field-term",
                    "package",
                ],
                root,
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
            self.assertIn('"dry_run": true', dry_run.stdout)
            prompts = list(root.glob("work/*_idea/task_prompt.md"))
            self.assertEqual(len(prompts), 1)
            prompt = prompts[0].read_text(encoding="utf-8")
            self.assertIn("Runtime Patent Research Field", prompt)
            self.assertIn("semiconductor packaging control software", prompt)

    def test_prompt_only_runner_writes_prompt_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seed = run_cli(
                [
                    "seed",
                    "--field",
                    "semiconductor packaging control software",
                    "--field-term",
                    "package",
                    "--title",
                    "Package recipe freshness gate",
                    "--hypothesis",
                    (
                        "Semiconductor package recipe control software sends a package echo "
                        "challenge, computes a residual response signature, checks calibration "
                        "version mismatch and replay freshness, and fail-closed blocks stale "
                        "recipe activation at a package control gate."
                    ),
                ],
                root,
            )
            self.assertEqual(seed.returncode, 0, seed.stderr + seed.stdout)

            result = run_cli(["run", "--runner", "prompt_only", "--stage-only", "idea"], root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('"dry_run": true', result.stdout)
            self.assertEqual(len(list(root.glob("work/*_idea/task_prompt.md"))), 1)

    def test_artifact_paths_must_stay_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "workbench"
            root.mkdir()
            outside = parent / "outside_draft.md"
            outside.write_text("# outside\n", encoding="utf-8")
            (root / "state").mkdir()
            backlog_item = {
                "id": "outside-artifact-001",
                "title": "Outside artifact",
                "domain": "test",
                "hypothesis": "A test item with an existing draft artifact outside the workspace.",
                "priority": 100,
                "status": "draft_ready",
                "draft_path": str(outside),
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            (root / "state" / "backlog.jsonl").write_text(json.dumps(backlog_item) + "\n", encoding="utf-8")

            result = run_cli(["run", "--dry-run", "--stage-only", "examine"], root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("escapes workspace root", result.stderr + result.stdout)

    def test_codex_child_env_uses_allowlist(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import runner_child_env

        os.environ["PATENT_LOOP_TEST_SECRET"] = "do-not-forward"
        os.environ["PATENT_LOOP_TEST_ALLOWED"] = "forward-me"
        child_env = runner_child_env({"env_allowlist": ["PATENT_LOOP_TEST_ALLOWED"]})
        self.assertEqual(child_env, {"PATENT_LOOP_TEST_ALLOWED": "forward-me"})

    def test_claude_runner_command_uses_print_mode(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import build_claude_command

        with tempfile.TemporaryDirectory() as tmp:
            fake_claude = Path(tmp) / "claude"
            fake_claude.write_text("#!/bin/sh\n", encoding="utf-8")
            command = build_claude_command(
                {
                    "command": str(fake_claude),
                    "model": "sonnet",
                    "output_format": "text",
                    "permission_mode": "acceptEdits",
                    "bare": True,
                    "no_session_persistence": True,
                    "max_turns": 3,
                    "query": "Execute stdin task.",
                }
            )
            self.assertEqual(command[0], str(fake_claude))
            self.assertIn("-p", command)
            self.assertIn("Execute stdin task.", command)
            self.assertIn("--output-format", command)
            self.assertIn("text", command)
            self.assertIn("--permission-mode", command)
            self.assertIn("acceptEdits", command)
            self.assertIn("--model", command)
            self.assertIn("sonnet", command)

    def test_usage_guard_defaults_to_codex_runner(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import usage_guard_applies_to_runner

        guard_cfg = {"enabled": True}
        self.assertTrue(usage_guard_applies_to_runner(guard_cfg, "codex"))
        self.assertFalse(usage_guard_applies_to_runner(guard_cfg, "claude"))
        self.assertTrue(usage_guard_applies_to_runner({"applies_to_runner": "all"}, "claude"))

    def test_live_pid_lock_is_not_removed_as_stale(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import LoopLock

        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "loop.lock"
            lock_path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
            old = lock_path.stat().st_mtime - 10
            os.utime(lock_path, (old, old))
            with self.assertRaisesRegex(RuntimeError, "Loop already running"):
                with LoopLock(lock_path, stale_seconds=1):
                    pass


if __name__ == "__main__":
    unittest.main()
