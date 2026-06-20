from __future__ import annotations

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

    def test_codex_child_env_uses_allowlist(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import codex_child_env

        os.environ["PATENT_LOOP_TEST_SECRET"] = "do-not-forward"
        os.environ["PATENT_LOOP_TEST_ALLOWED"] = "forward-me"
        child_env = codex_child_env({"env_allowlist": ["PATENT_LOOP_TEST_ALLOWED"]})
        self.assertEqual(child_env, {"PATENT_LOOP_TEST_ALLOWED": "forward-me"})


if __name__ == "__main__":
    unittest.main()
