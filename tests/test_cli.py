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

    @staticmethod
    def _valid_visual_html() -> str:
        sections = [
            "기술 분야",
            "배경 기술",
            "기존 기술의 문제점",
            "발명의 목적",
            "발명의 핵심 구성",
            "전체 시스템 구성",
            "구성요소별 상세 설명",
            "동작 절차",
            "판단식 및 변수 설명",
            "데이터 구조",
            "결과 반영 방식",
            "도면 설명",
            "상세 실시예",
            "예외 실시예 및 실패 처리",
            "복구 및 정상 복귀 절차",
            "기존 기술과의 구분점",
            "기대 효과",
            "변형예 및 구현 고려사항",
        ]
        body = "".join(f"<section><h2>{heading}</h2><p>입력과 판단 결과를 기술한다.</p></section>" for heading in sections)
        svgs = "".join(
            f'<svg viewBox="0 0 200 80"><rect x="5" y="5" width="190" height="70" fill="#fff" stroke="#17365d"/><text x="20" y="45" fill="#111">도식 {index}</text></svg>'
            for index in range(1, 4)
        )
        tables = "".join(
            "<table><tr><th>항목</th><th>설명</th></tr><tr><td>입력</td><td>원문 값</td></tr></table>" for _ in range(2)
        )
        return (
            '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>시험 발명</title><style>@media print{section{break-inside:avoid}} body{color:#111}</style>'
            f"</head><body><h1>시험 발명</h1>{body}{tables}{svgs}</body></html>"
        )

    @staticmethod
    def _valid_visual_review(verdict: str = "DIRECT_OK") -> str:
        detail = (
            "최종 명세서와 원문 상세 초안의 입력, 측정, 판단, 실패 처리, 결과 반영, 복구 조건을 서로 대조했다. "
            "HTML 본문은 해당 인과관계를 같은 용어로 설명하고 원문에 없는 숫자나 제어 효과를 추가하지 않았다. "
            "구현자는 입력 인터페이스와 기록 필드, 상태별 허용 동작을 문서 안에서 식별할 수 있다. "
        )
        remediation = "- 없음" if verdict == "DIRECT_OK" else (
            "- `동작 절차`의 실패 분기에 원문 상세 초안의 안전측 처리와 복구 조건을 연결한다. "
            "현재 HTML 위치와 원문 근거를 함께 표시하고 새로운 임계값은 추가하지 않는다."
        )
        return f"""# 기술문서 구현 가능성 검토 보고서

## 원문 충실성
- {detail * 2}

## 문서 완결성
- {detail * 2}

## 구성요소별 구현 가능성
| 구성요소/검증 항목 | 입력·출처 | 측정·생성 | 계산·판정 | 통과/실패 결과 | 결과 반영 | 판정 |
| --- | --- | --- | --- | --- | --- | --- |
| 입력 수집부 | 원문 입력 구조 | 원문 측정 구간에서 수집 | 원문 조건식으로 판정 | 통과와 실패를 분리 | 결과 연결과 기록 | 충족. {detail} |
| 상태 판정부 | 원문 상태 필드 | 원문 생성 절차를 사용 | 변수 의미와 기준을 대조 | 실패 시 안전측 처리 | 복구 조건과 연결 | 충족. {detail} |

## 판단식·변수·임계값 점검
- {detail * 2}

## 데이터 구조·상태 전이·실패 처리 점검
- {detail * 2}

## 실시예 재현성
- {detail * 2}

## 도식 검토
- {detail * 2}

## 보완 지시
{remediation}

## 최종 판정
FINAL_VERDICT: {verdict}
"""

    def test_visual_artifact_contract_accepts_complete_source_faithful_html(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import visual_artifact_failures

        cfg = {
            "quality": {
                "min_visual_html_chars": 1000,
                "min_visual_svg_count": 3,
                "min_visual_section_count": 16,
                "min_visual_table_count": 2,
            }
        }
        self.assertEqual(visual_artifact_failures(self._valid_visual_html(), cfg), [])

    def test_visual_artifact_contract_rejects_meta_placeholders_and_broken_style(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import visual_artifact_failures

        broken = self._valid_visual_html().replace(
            "</body>",
            "<p>한 문장 요약입니다.</p>@@B잠금0@@<script>bad()</script></body>",
        )
        cfg = {"quality": {"min_visual_html_chars": 1000, "min_visual_svg_count": 3, "min_visual_section_count": 16, "min_visual_table_count": 2}}
        failures = visual_artifact_failures(broken, cfg)
        self.assertTrue(any("한 문장 요약" in failure for failure in failures), failures)
        self.assertTrue(any("합니다" in failure or "입니다" in failure for failure in failures), failures)
        self.assertTrue(any("placeholder" in failure or "corruption" in failure for failure in failures), failures)
        self.assertIn("visual artifact must not contain JavaScript", failures)

    def test_visual_html_requires_independent_review_before_finalized(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        import patent_loop_harness.cli as cli

        with tempfile.TemporaryDirectory() as tmp:
            old_root = cli.ROOT
            try:
                cli.ROOT = Path(tmp)
                html_path = Path(tmp) / "visuals" / "item.html"
                html_path.parent.mkdir()
                html_path.write_text(self._valid_visual_html(), encoding="utf-8")
                item = {"id": "visual-review-001", "status": "visualization_ready"}
                cli.update_item_after_success(item, "visualize", html_path, config={"loop": {}})
                self.assertEqual(item["status"], "visual_review_ready")
                self.assertEqual(item["visual_contract_version"], 2)
                self.assertEqual(cli.stage_for(item), "visual_review")

                reject_path = Path(tmp) / "reports" / "review-reject.md"
                reject_path.parent.mkdir()
                reject_path.write_text("FINAL_VERDICT: REJECT\n", encoding="utf-8")
                cli.update_item_after_success(item, "visual_review", reject_path, config={"loop": {}})
                self.assertEqual(item["status"], "visual_revision_needed")
                self.assertEqual(item.get("visual_iteration", 0), 0)
                self.assertEqual(cli.stage_for(item), "visual_revise")

                revised_path = Path(tmp) / "visuals" / "item-revised.html"
                revised_path.write_text(self._valid_visual_html(), encoding="utf-8")
                cli.update_item_after_success(item, "visual_revise", revised_path, config={"loop": {}})
                self.assertEqual(item["status"], "visual_review_ready")
                self.assertEqual(item["visual_iteration"], 1)

                pass_path = Path(tmp) / "reports" / "review-pass.md"
                pass_path.write_text("FINAL_VERDICT: DIRECT_OK\n", encoding="utf-8")
                cli.update_item_after_success(item, "visual_review", pass_path, config={"loop": {}})
                self.assertEqual(item["status"], "finalized")
                self.assertIsNone(cli.stage_for(item))
            finally:
                cli.ROOT = old_root

    def test_visual_review_validation_requires_substantive_implementation_evidence(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import validate_stage

        hollow = """# 기술문서 구현 가능성 검토 보고서
## 원문 충실성
## 문서 완결성
## 구성요소별 구현 가능성
## 판단식·변수·임계값 점검
## 데이터 구조·상태 전이·실패 처리 점검
## 실시예 재현성
## 도식 검토
## 보완 지시
- 없음
## 최종 판정
FINAL_VERDICT: DIRECT_OK
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.md"
            path.write_text(hollow, encoding="utf-8")
            ok, failures = validate_stage("visual_review", path, {"quality": {}})
            self.assertFalse(ok)
            self.assertTrue(any("empty" in failure or "too thin" in failure for failure in failures), failures)
            self.assertTrue(any("component evidence rows" in failure for failure in failures), failures)

            path.write_text(self._valid_visual_review(), encoding="utf-8")
            ok, failures = validate_stage("visual_review", path, {"quality": {}})
            self.assertTrue(ok, failures)

    def test_visual_review_verdict_requires_consistent_remediation(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import visual_review_failures

        direct_with_work = self._valid_visual_review().replace("- 없음", "- 동작 절차를 수정한다.")
        failures = visual_review_failures(direct_with_work, {"quality": {}})
        self.assertTrue(any("must state only '없음'" in failure for failure in failures), failures)

        reject_without_work = self._valid_visual_review("REJECT").replace(
            "- `동작 절차`의 실패 분기에 원문 상세 초안의 안전측 처리와 복구 조건을 연결한다. 현재 HTML 위치와 원문 근거를 함께 표시하고 새로운 임계값은 추가하지 않는다.",
            "없음",
        )
        failures = visual_review_failures(reject_without_work, {"quality": {}})
        self.assertTrue(any("concrete itemized" in failure for failure in failures), failures)

    def test_visual_revision_limit_counts_completed_rewrites(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        import patent_loop_harness.cli as cli

        with tempfile.TemporaryDirectory() as tmp:
            old_root = cli.ROOT
            try:
                cli.ROOT = Path(tmp)
                item = {"id": "visual-limit-001", "status": "visual_revision_needed", "visual_iteration": 2}
                config = {"loop": {"max_visual_revision_cycles": 3}}
                self.assertFalse(cli.maybe_reject_for_revision_limit(item, config))

                revised_path = Path(tmp) / "visuals" / "third-revision.html"
                revised_path.parent.mkdir()
                revised_path.write_text(self._valid_visual_html(), encoding="utf-8")
                cli.update_item_after_success(item, "visual_revise", revised_path, config=config)
                self.assertEqual(item["visual_iteration"], 3)

                reject_path = Path(tmp) / "reports" / "third-review.md"
                reject_path.parent.mkdir()
                reject_path.write_text("FINAL_VERDICT: REJECT\n", encoding="utf-8")
                cli.update_item_after_success(item, "visual_review", reject_path, config=config)
                self.assertEqual(item["status"], "visual_revision_needed")
                self.assertTrue(cli.maybe_reject_for_revision_limit(item, config))
                self.assertEqual(item["status"], "blocked")
            finally:
                cli.ROOT = old_root

    def test_legacy_visual_contract_is_grandfathered_for_old_finalized_items(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import validate_stage, visual_validation_stage

        self.assertEqual(visual_validation_stage({"status": "finalized"}), "visualize_legacy")
        self.assertEqual(visual_validation_stage({"status": "finalized", "visual_contract_version": 2}), "visualize")
        self.assertEqual(visual_validation_stage({"status": "visual_review_ready"}), "visualize")

        legacy = (
            "<!doctype html><html><head><style>body{color:#111}</style></head><body>"
            "<h1>요약</h1><svg></svg><h2>배경</h2><h2>해결하고자 하는 문제</h2>"
            "<h2>문제 해결 접근</h2><h2>세부 내용</h2>" + ("기존 기술 설명 " * 1500) + "</body></html>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.html"
            path.write_text(legacy, encoding="utf-8")
            old_ok, old_failures = validate_stage("visualize_legacy", path, {"quality": {}})
            new_ok, new_failures = validate_stage("visualize", path, {"quality": {}})
            self.assertTrue(old_ok, old_failures)
            self.assertFalse(new_ok, new_failures)

    def test_revise_context_includes_verifier_and_spotcheck_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "reports").mkdir()
            (root / "reports" / "verification.md").write_text("VERIFY_REJECT_REASON", encoding="utf-8")
            (root / "reports" / "spotcheck.md").write_text("SPOTCHECK_REJECT_REASON", encoding="utf-8")
            env = os.environ.copy()
            env["PATENT_LOOP_ROOT"] = str(root)
            env["PYTHONPATH"] = str(REPO_ROOT / "src")
            script = (
                "from patent_loop_harness.cli import artifact_context\n"
                "item = {'id': 'x-001', 'status': 'needs_revision',"
                " 'verification_path': 'reports/verification.md',"
                " 'external_spotcheck_path': 'reports/spotcheck.md'}\n"
                "print(artifact_context(item, 'revise'))\n"
            )
            result = subprocess.run([sys.executable, "-c", script], env=env, cwd=str(root), text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("VERIFY_REJECT_REASON", result.stdout)
            self.assertIn("SPOTCHECK_REJECT_REASON", result.stdout)
            self.assertIn("독립 검증 보고서", result.stdout)

    def test_dry_run_does_not_persist_scope_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            item = {
                "id": "unrelated-seed-001",
                "title": "Unrelated seed",
                "domain": "other",
                "hypothesis": "nothing to do with the configured field",
                "priority": 100,
                "status": "seed",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            }
            (root / "state" / "backlog.jsonl").write_text(json.dumps(item) + "\n", encoding="utf-8")

            dry_run = run_cli(["run", "--dry-run", "--runner", "prompt_only"], root)
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr + dry_run.stdout)
            self.assertIn("seed outside target field scope", dry_run.stdout)
            self.assertIn('"dry_run": true', dry_run.stdout)
            persisted = json.loads((root / "state" / "backlog.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "seed")

            real_run = run_cli(["run", "--runner", "prompt_only"], root)
            self.assertEqual(real_run.returncode, 0, real_run.stderr + real_run.stdout)
            persisted = json.loads((root / "state" / "backlog.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "rejected")

    VALID_SEED_HYPOTHESIS = (
        "Semiconductor package inspection software commands a warpage-map echo challenge before "
        "recipe activation, computes a residual signature against the fixture baseline, checks "
        "calibration version mismatch and replay freshness, and fail-closed excludes the stale recipe "
        "contribution at the process recipe admission gate."
    )

    def write_fake_agent(self, root: Path) -> Path:
        # Stands in for any agent CLI: reads the prompt file, prints a fake search line,
        # writes the seeds JSON to the output path given on argv.
        agent = root / "fake_agent.py"
        agent.write_text(
            "import json, sys\n"
            "prompt_file, output_path, stage = sys.argv[1:4]\n"
            "prompt = open(prompt_file, encoding='utf-8').read()\n"
            "print('web search: package warpage echo recipe gate')\n"
            "if stage != 'scout':\n"
            "    open(output_path, 'w', encoding='utf-8').write('not a valid artifact\\n')\n"
            "    raise SystemExit(0)\n"
            "assert 'Requested seed count' in prompt, 'scout prompt missing'\n"
            "seeds = {'seeds': [\n"
            "  {'id': 'package-warpage-echo-gate', 'title': 'Warpage echo recipe gate', 'domain': 'advanced packaging inspection',\n"
            f"   'hypothesis': {self.VALID_SEED_HYPOTHESIS!r}, 'priority': 110, 'closest_art': ['US1', 'US2', 'US3']}},\n"
            "  {'id': 'weak-seed', 'title': 'Weak seed', 'domain': 'advanced packaging inspection',\n"
            "   'hypothesis': 'AI optimizes the package process.', 'priority': 100},\n"
            "]}\n"
            "open(output_path, 'w', encoding='utf-8').write('```json\\n' + json.dumps(seeds) + '\\n```\\n')\n",
            encoding="utf-8",
        )
        return agent

    def write_shell_runner_config(self, root: Path, agent: Path, search_pattern: str = "") -> None:
        (root / "config").mkdir(exist_ok=True)
        (root / "config" / "patent_loop.toml").write_text(
            f"""
[field]
name = "semiconductor packaging control software"
description = "Semiconductor package inspection software for recipe activation gates and package trace verification."
domains = ["advanced packaging inspection"]

[runner]
type = "shell"

[runner.shell]
command = ["{sys.executable}", "{agent}", "{{prompt_file}}", "{{output_path}}", "{{stage}}"]
prompt_mode = "file"
web_search_evidence_pattern = "{search_pattern}"

[scout]
count = 1
auto_when_empty = true
""".strip()
            + "\n",
            encoding="utf-8",
        )

    def test_scout_generates_validated_seeds_through_generic_shell_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = self.write_fake_agent(root)
            self.write_shell_runner_config(root, agent, search_pattern="^web search:")

            result = run_cli(["scout", "--count", "1"], root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["accepted"], ["package-warpage-echo-gate-001"])
            self.assertEqual([entry["id"] for entry in payload["rejected"]], ["weak-seed-001"])
            self.assertEqual(payload["failures"], [])

            backlog = [json.loads(line) for line in (root / "state" / "backlog.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(backlog), 1)
            self.assertEqual(backlog[0]["status"], "seed")
            self.assertEqual(backlog[0]["priority"], 110)
            self.assertEqual(backlog[0]["notes"][0]["source"], "patent-loop scout command")
            self.assertEqual(backlog[0]["notes"][0]["closest_art"], ["US1", "US2", "US3"])

    def test_scout_fails_closed_when_shell_runner_shows_no_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = self.write_fake_agent(root)
            self.write_shell_runner_config(root, agent, search_pattern="^LIVE_SEARCH_TOOL:")

            result = run_cli(["scout", "--count", "1"], root)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["accepted"], [])
            self.assertTrue(any("web search is required" in failure for failure in payload["failures"]))
            self.assertFalse((root / "state" / "backlog.jsonl").exists())

    def test_run_scouts_when_backlog_is_empty_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent = self.write_fake_agent(root)
            self.write_shell_runner_config(root, agent, search_pattern="^web search:")

            result = run_cli(["run", "--max-items", "1"], root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            lines = [json.loads(line) for line in result.stdout.strip().splitlines() if line.startswith("{")]
            self.assertEqual(lines[0]["stage"], "scout")
            self.assertEqual(lines[0]["accepted"], ["package-warpage-echo-gate-001"])
            # The same run continues into the idea stage on the freshly scouted seed; the
            # fake agent writes junk there, so the item ends blocked rather than idle.
            self.assertEqual(lines[1]["stage"], "idea")
            self.assertEqual(lines[1]["item_id"], "package-warpage-echo-gate-001")
            self.assertEqual(lines[1]["status"], "blocked")

            # With nothing runnable left, --no-runner only writes a scout prompt and never
            # touches the backlog.
            no_runner = run_cli(["run", "--max-items", "1", "--no-runner"], root)
            self.assertEqual(no_runner.returncode, 0, no_runner.stderr + no_runner.stdout)
            payload = json.loads(no_runner.stdout.strip().splitlines()[-1])
            self.assertEqual((payload["stage"], payload["dry_run"]), ("scout", True))
            backlog = (root / "state" / "backlog.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(backlog), 1)

    def test_shell_runner_placeholders_and_prompt_modes(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import ROOT, build_shell_command, web_search_evidence

        with tempfile.TemporaryDirectory() as tmp:
            fake_runner = Path(tmp) / "runner"
            fake_runner.write_text("#!/bin/sh\n", encoding="utf-8")
            prompt_path = Path(tmp) / "task_prompt.md"
            output_path = Path(tmp) / "out.md"
            cfg = {"command": [str(fake_runner), "--prompt-file", "{prompt_file}", "--out", "{output_path}", "--stage", "{stage}"]}
            command = build_shell_command(cfg, prompt="P", prompt_path=prompt_path, output_path=output_path, stage="examine")
            self.assertEqual(command[2], str(prompt_path))
            self.assertEqual(command[4], str(output_path))
            self.assertEqual(command[6], "examine")

            arg_cfg = {"command": [str(fake_runner), "-p"], "prompt_mode": "arg"}
            self.assertEqual(build_shell_command(arg_cfg, prompt="hello")[-1], "hello")
            root_cfg = {"command": [str(fake_runner), "--cwd", "{root}"]}
            self.assertEqual(build_shell_command(root_cfg)[-1], str(ROOT))
            with self.assertRaises(RuntimeError):
                build_shell_command({"command": [str(fake_runner)], "prompt_mode": "telepathy"})

        self.assertTrue(web_search_evidence("shell", "no pattern configured", ""))
        self.assertTrue(web_search_evidence("shell", "[tool] web_search(q=...)", "", {"web_search_evidence_pattern": r"web_search\("}))
        self.assertFalse(web_search_evidence("shell", "nothing", "", {"web_search_evidence_pattern": r"web_search\("}))
        with self.assertRaises(RuntimeError):
            web_search_evidence("shell", "x", "", {"web_search_evidence_pattern": "web_search("})

    def test_runner_alias_table_and_prompt_delivery_rules(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import build_shell_command, runner_profile, shell_prompt_in_argv

        profile = runner_profile({"runner": {"type": "custom", "custom": {"command": ["my-agent"], "prompt_mode": "arg"}}})
        self.assertEqual(profile["type"], "shell")
        self.assertEqual(profile["command"], ["my-agent"])
        self.assertEqual(profile["prompt_mode"], "arg")
        self.assertNotIn("custom", profile)

        self.assertTrue(shell_prompt_in_argv({"command": ["x", "{prompt}"]}))
        self.assertTrue(shell_prompt_in_argv({"command": ["x"], "prompt_mode": "arg"}))
        self.assertFalse(shell_prompt_in_argv({"command": ["x", "{prompt_file}"]}))
        with tempfile.TemporaryDirectory() as tmp:
            fake_runner = Path(tmp) / "runner"
            fake_runner.write_text("#!/bin/sh\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                build_shell_command({"command": [str(fake_runner), "{prompt}"], "prompt_mode": "arg"}, prompt="p")

    def test_parse_seed_output_accepts_arrays_prose_and_inner_fences(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from patent_loop_harness.cli import parse_seed_output

        self.assertEqual(len(parse_seed_output('Here are the seeds:\n[{"id": "a"}, {"id": "b"}]')), 2)
        self.assertEqual(len(parse_seed_output('```json\n{"seeds": [{"id": "a", "hypothesis": "uses ``` inside"}]}\n```')), 1)
        self.assertEqual(parse_seed_output('{"seeds": [{"id": "a"}, "junk"]}'), [{"id": "a"}])
        with self.assertRaises(RuntimeError):
            parse_seed_output("no json here")

    def test_scout_retry_never_reingests_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Attempt 1: writes seeds but no search evidence. Attempt 2: searched, but
            # writes nothing. The attempt-1 file must not leak into the backlog.
            agent = root / "flaky_agent.py"
            agent.write_text(
                "import json, sys, pathlib\n"
                "prompt_file, output_path = sys.argv[1:3]\n"
                "marker = pathlib.Path(output_path).parent / 'attempted'\n"
                "if not marker.exists():\n"
                "    marker.write_text('1')\n"
                f"    open(output_path, 'w').write(json.dumps({{'seeds': [{{'id': 'leak', 'title': 'Leak', 'hypothesis': {self.VALID_SEED_HYPOTHESIS!r}}}]}}))\n"
                "    raise SystemExit(0)\n"
                "print('web search: second attempt')\n",
                encoding="utf-8",
            )
            self.write_shell_runner_config(root, agent, search_pattern="^web search:")
            result = run_cli(["scout", "--count", "1"], root)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(payload["accepted"], [])
            self.assertFalse(payload["ran"])
            self.assertIn("reason", payload)
            self.assertFalse((root / "state" / "backlog.jsonl").exists())
            status = json.loads((root / "state" / "status.json").read_text(encoding="utf-8")) if (root / "state" / "status.json").exists() else {}
            self.assertNotEqual(status.get("last_completed_stage"), "scout")

    def test_dry_run_skips_out_of_scope_seed_and_previews_next_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            base = {"priority": 100, "status": "seed", "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}
            out_of_scope = {**base, "id": "unrelated-001", "title": "Unrelated", "domain": "other", "hypothesis": "nothing relevant", "priority": 200}
            valid = {**base, "id": "battery-ok-001", "title": "Battery gate", "domain": "ESS", "hypothesis": "battery cell echo residual gate stale"}
            (root / "state" / "backlog.jsonl").write_text(json.dumps(out_of_scope) + "\n" + json.dumps(valid) + "\n", encoding="utf-8")

            result = run_cli(["run", "--dry-run", "--max-items", "2", "--runner", "prompt_only"], root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            lines = [json.loads(line) for line in result.stdout.strip().splitlines() if line.startswith("{")]
            self.assertEqual([line.get("item_id") for line in lines], ["unrelated-001", "battery-ok-001"])
            self.assertEqual(lines[1]["stage"], "idea")
            persisted = [json.loads(line) for line in (root / "state" / "backlog.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({entry["status"] for entry in persisted}, {"seed"})

    def test_init_creates_workbench_with_custom_field_and_keeps_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init = run_cli(
                [
                    "init",
                    "--field",
                    "medical imaging software",
                    "--field-description",
                    "Software tied to image acquisition, reconstruction, and QC gates.",
                    "--field-domain",
                    "CT reconstruction, MRI QC",
                    "--runner",
                    "claude",
                ],
                root,
            )
            self.assertEqual(init.returncode, 0, init.stderr + init.stdout)
            for rel in ["config", "state", "work", "final", "reports", "visuals", "logs", "memory"]:
                self.assertTrue((root / rel).is_dir(), rel)
            self.assertTrue((root / ".gitignore").exists())
            status = run_cli(["status"], root)
            self.assertEqual(status.returncode, 0, status.stderr + status.stdout)
            self.assertIn("field: medical imaging software", status.stdout)
            self.assertIn("runner: claude", status.stdout)

            config_text = (root / "config" / "patent_loop.toml").read_text(encoding="utf-8")
            again = run_cli(["init", "--field", "other field"], root)
            self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
            self.assertIn("kept existing", again.stdout)
            self.assertEqual((root / "config" / "patent_loop.toml").read_text(encoding="utf-8"), config_text)

            forced = run_cli(["init", "--field", "other field", "--force"], root)
            self.assertEqual(forced.returncode, 0, forced.stderr + forced.stdout)
            self.assertIn("field: other field", run_cli(["status"], root).stdout)

    def test_init_without_field_warns_about_bundled_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init = run_cli(["init"], root)
            self.assertEqual(init.returncode, 0, init.stderr + init.stdout)
            self.assertIn("bundled battery-industry field applies", init.stdout)
            self.assertIn("runner: codex", run_cli(["status"], root).stdout)


if __name__ == "__main__":
    unittest.main()
