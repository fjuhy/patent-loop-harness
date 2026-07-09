from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cli(args: list[str], root: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATENT_LOOP_ROOT"] = str(root)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if extra_env:
        env.update(extra_env)
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
            # A workspace-escape in one item is isolated: that item is blocked and the
            # reason is surfaced, but the run does not abort the whole backlog.
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("escapes workspace root", result.stderr + result.stdout)
            backlog = (root / "state" / "backlog.jsonl").read_text(encoding="utf-8")
            self.assertIn('"status": "blocked"', backlog)

    def test_runner_child_env_uses_allowlist(self) -> None:
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
                    "max_budget_usd": 0.25,
                    "extra_args": ["--append-system-prompt", "keep,a,comma"],
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
            self.assertIn("--max-budget-usd", command)
            self.assertIn("0.25", command)
            self.assertIn("keep,a,comma", command)

    def test_shell_runner_command_preserves_array_arguments(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import build_shell_command

        with tempfile.TemporaryDirectory() as tmp:
            fake_runner = Path(tmp) / "runner"
            fake_runner.write_text("#!/bin/sh\n", encoding="utf-8")
            command = build_shell_command({"command": [str(fake_runner), "-c", "print('a,b')"], "extra_args": ["x,y"]})
            self.assertEqual(command, [str(fake_runner), "-c", "print('a,b')", "x,y"])

    def test_usage_guard_defaults_to_codex_runner(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import usage_guard_applies_to_runner

        guard_cfg = {"enabled": True}
        self.assertTrue(usage_guard_applies_to_runner(guard_cfg, "codex"))
        self.assertFalse(usage_guard_applies_to_runner(guard_cfg, "claude"))
        self.assertTrue(usage_guard_applies_to_runner({"applies_to_runner": "all"}, "claude"))

    def test_claude_usage_guard_reads_env_and_state_file(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import runner_usage, usage_from_state_file

        old = os.environ.get("CLAUDE_WEEKLY_USED_PERCENT")
        try:
            os.environ["CLAUDE_WEEKLY_USED_PERCENT"] = "71.5"
            usage = runner_usage({"usage_guard": {"enabled": True}}, "claude")
            self.assertIsNotNone(usage)
            self.assertEqual(usage["used_percent"], 71.5)
        finally:
            if old is None:
                os.environ.pop("CLAUDE_WEEKLY_USED_PERCENT", None)
            else:
                os.environ["CLAUDE_WEEKLY_USED_PERCENT"] = old

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "claude_usage.json"
            path.write_text(json.dumps({"claude_weekly_used_percent": 66.0}), encoding="utf-8")
            state_usage = usage_from_state_file(path, "claude")
            self.assertIsNotNone(state_usage)
            self.assertEqual(state_usage["used_percent"], 66.0)

    def test_claude_usage_guard_blocks_before_runner_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "patent_loop.toml").write_text(
                """
[usage_guard]
enabled = true
applies_to_runner = ["claude"]
max_weekly_used_percent = 70.0
fail_closed_on_unknown = true

[usage_guard.claude]
env_var = "PATENT_LOOP_TEST_CLAUDE_USAGE"
""".lstrip(),
                encoding="utf-8",
            )
            seed = run_cli(
                [
                    "seed",
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

            result = run_cli(
                ["run", "--runner", "claude", "--stage-only", "idea", "--max-items", "1"],
                root,
                extra_env={"PATENT_LOOP_TEST_CLAUDE_USAGE": "80"},
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('"ran": false', result.stdout)
            self.assertIn("claude usage 80.0% >= 70.0%", result.stdout)

    def test_evaluator_context_separates_format_from_patentability_and_requires_ksr(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import context_isolation_block

        block = context_isolation_block("verify")
        self.assertIn("Separate substantive patentability from harness format compliance", block)
        self.assertIn("missing Runtime Field labels or micro-boundary headings are format issues", block)
        self.assertIn("KSR predictable-combination screen", block)

    def test_verifier_validation_requires_calibration_sections(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import load_config, validate_stage

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verification.md"
            path.write_text(
                """
# 독립 검증 보고서
## 통과 항목
통과.
## 실패 또는 잔여 위험
없음.
## 외부 신규 평가자 거절 시나리오
시나리오.
## 심사 점수표
| 항목 | 점수 | 이유 |
| --- | --- | --- |
| 신규성 | A- | ok |
| 진보성 | A- | ok |
| 명세서 뒷받침/명확성 | A- | ok |
| 권리범위 방어력 | A- | ok |
## 최종 판정
FINAL_VERDICT: DIRECT_OK
""".lstrip(),
                encoding="utf-8",
            )
            ok, failures = validate_stage("verify", path, load_config())
            self.assertFalse(ok)
            self.assertIn("missing verifier section: ## 하네스 형식/필드 바인딩 점검", failures)
            self.assertIn("missing verifier section: ## KSR/예측 가능한 조합 점검", failures)

    def test_verifier_validation_rejects_invalid_final_verdict(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import load_config, validate_stage

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "verification.md"
            path.write_text(
                """
# 독립 검증 보고서
## 통과 항목
통과.
## 하네스 형식/필드 바인딩 점검
정상.
## 외부 신규 평가자 거절 시나리오
없음.
## KSR/예측 가능한 조합 점검
정상.
## 심사 점수표
| 항목 | 점수 | 이유 |
| --- | --- | --- |
| 신규성 | A- | ok |
| 진보성 | A- | ok |
| 명세서 뒷받침/명확성 | A- | ok |
| 권리범위 방어력 | A- | ok |
## 최종 판정
FINAL_VERDICT: MAYBE
""".lstrip(),
                encoding="utf-8",
            )
            ok, failures = validate_stage("verify", path, load_config())
            self.assertFalse(ok)
            self.assertIn("missing valid FINAL_VERDICT token", failures)

    def test_claim_count_uses_claim_section_claim_starts_only(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import count_claims

        text = (
            "# 최종 특허 명세서 후보\n"
            "## 독립항 1 구성요소 매핑\n"
            + "\n".join(f"- 청구항 1 구성요소 반복 {index}" for index in range(30))
            + "\n## 청구범위\n"
            "청구항 1. 실제 청구항 하나.\n"
            "## 요약서\n"
            "요약.\n"
        )
        self.assertEqual(count_claims(text), 1)

    def test_grade_parser_accepts_colon_in_table_label(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import extract_grade

        text = """
| 항목 | 점수 | 이유 |
| --- | --- | --- |
| 신규성: | A- | ok |
| 진보성: | B+ | weak |
""".lstrip()
        self.assertEqual(extract_grade(text, "신규성"), "A-")
        self.assertEqual(extract_grade(text, "진보성"), "B+")

    def test_doctor_runner_smoke_accepts_prompt_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(["doctor", "--runner", "prompt_only", "--runner-smoke"], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Doctor OK", result.stdout)

    def test_run_max_items_default_allows_config_default(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import build_parser

        args = build_parser().parse_args(["run"])
        self.assertIsNone(args.max_items)

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

    def test_deep_merge_overrides_scalars_and_recurses(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import deep_merge

        base = {"a": 1, "b": {"x": 1, "y": 2}}
        override = {"b": {"y": 3, "z": 4}, "c": 5}
        self.assertEqual(deep_merge(base, override), {"a": 1, "b": {"x": 1, "y": 3, "z": 4}, "c": 5})

    def test_partial_config_does_not_crash_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "config").mkdir()
            (root / "config" / "patent_loop.toml").write_text('[runner]\ntype = "prompt_only"\n', encoding="utf-8")
            (root / "state").mkdir()
            (root / "state" / "backlog.jsonl").write_text(
                json.dumps(
                    {
                        "id": "merge-regression-001",
                        "title": "t",
                        "domain": "d",
                        "hypothesis": "h" * 120,
                        "priority": 100,
                        "status": "draft_ready",
                        "draft_path": "work/x/02_draft.md",
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            result = run_cli(["run", "--dry-run"], root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertNotIn("'loop'", result.stderr)
            self.assertNotIn("'quality'", result.stderr)

    def test_section_text_allows_annotated_heading(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import bullet_count, section_text

        text = "## 검색 쿼리 로그 (8건)\n- q1\n- q2\n## 다음\n본문\n"
        section = section_text(text, "검색 쿼리 로그")
        self.assertIn("q1", section)
        self.assertEqual(bullet_count(section), 2)

    def test_count_claims_scopes_to_numbered_claims_heading(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import count_claims

        text = (
            "## 8. 실시형태\n"
            + "\n".join(f"청구항 1 설명 반복 {i}" for i in range(20))
            + "\n## 9. 청구범위\n청구항 1. 첫째.\n청구항 2. 둘째.\n## 10. 요약\n"
        )
        self.assertEqual(count_claims(text), 2)

    def test_codex_command_includes_search_flag(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import build_codex_command

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "codex"
            fake.write_text("#!/bin/sh\n", encoding="utf-8")
            last = Path(tmp) / "last.md"
            self.assertIn("--search", build_codex_command({"command": str(fake), "web_search": True}, last))
            self.assertNotIn("--search", build_codex_command({"command": str(fake), "web_search": False}, last))

    def test_claude_command_enables_web_search_tools(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import build_claude_command

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "claude"
            fake.write_text("#!/bin/sh\n", encoding="utf-8")
            cmd = build_claude_command({"command": str(fake), "web_search": True})
            self.assertIn("--allowedTools", cmd)
            self.assertIn("WebSearch,WebFetch", cmd)

    def test_web_search_evidence_and_requirement(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        import subprocess as sp

        from patent_loop_harness.cli import web_search_evidence, web_search_requirement_failure

        self.assertTrue(web_search_evidence("codex", "", "thinking\nweb search: LTC6811 datasheet\n"))
        self.assertFalse(web_search_evidence("codex", "no tools used", ""))
        self.assertTrue(web_search_evidence("claude", '{"usage":{"server_tool_use":{"web_search_requests":2}}}', ""))
        self.assertFalse(web_search_evidence("claude", '{"usage":{"server_tool_use":{"web_search_requests":0}}}', ""))
        self.assertFalse(web_search_evidence("claude", "검색 쿼리 로그에 web search 라고 적었다", ""))

        searched = sp.CompletedProcess([], 0, stdout="", stderr="web search: foo")
        unsearched = sp.CompletedProcess([], 0, stdout="report mentions search", stderr="")
        self.assertIsNone(web_search_requirement_failure("examine", {"type": "codex", "require_web_search": True}, searched))
        self.assertIsNotNone(web_search_requirement_failure("examine", {"type": "codex", "require_web_search": True}, unsearched))
        self.assertIsNone(web_search_requirement_failure("draft", {"type": "codex", "require_web_search": True}, unsearched))
        self.assertIsNone(web_search_requirement_failure("examine", {"type": "codex", "require_web_search": False}, unsearched))
        self.assertIsNone(web_search_requirement_failure("examine", {"type": "shell", "require_web_search": True}, unsearched))

    def test_research_limitation_with_pass_verdict_is_allowed(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import load_config, validate_stage

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "examine.md"
            queries = "\n".join(f"- query {i}" for i in range(8))
            path.write_text(
                "# 특허성 심사 보고서\n"
                "## 검색 범위 및 한계\nRESEARCH_LIMITATION: 검색 불가\n"
                "## 배터리 산업 SW 직접 결속 판단\nok\n"
                "## 선행기술 후보\nA\n"
                f"## 검색 쿼리 로그\n{queries}\n"
                "## 하네스 형식/필드 바인딩 점검\nok\n"
                "## 독립항 1 구성요소별 선행기술 매핑\nok\n"
                "## 심사관 A 판단\nok\n## 심사관 B 판단\nok\n"
                "## 신규성 판단\nok\n## 진보성 판단\nok\n"
                "## KSR/예측 가능한 조합 점검\nok\n"
                "## 명확성/기재요건 판단\nok\n"
                "## 외부 신규 심사관 리스크\nok\n"
                "## 심사 점수표\n신규성: A-\n진보성: A-\n명세서 뒷받침/명확성: A-\n권리범위 방어력: A-\n"
                "## 보정 지시\n없음\n## 최종 판정\nFINAL_VERDICT: DIRECT_OK\n",
                encoding="utf-8",
            )
            ok, failures = validate_stage("examine", path, load_config())
            # incomplete search (RESEARCH_LIMITATION) is no longer a ground of refusal
            self.assertTrue(ok, failures)

    def test_codex_usage_skips_malformed_session_lines(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import codex_usage_from_sessions

        with tempfile.TemporaryDirectory() as tmp:
            sess = Path(tmp) / "s.jsonl"
            sess.write_text(
                '[1,2,3]\n'
                '"scalar"\n'
                '{"payload":{"type":"token_count","rate_limits":{"secondary":{"window_minutes":"oops","used_percent":50}}}}\n',
                encoding="utf-8",
            )
            self.assertIsNone(codex_usage_from_sessions({"session_glob": str(sess)}))

    def test_version_flag(self) -> None:
        result = run_cli(["--version"], REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("patent-loop-harness", result.stdout)

    def test_custom_field_is_not_battery_profile_via_word_boundary(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        import tomllib

        from patent_loop_harness.cli import field_profile, is_battery_profile_text

        # ordinary words ("process"/"inspection") must NOT trigger battery via the "ess" substring
        self.assertFalse(is_battery_profile_text("Semiconductor package inspection and process control gates"))
        self.assertTrue(is_battery_profile_text("battery-industry software for BMS and ESS"))
        # the shipped semiconductor example config must resolve as a non-battery profile
        example = tomllib.loads((REPO_ROOT / "examples" / "patent_loop.example.toml").read_text(encoding="utf-8"))
        profile = field_profile(example)
        self.assertFalse(profile["battery_default"], profile["scope_terms"][:5])
        self.assertNotIn("bms", [t.lower() for t in profile["scope_terms"]])

    def test_research_retry_status_routes_to_research(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import stage_for

        self.assertEqual(stage_for({"status": "research_retry"}), "research")
        self.assertEqual(stage_for({"status": "idea_ready"}), "research")

    def test_grade_failures_uses_preponderance_floors(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import grade_failures

        cfg = {"quality": {"min_grade_inventive_step": "B+", "min_grade_any_axis": "B", "forbid_conditional_pass": False}}

        def doc(nov: str, inv: str, sup: str, scope: str) -> str:
            return f"신규성: {nov}\n진보성: {inv}\n명세서 뒷받침/명확성: {sup}\n권리범위 방어력: {scope}\n"

        # borderline-but-allowable: inventive step B+, other axes B -> passes (preponderance)
        self.assertEqual(grade_failures(doc("B", "B+", "B", "B"), cfg), [])
        # inventive step below the B+ floor -> fails on 진보성
        self.assertTrue(any("진보성" in f for f in grade_failures(doc("A-", "B", "A-", "A-"), cfg)))
        # another axis below the hard B floor -> fails
        self.assertTrue(any("신규성" in f for f in grade_failures(doc("B-", "A-", "A-", "A-"), cfg)))
        # all A- still passes
        self.assertEqual(grade_failures(doc("A-", "A-", "A-", "A-"), cfg), [])


if __name__ == "__main__":
    unittest.main()
