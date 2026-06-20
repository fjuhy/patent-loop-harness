#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import glob
from importlib import resources
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


ROOT = Path(os.environ.get("PATENT_LOOP_ROOT", os.getcwd())).resolve()
CONFIG_PATH = ROOT / "config" / "patent_loop.toml"
BACKLOG_PATH = ROOT / "state" / "backlog.jsonl"
STATUS_PATH = ROOT / "state" / "status.json"
GUARDRAILS_PATH = ROOT / "state" / "guardrails.md"
SEED_IDEATION_PATH = ROOT / "state" / "seed_ideation_strategy.md"
SEED_PREFLIGHT_PATH = ROOT / "state" / "seed_prior_art_preflight.md"
HEARTBEAT_STATE_PATH = ROOT / "state" / "heartbeat-state.json"
LOCK_PATH = ROOT / "state" / "loop.lock"
METRICS_PATH = ROOT / "logs" / "metrics.jsonl"
PACKAGE = "patent_loop_harness"
DEFAULT_CODEX_ENV_ALLOWLIST = [
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "CODEX_HOME",
]

TERMINAL_STATUSES = {"finalized", "finalized_out_of_scope", "rejected", "blocked"}
PROMPTS = {
    "idea": "10_idea_scout.md",
    "research": "15_prior_art_gate.md",
    "draft": "20_draft_writer.md",
    "examine": "30_patentability_examiner.md",
    "redteam": "35_context_free_red_team.md",
    "revise": "40_revision_writer.md",
    "finalize": "50_finalizer.md",
    "verify": "60_independent_verifier.md",
    "external_spotcheck": "65_external_prior_art_spotcheck.md",
    "visualize": "70_visual_explainer.md",
}


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def slug_time() -> str:
    return dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    append_text(path, json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def bundled_text(relative_path: str) -> str:
    return resources.files(PACKAGE).joinpath(relative_path).read_text(encoding="utf-8")


def read_prompt(name: str) -> str:
    workspace_prompt = ROOT / "prompts" / name
    if workspace_prompt.exists():
        return read_text(workspace_prompt)
    return bundled_text(f"prompts/{name}")


def load_config() -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required for tomllib TOML parsing.")
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as handle:
            return tomllib.load(handle)
    return tomllib.loads(bundled_text("default_config.toml"))


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def save_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_backlog() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not BACKLOG_PATH.exists():
        return items
    for line_no, line in enumerate(BACKLOG_PATH.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSONL in {BACKLOG_PATH}:{line_no}: {exc}") from exc
    return items


def save_backlog(items: list[dict[str, Any]]) -> None:
    lines = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in items]
    write_text(BACKLOG_PATH, "\n".join(lines) + ("\n" if lines else ""))


def ensure_layout() -> None:
    for rel in ["config", "prompts", "state", "work", "final", "reports", "visuals", "logs", "memory"]:
        (ROOT / rel).mkdir(parents=True, exist_ok=True)


class LoopLock:
    def __init__(self, path: Path, stale_seconds: int = 6 * 3600) -> None:
        self.path = path
        self.stale_seconds = stale_seconds
        self.acquired = False

    def __enter__(self) -> "LoopLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = time.time() - self.path.stat().st_mtime
            if age < self.stale_seconds:
                raise RuntimeError(f"Loop already running: {self.path}")
            self.path.unlink()
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "created_at": now()}, ensure_ascii=False))
        self.acquired = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def stage_for(item: dict[str, Any]) -> str | None:
    status = item.get("status", "seed")
    if status == "seed":
        return "idea"
    if status == "idea_ready":
        return "research"
    if status == "research_ready":
        return "draft"
    if status == "draft_ready":
        return "examine"
    if status == "needs_revision":
        return "revise"
    if status == "examiner_passed":
        return "redteam"
    if status == "redteam_passed":
        return "finalize"
    if status == "final_ready":
        return "verify"
    if status == "external_spotcheck_ready":
        return "external_spotcheck"
    if status == "visualization_ready":
        return "visualize"
    return None


def next_item(
    items: list[dict[str, Any]],
    stage_only: str | None = None,
    field: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    candidates = [item for item in items if item.get("status") not in TERMINAL_STATUSES and stage_for(item)]
    if stage_only:
        candidates = [item for item in candidates if stage_for(item) == stage_only]
    if field and bool(field.get("filter_backlog", False)):
        candidates = [item for item in candidates if is_in_field_scope_text(item_scope_text(item), field)]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-int(item.get("priority", 0)), item.get("updated_at", "")))
    return candidates[0]


def root_relative_path(raw: Any) -> Path:
    path = Path(str(raw)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def parse_percent(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return float(text)
    except ValueError:
        return None


def nested_percent(data: dict[str, Any], paths: list[tuple[str, ...]]) -> float | None:
    for path in paths:
        current: Any = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                current = None
                break
            current = current[key]
        percent = parse_percent(current)
        if percent is not None:
            return percent
    return None


def codex_usage_from_state_file(path: Path) -> dict[str, Any] | None:
    data = load_json(path, None)
    if not isinstance(data, dict):
        return None
    percent = nested_percent(
        data,
        [
            ("weekly_used_percent",),
            ("used_percent",),
            ("codex_weekly_used_percent",),
            ("secondary", "used_percent"),
            ("rate_limits", "secondary", "used_percent"),
        ],
    )
    if percent is None:
        return None
    return {"source": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path), "used_percent": percent}


def codex_usage_from_sessions(guard_cfg: dict[str, Any]) -> dict[str, Any] | None:
    pattern = os.path.expanduser(str(guard_cfg.get("codex_sessions_glob", "~/.codex/sessions/**/*.jsonl")))
    max_files = max(1, int(guard_cfg.get("max_session_files", 120)))
    weekly_window = int(guard_cfg.get("weekly_window_minutes", 10080))
    paths = [Path(path) for path in glob.glob(pattern, recursive=True)]
    paths = sorted(paths, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)[:max_files]
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "token_count":
                continue
            rate_limits = payload.get("rate_limits")
            if not isinstance(rate_limits, dict):
                continue
            secondary = rate_limits.get("secondary")
            if not isinstance(secondary, dict):
                continue
            if int(secondary.get("window_minutes", 0)) != weekly_window:
                continue
            percent = parse_percent(secondary.get("used_percent"))
            if percent is None:
                continue
            return {
                "source": str(path),
                "used_percent": percent,
                "timestamp": record.get("timestamp"),
                "resets_at": secondary.get("resets_at"),
            }
    return None


def codex_weekly_usage(config: dict[str, Any]) -> dict[str, Any] | None:
    guard_cfg = config.get("usage_guard", {})
    if not bool(guard_cfg.get("enabled", False)):
        return None
    env_var = str(guard_cfg.get("env_var", "CODEX_WEEKLY_USED_PERCENT"))
    percent = parse_percent(os.environ.get(env_var))
    if percent is not None:
        return {"source": f"env:{env_var}", "used_percent": percent}

    state_path = root_relative_path(guard_cfg.get("state_path", "state/codex_usage.json"))
    state_usage = codex_usage_from_state_file(state_path)
    if state_usage:
        return state_usage
    return codex_usage_from_sessions(guard_cfg)


def usage_guard_for_item(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    guard_cfg = config.get("usage_guard", {})
    if not bool(guard_cfg.get("enabled", False)):
        return None
    stage = stage_for(item)
    if bool(guard_cfg.get("check_only_before_new_idea", True)):
        if stage != "idea" or item.get("status", "seed") != "seed":
            return None
    usage = codex_weekly_usage(config)
    threshold = float(guard_cfg.get("max_weekly_used_percent", 70.0))
    if usage is None:
        event = {
            "at": now(),
            "event": "usage_guard_unknown",
            "item_id": item.get("id"),
            "stage": stage,
            "threshold_percent": threshold,
        }
        append_jsonl(METRICS_PATH, event)
        if bool(guard_cfg.get("fail_closed_on_unknown", False)):
            return {
                "ran": False,
                "stage": stage,
                "item_id": item.get("id"),
                "status": item.get("status"),
                "reason": "codex weekly usage is unknown and fail_closed_on_unknown=true",
            }
        return None

    percent = float(usage["used_percent"])
    event = {
        "at": now(),
        "event": "usage_guard_check",
        "item_id": item.get("id"),
        "stage": stage,
        "used_percent": percent,
        "threshold_percent": threshold,
        "source": usage.get("source"),
        "blocked": percent >= threshold,
    }
    append_jsonl(METRICS_PATH, event)
    if percent >= threshold:
        return {
            "ran": False,
            "stage": stage,
            "item_id": item.get("id"),
            "status": item.get("status"),
            "reason": f"codex weekly usage {percent:.1f}% >= {threshold:.1f}%; stop before starting a new idea",
            "usage_percent": percent,
            "threshold_percent": threshold,
            "usage_source": usage.get("source"),
        }
    return None


def count_claims(text: str) -> int:
    patterns = [
        r"청구항\s*\d+",
        r"^\s*\d+\.\s+.*?청구",
    ]
    counts = [len(re.findall(pattern, text, flags=re.MULTILINE)) for pattern in patterns]
    return max(counts) if counts else 0


def has_any(text: str, needles: list[str]) -> bool:
    return any(needle in text for needle in needles)


SEED_FEATURE_GROUPS = {
    "physical_challenge": [
        "challenge",
        "probe",
        "stimulus",
        "chirp",
        "dither",
        "marker",
        "pilot",
        "ping",
        "pulse",
        "micro-step",
        "load-step",
        "echo",
        "read probe",
        "자극",
        "명령",
    ],
    "response_signature": [
        "signature",
        "residual",
        "phase",
        "skew",
        "drift",
        "ringdown",
        "impedance",
        "syndrome",
        "response",
        "slope",
        "latency",
        "gradient",
        "mode shift",
        "signature",
        "응답",
        "잔차",
    ],
    "specific_control_gate": [
        "admission",
        "lock",
        "fence",
        "quarantine",
        "exclude",
        "routing",
        "forwarding",
        "inhibit",
        "permission",
        "gate",
        "회수",
        "금지",
        "잠그",
        "제외",
        "재배치",
    ],
    "freshness_or_fail_closed": [
        "fail-closed",
        "stale",
        "replay",
        "calibration",
        "freshness",
        "evidence",
        "hash",
        "signed",
        "version",
        "safe-state",
        "검증 실패",
        "보정",
    ],
}


BATTERY_REPEAT_RISK_TERMS = [
    "thermal runaway",
    "열폭주",
    "precharge",
    "contactor",
    "charger handshake",
    "battery passport",
    "federated",
    "soh",
    "ota",
    "attestation",
    "derating token",
]


BATTERY_SW_SCOPE_TERMS = [
    "battery",
    "bms",
    "ess",
    "pcs",
    "pack",
    "cell",
    "module",
    "soh",
    "soc",
    "sop",
    "degradation",
    "charging",
    "charger",
    "balancing",
    "배터리",
    "전지",
    "셀",
    "모듈",
    "팩",
    "비엠에스",
    "충전",
    "열화",
    "수명",
    "냉각",
    "절연",
    "밸런싱",
    "진단",
    "검증",
    "시뮬레이터",
    "디지털 트윈",
    "에너지 저장",
]


HARD_FAIL_CLOSED_TERMS = [
    "fail-closed",
    "stale",
    "replay",
    "calibration",
    "freshness",
    "safe-state",
    "expired",
    "epoch",
    "version mismatch",
    "검증 실패",
    "보정",
    "만료",
    "불일치",
    "재생",
]


DEFAULT_FIELD_NAME = "battery-industry software"
DEFAULT_FIELD_DESCRIPTION = (
    "Battery-industry software tied directly to BMS, ESS, PCS, pack/cell/module, charger, "
    "SOH/SOC/SOP, battery logs/data, cloud, digital-twin, simulator, or verification boundaries."
)
DEFAULT_FIELD_BINDING_LABEL = "배터리 산업 SW 직접 결속"
DEFAULT_FIELD_MICRO_BOUNDARY_LABEL = "배터리 SW micro-boundary"
DEFAULT_FIELD_MICRO_BOUNDARY_COLUMN = "battery SW micro-boundary"
FIELD_TERM_STOPWORDS = {
    "advanced",
    "application",
    "control",
    "field",
    "method",
    "patent",
    "software",
    "system",
    "tech",
    "technical",
    "technology",
}


def listify(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    output: list[str] = []
    for raw in values:
        for piece in re.split(r"[,;\n]", str(raw)):
            text = piece.strip()
            if text:
                output.append(text)
    return output


def merge_unique(*groups: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for group in groups:
        for value in group:
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            output.append(value)
    return output


def field_terms_from_text(text: str) -> list[str]:
    terms = [text.strip()] if text.strip() else []
    terms.extend(
        term
        for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9+/._-]{2,}|[가-힣]{2,}", text)
        if term.casefold() not in FIELD_TERM_STOPWORDS
    )
    return merge_unique(terms)


def add_field_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--field",
        default="",
        help="override target patent research field for this invocation",
    )
    parser.add_argument(
        "--field-domain",
        action="append",
        default=[],
        help="allowed/narrow domain within --field; repeat or comma-separate",
    )
    parser.add_argument(
        "--field-term",
        action="append",
        default=[],
        help="term that marks backlog/artifacts as in-scope for --field; repeat or comma-separate",
    )
    parser.add_argument(
        "--field-instruction",
        action="append",
        default=[],
        help="extra field-specific instruction injected into generated task prompts",
    )
    parser.add_argument(
        "--no-scope-guard",
        action="store_true",
        help="do not reject/skip seeds solely because they miss field scope terms",
    )


def apply_field_args(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    field_arg = str(getattr(args, "field", "") or "").strip()
    field_domains = listify(getattr(args, "field_domain", []))
    field_terms = listify(getattr(args, "field_term", []))
    field_instructions = listify(getattr(args, "field_instruction", []))

    if not (field_arg or field_domains or field_terms or field_instructions or getattr(args, "no_scope_guard", False)):
        return config

    updated = dict(config)
    field_cfg = dict(updated.get("field", {}))
    if field_arg:
        field_cfg["name"] = field_arg
        field_cfg["description"] = field_arg
        field_cfg["binding_label"] = "조사 분야 직접 결속"
        field_cfg["micro_boundary_label"] = "조사 분야 micro-boundary"
        field_cfg["micro_boundary_column"] = "target-field micro-boundary"
        field_cfg["scope_terms"] = merge_unique(field_terms_from_text(field_arg), field_domains, field_terms)
        field_cfg["high_risk_terms"] = []
        field_cfg["strict_battery_sections"] = False
        field_cfg["filter_backlog"] = True
    elif field_terms:
        field_cfg["scope_terms"] = merge_unique(listify(field_cfg.get("scope_terms")), field_terms)

    if field_domains:
        field_cfg["domains"] = field_domains
    if field_instructions:
        field_cfg["instructions"] = merge_unique(listify(field_cfg.get("instructions")), field_instructions)
    if getattr(args, "no_scope_guard", False):
        field_cfg["scope_guard_enabled"] = False

    updated["field"] = field_cfg
    return updated


def is_battery_profile_text(text: str) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in ["battery", "bms", "ess", "배터리", "전지", "pcs"])


def field_profile(config: dict[str, Any]) -> dict[str, Any]:
    field_cfg = config.get("field", {})
    domains = listify(field_cfg.get("domains")) or listify(config.get("loop", {}).get("domains"))
    name = str(field_cfg.get("name") or DEFAULT_FIELD_NAME).strip()
    description = str(field_cfg.get("description") or DEFAULT_FIELD_DESCRIPTION).strip()
    scope_terms = listify(field_cfg.get("scope_terms")) or BATTERY_SW_SCOPE_TERMS
    profile_text = " ".join([name, description, " ".join(domains), " ".join(scope_terms)])
    battery_default = is_battery_profile_text(profile_text)
    high_risk_terms = listify(field_cfg.get("high_risk_terms"))
    if not high_risk_terms and battery_default:
        high_risk_terms = BATTERY_REPEAT_RISK_TERMS
    strict_battery_sections = bool(field_cfg.get("strict_battery_sections", battery_default))
    return {
        "name": name,
        "description": description,
        "domains": domains,
        "scope_terms": scope_terms,
        "scope_guard_enabled": bool(field_cfg.get("scope_guard_enabled", True)),
        "high_risk_terms": high_risk_terms,
        "binding_label": str(field_cfg.get("binding_label") or DEFAULT_FIELD_BINDING_LABEL),
        "micro_boundary_label": str(field_cfg.get("micro_boundary_label") or DEFAULT_FIELD_MICRO_BOUNDARY_LABEL),
        "micro_boundary_column": str(field_cfg.get("micro_boundary_column") or DEFAULT_FIELD_MICRO_BOUNDARY_COLUMN),
        "instructions": listify(field_cfg.get("instructions")),
        "strict_battery_sections": strict_battery_sections,
        "filter_backlog": bool(field_cfg.get("filter_backlog", False)),
        "battery_default": battery_default,
    }


def field_heading_options(field: dict[str, Any], key: str) -> list[str]:
    if key == "micro_boundary":
        if bool(field.get("strict_battery_sections", False)):
            return [str(field["micro_boundary_label"])]
        return merge_unique(
            [str(field["micro_boundary_label"])],
            [DEFAULT_FIELD_MICRO_BOUNDARY_LABEL, "조사 분야 micro-boundary", "target-field micro-boundary"],
        )
    if key == "binding":
        if bool(field.get("strict_battery_sections", False)):
            return [str(field["binding_label"])]
        return merge_unique(
            [str(field["binding_label"])],
            [DEFAULT_FIELD_BINDING_LABEL, "조사 분야 직접 결속", "target field binding"],
        )
    return []


def field_column_options(field: dict[str, Any], key: str) -> list[str]:
    if key == "micro_boundary":
        if bool(field.get("strict_battery_sections", False)):
            return [str(field["micro_boundary_column"])]
        return merge_unique(
            [str(field["micro_boundary_column"])],
            [DEFAULT_FIELD_MICRO_BOUNDARY_COLUMN, "target-field micro-boundary", "조사 분야 micro-boundary"],
        )
    return []


def has_any_heading(text: str, headings: list[str]) -> bool:
    return any(re.search(rf"^##\s+{re.escape(heading)}\s*$", text, flags=re.MULTILINE) for heading in headings)


def has_any_term(text: str, terms: list[str]) -> bool:
    lowered = text.casefold()
    return any(term.casefold() in lowered for term in terms)


def is_in_field_scope_text(text: str, field: dict[str, Any]) -> bool:
    if not bool(field.get("scope_guard_enabled", True)):
        return True
    terms = listify(field.get("scope_terms"))
    if not terms:
        return True
    return has_any_term(text, terms)


def validate_seed_item(item: dict[str, Any], config: dict[str, Any]) -> list[str]:
    if item.get("status") != "seed":
        return []
    field = field_profile(config)
    failures: list[str] = []
    for key in ["id", "title", "domain", "hypothesis", "priority", "created_at", "updated_at"]:
        if not item.get(key):
            failures.append(f"seed missing required field: {key}")
    item_id = str(item.get("id", ""))
    if item_id and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}", item_id):
        failures.append("seed id must be lowercase-kebab-case ending in -NNN")
    hypothesis = str(item.get("hypothesis", ""))
    if len(hypothesis) < 100:
        failures.append("seed hypothesis is too short to encode a narrow causal chain")

    text = " ".join(
        [
            str(item.get("id", "")),
            str(item.get("title", "")),
            str(item.get("domain", "")),
            hypothesis,
            json.dumps(item.get("notes", []), ensure_ascii=False),
        ]
    ).lower()
    if not is_in_field_scope_text(text, field):
        failures.append(f"seed is outside target field scope: {field['name']}")
    matched_groups = [
        name
        for name, terms in SEED_FEATURE_GROUPS.items()
        if any(term.lower() in text for term in terms)
    ]
    if len(matched_groups) < 3:
        failures.append(
            "seed lacks at least 3 low-pass-rate counterfeatures: "
            + ", ".join(SEED_FEATURE_GROUPS)
            + f" (matched: {', '.join(matched_groups) or 'none'})"
        )
    hypothesis_text = hypothesis.lower()
    if not any(term.lower() in hypothesis_text for term in HARD_FAIL_CLOSED_TERMS):
        failures.append("seed hypothesis lacks explicit stale/replay/calibration/fail-closed invalidity trigger")

    high_risk_terms = listify(field.get("high_risk_terms"))
    repeats = [term for term in high_risk_terms if term.casefold() in text.casefold()]
    if repeats:
        failures.append(f"seed repeats high-risk {field['name']} cluster terms: " + ", ".join(repeats))
    return failures


def item_scope_text(item: dict[str, Any]) -> str:
    return " ".join(
        [
            str(item.get("id", "")),
            str(item.get("title", "")),
            str(item.get("domain", "")),
            str(item.get("hypothesis", "")),
        ]
    ).lower()


def reject_out_of_scope_seed(item: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    if item.get("status") != "seed":
        return None
    field = field_profile(config)
    if is_in_field_scope_text(item_scope_text(item), field):
        return None
    item["status"] = "rejected"
    item["updated_at"] = now()
    item.setdefault("notes", []).append(
        {
            "at": now(),
            "stage": "scope_guard",
            "decision": "REJECT_OUT_OF_SCOPE",
            "reason": f"Seed is not directly tied to the configured target field: {field['name']}.",
        }
    )
    return {
        "ran": False,
        "stage": "idea",
        "item_id": item.get("id"),
        "status": "rejected",
        "reason": f"seed outside target field scope: {field['name']}",
    }


GRADE_ORDER = {
    "A+": 12,
    "A": 11,
    "A-": 10,
    "B+": 9,
    "B": 8,
    "B-": 7,
    "C+": 6,
    "C": 5,
    "C-": 4,
    "D": 3,
    "F": 0,
}


def grade_value(raw: str) -> int | None:
    return GRADE_ORDER.get(raw.strip().upper())


def grade_aliases(label: str) -> list[str]:
    aliases = {
        "명세서 뒷받침/명확성": [
            "명세서 뒷받침/명확성",
            "명확성",
            "명확성/기재요건",
            "기재요건/명확성",
            "기재요건/실시가능성",
            "기재요건",
        ],
    }
    return aliases.get(label, [label])


def extract_grade(text: str, label: str) -> str | None:
    grades: list[str] = []
    for candidate in grade_aliases(label):
        line_pattern = re.compile(
            rf"^\s*(?:[-*]\s*)?{re.escape(candidate)}\s*:\s*([A-F][+-]?)\b",
            re.MULTILINE,
        )
        table_pattern = re.compile(
            rf"^\s*\|\s*{re.escape(candidate)}\s*\|\s*([A-F][+-]?)\s*\|",
            re.MULTILINE,
        )
        grades.extend(match.group(1).upper() for match in line_pattern.finditer(text))
        grades.extend(match.group(1).upper() for match in table_pattern.finditer(text))
    if not grades:
        return None
    return min(grades, key=lambda raw: grade_value(raw) if grade_value(raw) is not None else -1)



def grade_failures(text: str, config: dict[str, Any], labels: list[str] | None = None) -> list[str]:
    min_grade = str(config["quality"].get("min_grade_for_pass", "A-")).upper()
    min_value = grade_value(min_grade)
    if min_value is None:
        return [f"invalid configured min_grade_for_pass={min_grade}"]
    labels = labels or ["신규성", "진보성", "명세서 뒷받침/명확성", "권리범위 방어력"]
    failures: list[str] = []
    for label in labels:
        raw = extract_grade(text, label)
        if raw is None:
            failures.append(f"missing grade: {label}")
            continue
        value = grade_value(raw)
        if value is None or value < min_value:
            failures.append(f"grade {label}={raw} < {min_grade}")
    ambiguous_pass = re.compile(
        r"조건부\s*(?:출원|통과|진행|합격|가치)|중간\s*이상|보완\s*필요|간신히\s*통과"
    )
    if bool(config["quality"].get("forbid_conditional_pass", True)):
        for match in ambiguous_pass.finditer(text):
            context = text[max(0, match.start() - 80) : match.end() + 120]
            if re.search(
                r"아니라|아니다|아님|아닌|않는다|않음|없다|부여하지|금지|통과가\s*아니|반려|거절|미달|"
                r"REJECT|KILL|NEED_MORE_SEARCH|"
                r"Narrowing Lock|독립항\s*필수|필수\s*구성|전부를\s*독립항",
                context,
                flags=re.IGNORECASE,
            ):
                continue
            failures.append("contains conditional/ambiguous pass language")
            break
    return failures


def decision(path: Path) -> str | None:
    text = read_text(path)
    matches = re.findall(r"GO_DECISION:\s*(PROCEED_NARROW|NEED_MORE_SEARCH|KILL)", text)
    return matches[-1] if matches else None


def requires_strict_idea_screening(item: dict[str, Any] | None) -> bool:
    if item is None:
        return True
    return item.get("status", "seed") not in TERMINAL_STATUSES


def markdown_table_data_rows(text: str) -> int:
    rows = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if cells[0] in {"후보", "candidate", "Candidate"}:
            continue
        rows += 1
    return rows


def idea_screening_failures(text: str, field: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    micro_boundary_headings = field_heading_options(field, "micro_boundary")
    binding_labels = field_heading_options(field, "binding")
    micro_boundary_columns = field_column_options(field, "micro_boundary")

    if "## Seed 자체 평가" not in text:
        failures.append("missing section: ## Seed 자체 평가")
    if not has_any_heading(text, micro_boundary_headings):
        failures.append(f"missing section: ## {field['micro_boundary_label']}")
    if "## 선행특허 클러스터 프리플라이트" not in text:
        failures.append("missing section: ## 선행특허 클러스터 프리플라이트")
    if "## Problem-Solution Seed Map" not in text:
        failures.append("missing section: ## Problem-Solution Seed Map")
    if "## 미청구 구현 빈틈" not in text:
        failures.append("missing section: ## 미청구 구현 빈틈")
    if "## 창의성 렌즈 적용" not in text:
        failures.append("missing section: ## 창의성 렌즈 적용")
    if "SEED_DECISION:" not in text:
        failures.append("missing SEED_DECISION token")
    seed_eval = section_text(text, "Seed 자체 평가")
    if not any(f"{label}:" in seed_eval for label in binding_labels):
        failures.append(f"missing target field binding line in Seed 자체 평가: {field['binding_label']}:")

    preflight = section_text(text, "선행특허 클러스터 프리플라이트")
    if not preflight.strip():
        failures.append("missing section content: ## 선행특허 클러스터 프리플라이트")
    else:
        preflight_columns = [
            ["후보"],
            micro_boundary_columns,
            ["closest patent cluster"],
            ["공개된 구성"],
            ["미청구 구현 빈틈"],
            ["103 조합 위험"],
            ["진행 판단"],
        ]
        failures.extend(
            [
                f"missing preflight column: {' or '.join(names)}"
                for names in preflight_columns
                if not any(name in preflight for name in names)
            ]
        )
        preflight_rows = markdown_table_data_rows(preflight)
        if preflight_rows < 8:
            failures.append(f"prior-art cluster preflight rows {preflight_rows} < 8")

    gap = section_text(text, "미청구 구현 빈틈")
    for token in ["UNCOVERED_GAP:", "NEW_INTERNAL_CONTRACT:", "WHY_NOT_OBVIOUS_OVER_CLUSTER:"]:
        if token not in gap:
            failures.append(f"missing uncovered-gap token: {token}")
    if not any(token in gap for token in ["BATTERY_SW_BOUNDARY:", "TARGET_FIELD_BOUNDARY:", "FIELD_BOUNDARY:"]):
        failures.append("missing uncovered-gap token: TARGET_FIELD_BOUNDARY: or BATTERY_SW_BOUNDARY:")
    if "SKELETON_FAMILY:" not in gap:
        failures.append("missing uncovered-gap token: SKELETON_FAMILY:")

    problem_solution = section_text(text, "Problem-Solution Seed Map")
    for token in [
        "CLOSEST_SINGLE_ART_OR_CLUSTER:",
        "OBJECTIVE_TECHNICAL_PROBLEM:",
        "WHY_STANDARD_COMBINATION_IS_WEAK:",
        "SKELETON_FAMILY:",
    ]:
        if token not in problem_solution:
            failures.append(f"missing problem-solution seed token: {token}")

    section = section_text(text, "후보군 스크리닝")
    if not section.strip():
        failures.append("missing section: ## 후보군 스크리닝")
        return failures
    required_columns = [
        "후보",
        "창의성 렌즈",
        "analog source",
        "skeleton family",
        "active challenge",
        "response signature/residual",
        "specific gate",
        "예상 closest prior art",
        "중복/저품질 위험",
        "seed action",
        "선택/탈락 이유",
    ]
    failures.extend([f"missing idea screening column: {name}" for name in required_columns if name not in section])
    row_count = markdown_table_data_rows(section)
    if row_count < 8:
        failures.append(f"idea screening candidate rows {row_count} < 8")
    return failures


def validate_stage(stage: str, path: Path, config: dict[str, Any], item: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    text = read_text(path)
    failures: list[str] = []
    field = field_profile(config)
    if not text.strip():
        return False, [f"{path} is empty or missing"]

    if stage == "idea":
        required = ["# 아이디어 후보", "## 발명명", "## 핵심 기술 구성", "## 예상 선행기술 후보", "## 독립항 후보"]
        failures.extend([f"missing section: {name}" for name in required if name not in text])
        if not is_in_field_scope_text(text, field):
            failures.append(f"idea output is outside target field scope: {field['name']}")
        if requires_strict_idea_screening(item):
            failures.extend(idea_screening_failures(text, field))
    elif stage == "research":
        required = [
            "# 선행기술 Kill-or-Narrow 보고서",
            "## 넓은 표현",
            "## 좁은 생존 표현",
            "## 검색 범위 및 한계",
            "## 검색 쿼리 로그",
            "## 가장 가까운 선행기술 후보",
            "## 102 신규성 공격",
            "## 103 진보성 공격",
            "## Narrowing Lock",
            "## 필수 실시예 요구사항",
            "## 심사 점수표",
            "GO_DECISION:",
        ]
        if requires_strict_idea_screening(item):
            required.append("## Problem-Solution 판단")
        failures.extend([f"missing research section: {name}" for name in required if name not in text])
        if requires_strict_idea_screening(item):
            problem_solution = section_text(text, "Problem-Solution 판단")
            for token in ["CLOSEST_SINGLE_ART:", "OBJECTIVE_TECHNICAL_PROBLEM:", "WOULD_COMBINE_REASON:", "WHY_SURVIVES_OR_FAILS:"]:
                if token not in problem_solution:
                    failures.append(f"missing problem-solution research token: {token}")
        gate_decision = decision(path)
        if not gate_decision:
            failures.append("missing valid GO_DECISION token")
        if gate_decision == "PROCEED_NARROW":
            query_count = bullet_count(section_text(text, "검색 쿼리 로그"))
            min_queries = int(config["quality"].get("min_prior_art_search_queries", 8))
            if query_count < min_queries:
                failures.append(f"research search query count {query_count} < {min_queries}")
            reference_count = bullet_count(section_text(text, "가장 가까운 선행기술 후보"))
            min_refs = int(config["quality"].get("min_closest_references", 8))
            if reference_count < min_refs:
                failures.append(f"closest reference count {reference_count} < {min_refs}")
            failures.extend(grade_failures(text, config))
    elif stage in {"draft", "revise"}:
        min_claims = int(config["loop"].get("min_claims_for_draft", 12))
        required = [
            "기술분야",
            "배경기술",
            "발명이 해결하려는 과제",
            "과제의 해결수단",
            "선행기술 회피를 위한 필수 결합",
            "핵심 계산/판단 실시예",
            "가장 가까운 선행기술 대비표",
            "청구범위",
        ]
        failures.extend([f"missing draft section: {name}" for name in required if name not in text])
        claims = count_claims(text)
        if claims < min_claims:
            failures.append(f"claim count {claims} < {min_claims}")
    elif stage == "examine":
        required = ["# 특허성 심사 보고서", "## 선행기술 후보", "## 심사관 A 판단", "## 심사관 B 판단", "## 신규성 판단", "## 진보성 판단", "FINAL_VERDICT:"]
        failures.extend([f"missing examiner section: {name}" for name in required if name not in text])
        strict_required = ["## 검색 쿼리 로그", "## 독립항 1 구성요소별 선행기술 매핑", "## 외부 신규 심사관 리스크"]
        failures.extend([f"missing strict examiner section: {name}" for name in strict_required if name not in text])
        query_count = bullet_count(section_text(text, "검색 쿼리 로그"))
        min_queries = int(config["quality"].get("min_prior_art_search_queries", 8))
        if query_count < min_queries:
            failures.append(f"search query log count {query_count} < {min_queries}")
        if "## 심사 점수표" not in text:
            failures.append("missing strict examiner section: ## 심사 점수표")
        if verdict(path) == "DIRECT_OK":
            failures.extend(grade_failures(text, config))
        if not has_any(text, ["FINAL_VERDICT: DIRECT_OK", "FINAL_VERDICT: REJECT"]):
            failures.append("missing valid FINAL_VERDICT token")
    elif stage == "redteam":
        required = [
            "# 문맥 차단 레드팀 보고서",
            "## 독립항 1 구성요소 분해",
            "## 검색 쿼리 로그",
            "## 가장 가까운 선행기술 후보",
            "## 102 신규성 공격",
            "## 103 진보성 공격",
            "## 문서 자체의 방어 논리",
            "FINAL_VERDICT:",
        ]
        failures.extend([f"missing redteam section: {name}" for name in required if name not in text])
        query_count = bullet_count(section_text(text, "검색 쿼리 로그"))
        min_queries = int(config["quality"].get("min_prior_art_search_queries", 8))
        if query_count < min_queries:
            failures.append(f"redteam search query count {query_count} < {min_queries}")
        if "## 심사 점수표" not in text:
            failures.append("missing redteam section: ## 심사 점수표")
        if verdict(path) == "DIRECT_OK":
            failures.extend(grade_failures(text, config))
        if not has_any(text, ["FINAL_VERDICT: DIRECT_OK", "FINAL_VERDICT: REJECT"]):
            failures.append("missing valid FINAL_VERDICT token")
    elif stage == "finalize":
        min_claims = int(config["loop"].get("min_claims_for_final", 18))
        required = [
            "# 최종 특허 명세서 후보",
            "## 문맥 독립 요약",
            "## 최종 전략 메모",
            "## 가장 가까운 선행기술 대비표",
            "## 독립항 1 구성요소 매핑",
            "## 청구범위",
            "## 요약서",
        ]
        failures.extend([f"missing final section: {name}" for name in required if name not in text])
        claims = count_claims(text)
        if claims < min_claims:
            failures.append(f"claim count {claims} < {min_claims}")
    elif stage == "verify":
        required = ["# 독립 검증 보고서", "## 통과 항목", "## 외부 신규 평가자 거절 시나리오", "## 최종 판정", "FINAL_VERDICT:"]
        failures.extend([f"missing verifier section: {name}" for name in required if name not in text])
        if "## 심사 점수표" not in text:
            failures.append("missing verifier section: ## 심사 점수표")
        if verdict(path) == "DIRECT_OK":
            failures.extend(grade_failures(text, config))
    elif stage == "external_spotcheck":
        required = [
            "# 외부 선행기술 Spot Check 보고서",
            "## 검색 범위 및 한계",
            "## 검색 쿼리 로그",
            "## 새로 확인한 외부 선행기술",
            "## 독립항 1 구성요소별 외부 매핑",
            "## 102 신규성 재공격",
            "## 103 진보성 재공격",
            "## 하네스 통과판정 재검토",
            "## 재판정",
            "## 심사 점수표",
            "FINAL_VERDICT:",
        ]
        failures.extend([f"missing external spotcheck section: {name}" for name in required if name not in text])
        query_count = bullet_count(section_text(text, "검색 쿼리 로그"))
        min_queries = int(config["quality"].get("min_prior_art_search_queries", 8))
        if query_count < min_queries:
            failures.append(f"external spotcheck search query count {query_count} < {min_queries}")
        reference_count = bullet_count(section_text(text, "새로 확인한 외부 선행기술"))
        min_refs = int(config["quality"].get("min_closest_references", 8))
        if reference_count < min_refs:
            failures.append(f"external spotcheck reference count {reference_count} < {min_refs}")
        if verdict(path) == "DIRECT_OK":
            failures.extend(grade_failures(text, config))
        if not has_any(text, ["FINAL_VERDICT: DIRECT_OK", "FINAL_VERDICT: REJECT"]):
            failures.append("missing valid FINAL_VERDICT token")
    elif stage == "visualize":
        lowered = text.lower()
        required = [
            "<!doctype html",
            "<html",
            "<style",
            "<svg",
            "요약",
            "배경",
            "해결하고자 하는 문제",
            "문제 해결 접근",
            "세부 내용",
        ]
        failures.extend([f"missing visual artifact element: {name}" for name in required if name.lower() not in lowered])
        forbidden = [
            "선행기술",
            "하네스",
            "루프",
            "레드팀",
            "LLM",
            "AI가 작성",
            "청구항",
            "특허성 조사",
            "DIRECT_OK",
            "FINAL_VERDICT",
        ]
        failures.extend([f"visual artifact contains forbidden term: {term}" for term in forbidden if term in text])
        if len(text) < 12000:
            failures.append("visual artifact is too short for a self-contained official overview")
    else:
        failures.append(f"unknown stage: {stage}")

    return not failures, failures


def section_text(text: str, heading: str) -> str:
    normalized = heading.replace("## ", "")
    pattern = re.compile(rf"^##\s+{re.escape(normalized)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    next_match = re.search(r"^##\s+", text[match.end() :], flags=re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(text)
    return text[match.end() : end]


def bullet_count(text: str) -> int:
    bullet_rows = len(re.findall(r"(^|\n)\s*(?:[-*]|\d+\.)\s+", text, flags=re.MULTILINE))
    heading_rows = len(re.findall(r"(?m)^#{3,}\s+(?:후보|Candidate)\s*\d+\b", text))
    table_rows = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        if cells[0] in {"번호", "항목", "문헌", "요소", "구분"}:
            continue
        table_rows += 1
    return bullet_rows + heading_rows + table_rows


def verdict(path: Path) -> str | None:
    text = read_text(path)
    matches = re.findall(r"FINAL_VERDICT:\s*(DIRECT_OK|REJECT)", text)
    return matches[-1] if matches else None


def is_capacity_error(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    combined = f"{result.stdout}\n{result.stderr}"
    return "Selected model is at capacity" in combined or "model is at capacity" in combined


def artifact_context(item: dict[str, Any], stage: str) -> str:
    if stage == "idea":
        keys: list[tuple[str, str]] = []
    elif stage == "research":
        keys = [
            ("idea_path", "아이디어 후보"),
            ("research_path", "이전 선행기술 Kill-or-Narrow 보고서"),
        ]
    elif stage == "draft":
        keys = [("idea_path", "아이디어 후보"), ("research_path", "선행기술 Kill-or-Narrow 보고서")]
    elif stage in {"examine", "redteam"}:
        keys = [("draft_path", "평가 대상 초안")]
    elif stage == "revise":
        keys = [
            ("draft_path", "거절 대상 초안"),
            ("research_path", "선행기술 Kill-or-Narrow 보고서"),
            ("examiner_path", "심사 보고서"),
            ("redteam_path", "문맥 차단 레드팀 보고서"),
        ]
    elif stage == "finalize":
        keys = [
            ("draft_path", "최종화 대상 초안"),
            ("research_path", "선행기술 Kill-or-Narrow 보고서"),
            ("examiner_path", "심사 보고서"),
            ("redteam_path", "문맥 차단 레드팀 보고서"),
        ]
    elif stage == "verify":
        keys = [("final_path", "최종본 후보")]
    elif stage == "external_spotcheck":
        keys = [
            ("final_path", "최종본 후보"),
            ("verification_path", "독립 검증 보고서"),
        ]
    elif stage == "visualize":
        keys = [("final_path", "최종 특허 명세서")]
    else:
        keys = []
    chunks: list[str] = []
    for key, label in keys:
        raw = item.get(key)
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / raw
        text = read_text(path)
        if text:
            chunks.append(f"## {label}: {path}\n\n{text[:50000]}")
    return "\n\n".join(chunks)


def compact_field(value: Any, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).replace("|", "/").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def latest_note_summary(item: dict[str, Any]) -> str:
    notes = item.get("notes", [])
    if not isinstance(notes, list):
        return ""
    for note in reversed(notes):
        if isinstance(note, dict):
            parts = []
            for key in ["stage", "decision", "reason", "changes", "grades"]:
                if note.get(key):
                    parts.append(f"{key}={note[key]}")
            if parts:
                return compact_field("; ".join(parts), 220)
        elif isinstance(note, str) and note.strip():
            return compact_field(note, 220)
    return ""


def duplicate_avoidance_context(item: dict[str, Any], stage: str) -> str:
    if stage not in {"idea", "research"}:
        return ""
    current_id = str(item.get("id", ""))
    rows: list[str] = []
    for other in load_backlog():
        other_id = str(other.get("id", ""))
        if other_id == current_id:
            continue
        status = str(other.get("status", ""))
        if status == "seed":
            lesson = "active seed; avoid same claim skeleton"
        elif status == "finalized":
            lesson = "successful reference; do not duplicate final claim skeleton"
        elif status == "finalized_out_of_scope":
            lesson = "technically finalized but outside battery software scope; do not count or repeat"
        elif status == "rejected":
            lesson = latest_note_summary(other) or "rejected; avoid same closest-art and control-gate skeleton"
        elif status == "blocked":
            lesson = latest_note_summary(other) or "blocked; do not repeat validation blocker"
        else:
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    compact_field(status, 24),
                    compact_field(other_id, 48),
                    compact_field(other.get("domain", ""), 36),
                    compact_field(other.get("title", ""), 90),
                    compact_field(other.get("hypothesis", ""), 180),
                    compact_field(lesson, 220),
                ]
            )
            + " |"
        )
    if not rows:
        return ""
    header = [
        "# Duplicate Avoidance Context",
        "",
        "이 표는 도메인 분산을 강제하기 위한 것이 아니다. 기존 성공/실패/활성 seed와 같은 closest prior art 조합, active challenge, response signature/residual, control gate, fail-closed fallback 골격을 반복하지 않기 위한 참고 자료다.",
        "",
        "| status | id | domain | title | hypothesis | duplicate-risk lesson |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    return "\n".join(header + rows)


def seed_preflight_context(stage: str) -> str:
    if stage not in {"idea", "research"}:
        return ""
    text = read_text(SEED_PREFLIGHT_PATH).strip()
    if not text:
        return ""
    return "# Seed Prior-Art Preflight Context\n\n" + text


def seed_ideation_context(stage: str) -> str:
    if stage != "idea":
        return ""
    text = read_text(SEED_IDEATION_PATH).strip()
    if not text:
        return ""
    return "# Seed Ideation Strategy Context\n\n" + text


def field_prompt_block(config: dict[str, Any]) -> str:
    field = field_profile(config)
    lines = [
        "# Runtime Patent Research Field",
        "",
        f"- Target field: {field['name']}",
        f"- Field description: {field['description']}",
    ]
    domains = listify(field.get("domains"))
    if domains:
        lines.append("- Allowed/narrow domains: " + ", ".join(domains))
    scope_terms = listify(field.get("scope_terms"))
    if scope_terms:
        lines.append("- Scope guard terms: " + ", ".join(scope_terms[:30]))
    lines.extend(
        [
            f"- Required binding label: `{field['binding_label']}:`",
            f"- Required micro-boundary heading: `## {field['micro_boundary_label']}`",
            f"- Required micro-boundary table column: `{field['micro_boundary_column']}`",
            "- A candidate is in scope only when claim-level elements are directly tied to this target field, not merely applicable to it.",
        ]
    )
    if not bool(field.get("battery_default", False)):
        lines.extend(
            [
                "- Static prompt compatibility: any battery/ESS/BMS wording in the bundled prompts is the built-in profile, not a hard requirement for this run.",
                "- Translate battery-specific constraints, boundary names, and rejection language to the target field above while keeping the same strict patentability posture.",
                "- For machine-readable boundary tokens, prefer `TARGET_FIELD_BOUNDARY:`; legacy `BATTERY_SW_BOUNDARY:` is accepted only for compatibility.",
            ]
        )
    instructions = listify(field.get("instructions"))
    if instructions:
        lines.append("- Extra field instructions: " + " / ".join(instructions))
    return "\n".join(lines)


def context_isolation_block(stage: str) -> str:
    if stage not in {"examine", "redteam", "verify", "external_spotcheck"}:
        return ""
    verification_note = ""
    if stage == "external_spotcheck":
        verification_note = (
            "\n- The verification report is an object to audit, not proof of patentability. "
            "Do not inherit its DIRECT_OK, grades, or confidence."
        )
    return (
        "# Context Isolation Contract\n\n"
        "- Use only the stage artifact(s) under `# Existing Artifacts` and independently verifiable references as substantive evidence.\n"
        "- Treat backlog status, notes, prior pass/fail decisions, prior DIRECT_OK tokens, guardrail history, and harness metrics as procedural metadata only.\n"
        "- Do not reward the candidate because it previously advanced through the loop; re-apply the same objective examiner standard from scratch.\n"
        "- If the document itself does not support an A- or stronger answer to novelty, inventive step, clarity/support, and claim-scope defense, reject it."
        f"{verification_note}"
    )


def output_path_for(item: dict[str, Any], stage: str) -> Path:
    run_id = f"{slug_time()}_{item['id']}_{stage}"
    if stage == "finalize":
        return ROOT / "final" / f"{item['id']}_final_{slug_time()}.md"
    if stage == "verify":
        return ROOT / "reports" / f"{item['id']}_verification_{slug_time()}.md"
    if stage == "external_spotcheck":
        return ROOT / "reports" / f"{item['id']}_external_spotcheck_{slug_time()}.md"
    if stage == "visualize":
        return ROOT / "visuals" / f"{item['id']}_overview_{slug_time()}.html"
    filename = {
        "idea": "01_idea.md",
        "research": "015_prior_art_gate.md",
        "draft": "02_draft.md",
        "examine": "03_patentability_report.md",
        "redteam": "035_context_free_red_team.md",
        "revise": "04_revised_draft.md",
    }[stage]
    return ROOT / "work" / run_id / filename


def build_prompt(item: dict[str, Any], stage: str, output_path: Path, config: dict[str, Any], repair_notes: list[str] | None = None) -> str:
    shared = read_prompt("00_shared_rules.md")
    role = read_prompt(PROMPTS[stage])
    guardrails = read_text(GUARDRAILS_PATH)
    evaluation_lessons = read_text(ROOT / "state" / "evaluation_lessons.md")
    context = artifact_context(item, stage)
    duplicate_context = duplicate_avoidance_context(item, stage)
    ideation_context = seed_ideation_context(stage)
    preflight_context = seed_preflight_context(stage)
    field_block = field_prompt_block(config)
    isolation_block = context_isolation_block(stage)
    archive = config.get("paths", {}).get("archive", "")
    repair_block = ""
    if repair_notes:
        repair_block = "\n\n## 이전 검증 실패\n\n" + "\n".join(f"- {note}" for note in repair_notes)

    if stage == "visualize":
        return "\n\n".join(
            [
                'Start the "Patent Generation Loop" visual explanation stage.',
                f"Workspace root: {ROOT}\nStage: {stage}\nOutput path: {output_path}",
                "Write exactly one complete, static HTML file to the output path above.\n"
                "Use only the final specification as source material. Do not include internal process notes, evaluation notes, prior-art analysis, or metadata.\n"
                "The HTML must be understandable as a standalone official company technical overview for readers with no background context.",
                "# Backlog Item\n\n```json\n" + json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + "\n```",
                "# Role Instructions\n\n" + role,
                field_block,
                "# Final Specification\n\n" + (context if context else "No final specification is available.") + repair_block,
                f"# Exit Condition\n\nThe artifact exists at `{output_path}` and satisfies the required output format for stage `{stage}`.",
            ]
        ).strip() + "\n"

    return "\n\n".join(
        [
            'Start the "Patent Generation Loop" stage.',
            f"Workspace root: {ROOT}\nStage: {stage}\nOutput path: {output_path}\nReference loop archive: {archive}",
            "You must write the complete stage artifact to the exact output path above.\n"
            "Work only inside the workspace unless you are reading public references or the loop archive.\n"
            "After writing the artifact, give a short status summary.",
            shared,
            "# Current Guardrails\n\n" + guardrails,
            "# External Evaluation Lessons\n\n" + (evaluation_lessons if evaluation_lessons else "No external evaluation lessons recorded."),
            duplicate_context,
            ideation_context,
            preflight_context,
            "# Backlog Item\n\n```json\n" + json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True) + "\n```",
            "# Role Instructions\n\n" + role,
            field_block,
            isolation_block,
            "# Existing Artifacts\n\n" + (context if context else "No previous artifacts for this item.") + repair_block,
            f"# Exit Condition\n\nThe artifact exists at `{output_path}` and satisfies the required output format for stage `{stage}`.",
        ]
    ).strip() + "\n"


def codex_child_env(codex_cfg: dict[str, Any]) -> dict[str, str]:
    allowed = listify(codex_cfg.get("env_allowlist")) or DEFAULT_CODEX_ENV_ALLOWLIST
    return {name: os.environ[name] for name in allowed if name in os.environ}


def run_codex(prompt: str, output_path: Path, config: dict[str, Any], stage: str, item_id: str) -> subprocess.CompletedProcess[str]:
    codex_path = shutil.which("codex")
    if not codex_path:
        raise RuntimeError("codex CLI not found on PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    last_message = ROOT / "logs" / f"codex-last-{item_id}-{stage}-{slug_time()}.md"
    stdout_log = ROOT / "logs" / f"codex-{item_id}-{stage}-{slug_time()}.out.log"
    stderr_log = ROOT / "logs" / f"codex-{item_id}-{stage}-{slug_time()}.err.log"

    codex_cfg = config.get("codex", {})
    command = [
        codex_path,
        "exec",
        "-c",
        f"approval_policy={json.dumps(str(codex_cfg.get('approval_policy', 'never')))}",
        "--cd",
        str(ROOT),
        "--sandbox",
        str(codex_cfg.get("sandbox", "workspace-write")),
        "--skip-git-repo-check",
        "-o",
        str(last_message),
        "-",
    ]
    if bool(codex_cfg.get("ignore_user_config", True)):
        command.insert(2, "--ignore-user-config")
    if bool(codex_cfg.get("ephemeral", True)):
        command.insert(2, "--ephemeral")
    if bool(codex_cfg.get("bypass_hook_trust", False)):
        command.insert(2, "--dangerously-bypass-hook-trust")
    model = str(codex_cfg.get("model", "")).strip()
    if model:
        command[2:2] = ["--model", model]

    capacity_retry_seconds = max(30, int(codex_cfg.get("capacity_retry_seconds", 300)))
    capacity_retry_max_attempts = int(codex_cfg.get("capacity_retry_max_attempts", 0))
    attempt = 0
    while True:
        attempt += 1
        started = time.time()
        result = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=int(codex_cfg.get("timeout_seconds", 3600)),
            cwd=str(ROOT),
            env=codex_child_env(codex_cfg),
        )
        duration = round(time.time() - started, 3)
        write_text(stdout_log, result.stdout)
        write_text(stderr_log, result.stderr)

        capacity_retry = is_capacity_error(result)
        append_jsonl(
            METRICS_PATH,
            {
                "at": now(),
                "event": "codex_exec",
                "item_id": item_id,
                "stage": stage,
                "returncode": result.returncode,
                "duration_seconds": duration,
                "attempt": attempt,
                "capacity_retry": capacity_retry,
                "stdout_log": str(stdout_log.relative_to(ROOT)),
                "stderr_log": str(stderr_log.relative_to(ROOT)),
                "last_message": str(last_message.relative_to(ROOT)),
                "output_path": str(output_path.relative_to(ROOT)),
            },
        )
        if not capacity_retry:
            break
        if capacity_retry_max_attempts and attempt >= capacity_retry_max_attempts:
            break
        print(
            json.dumps(
                {
                    "event": "capacity_retry",
                    "item_id": item_id,
                    "stage": stage,
                    "model": model or "default",
                    "attempt": attempt,
                    "sleep_seconds": capacity_retry_seconds,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        time.sleep(capacity_retry_seconds)

    if not output_path.exists() and last_message.exists():
        last = read_text(last_message)
        if last.strip():
            write_text(output_path, last)
    return result


def update_item_after_success(
    item: dict[str, Any],
    stage: str,
    output_path: Path,
    config: dict[str, Any] | None = None,
) -> None:
    rel = str(output_path.relative_to(ROOT))
    if stage == "idea":
        item["status"] = "idea_ready"
        item["idea_path"] = rel
    elif stage == "research":
        item["research_path"] = rel
        gate_decision = decision(output_path)
        if gate_decision == "PROCEED_NARROW":
            item["status"] = "research_ready"
        elif gate_decision == "NEED_MORE_SEARCH":
            item["status"] = "rejected"
            item.setdefault("notes", []).append(
                {
                    "at": now(),
                    "stage": stage,
                    "decision": gate_decision,
                    "reason": "Research gate did not find an A- narrow survival path; stop before drafting and move to a different seed.",
                }
            )
        else:
            item["status"] = "rejected"
            item.setdefault("notes", []).append({"at": now(), "stage": stage, "decision": gate_decision or "missing"})
    elif stage == "draft":
        item["status"] = "draft_ready"
        item["draft_path"] = rel
    elif stage == "examine":
        item["examiner_path"] = rel
        if verdict(output_path) == "DIRECT_OK":
            item["status"] = "examiner_passed"
        else:
            item["status"] = "needs_revision"
            item["iteration"] = int(item.get("iteration", 0)) + 1
    elif stage == "redteam":
        item["redteam_path"] = rel
        if verdict(output_path) == "DIRECT_OK":
            item["status"] = "redteam_passed"
        else:
            next_iteration = int(item.get("iteration", 0)) + 1
            item["iteration"] = next_iteration
            terminal_after = int((config or {}).get("loop", {}).get("redteam_reject_terminal_after_iteration", 0))
            if terminal_after and next_iteration >= terminal_after:
                item["status"] = "rejected"
                item.setdefault("notes", []).append(
                    {
                        "at": now(),
                        "stage": stage,
                        "decision": "FINAL_VERDICT_REJECT_REPEATED",
                        "reason": (
                            "Context-free redteam rejected after repeated examiner/revision cycles; "
                            f"terminal_after_iteration={terminal_after} prevents spending further loop budget on a stable 103/claim-defense failure."
                        ),
                    }
                )
            else:
                item["status"] = "needs_revision"
                item["iteration"] = next_iteration
    elif stage == "revise":
        item["status"] = "draft_ready"
        item["revised_path"] = rel
        item["draft_path"] = rel
    elif stage == "finalize":
        item["status"] = "final_ready"
        item["final_path"] = rel
    elif stage == "verify":
        item["verification_path"] = rel
        item["status"] = "external_spotcheck_ready" if verdict(output_path) == "DIRECT_OK" else "needs_revision"
        if item["status"] == "needs_revision":
            item["iteration"] = int(item.get("iteration", 0)) + 1
    elif stage == "external_spotcheck":
        item["external_spotcheck_path"] = rel
        item["status"] = "visualization_ready" if verdict(output_path) == "DIRECT_OK" else "needs_revision"
        if item["status"] == "needs_revision":
            item["iteration"] = int(item.get("iteration", 0)) + 1
    elif stage == "visualize":
        item["status"] = "finalized"
        item["visual_path"] = rel
    item["updated_at"] = now()


def maybe_reject_for_revision_limit(item: dict[str, Any], config: dict[str, Any]) -> bool:
    stage = stage_for(item)
    if stage not in {"draft", "examine", "redteam", "revise"}:
        return False
    max_cycles = int(config["loop"].get("max_revision_cycles", 5))
    if int(item.get("iteration", 0)) >= max_cycles:
        item["status"] = "rejected"
        item["updated_at"] = now()
        item.setdefault("notes", []).append(
            {
                "at": now(),
                "stage": "revision_limit",
                "decision": "MAX_REVISION_CYCLES_REACHED",
                "reason": (
                    f"Stopped at max_revision_cycles={max_cycles}; repeated examiner/redteam failures usually indicate "
                    "a stable 103/claim-defense weakness rather than a draft-only defect."
                ),
            }
        )
        return True
    return False


def record_guardrail(stage: str, item: dict[str, Any], failures: list[str]) -> None:
    if not failures:
        return
    summary = "; ".join(failures[:3])
    append_text(
        GUARDRAILS_PATH,
        f"\n- {now()} `{item.get('id')}` stage `{stage}` failed validation: {summary}\n",
    )


def run_one(item: dict[str, Any], config: dict[str, Any], dry_run: bool = False, no_codex: bool = False) -> dict[str, Any]:
    stage = stage_for(item)
    if not stage:
        return {"ran": False, "reason": f"no runnable stage for status={item.get('status')}"}
    if maybe_reject_for_revision_limit(item, config):
        return {"ran": False, "reason": "revision limit exceeded"}

    output_path = output_path_for(item, stage)
    prompt_path = output_path.parent / "task_prompt.md"
    prompt = build_prompt(item, stage, output_path, config)
    write_text(prompt_path, prompt)

    if dry_run or no_codex or not bool(config.get("codex", {}).get("enabled", True)):
        append_jsonl(
            METRICS_PATH,
            {
                "at": now(),
                "event": "dry_run" if dry_run else "prompt_only",
                "item_id": item["id"],
                "stage": stage,
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "output_path": str(output_path.relative_to(ROOT)),
            },
        )
        return {"ran": True, "stage": stage, "item_id": item["id"], "prompt_path": prompt_path, "output_path": output_path, "dry_run": True}

    repair_attempts = int(config.get("codex", {}).get("repair_attempts", 1))
    failures: list[str] = []
    for attempt in range(repair_attempts + 1):
        if attempt:
            prompt = build_prompt(item, stage, output_path, config, repair_notes=failures)
            write_text(prompt_path, prompt)
        result = run_codex(prompt, output_path, config, stage, item["id"])
        if result.returncode != 0:
            failures = [f"codex returned {result.returncode}"]
        else:
            ok, failures = validate_stage(stage, output_path, config, item=item)
            if ok:
                update_item_after_success(item, stage, output_path, config=config)
                return {"ran": True, "stage": stage, "item_id": item["id"], "output_path": output_path, "status": item["status"]}

    record_guardrail(stage, item, failures)
    item["status"] = "blocked"
    item["updated_at"] = now()
    item.setdefault("notes", []).append({"at": now(), "stage": stage, "validation_failures": failures})
    return {"ran": True, "stage": stage, "item_id": item["id"], "output_path": output_path, "status": "blocked", "failures": failures}


def slugify_id(text: str) -> str:
    parts = re.findall(r"[a-z0-9]+", text.casefold())
    slug = "-".join(parts)[:56].strip("-")
    return slug or "patent-seed"


def next_unique_seed_id(base: str, items: list[dict[str, Any]]) -> str:
    existing = {str(item.get("id", "")) for item in items}
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-\d{3}", base) and base not in existing:
        return base
    base = re.sub(r"-\d{3}$", "", base)
    for index in range(1, 1000):
        candidate = f"{base}-{index:03}"
        if candidate not in existing:
            return candidate
    raise RuntimeError(f"Could not allocate unique seed id for base={base}")


def cmd_seed(args: argparse.Namespace) -> int:
    ensure_layout()
    config = apply_field_args(load_config(), args)
    field = field_profile(config)
    items = load_backlog()
    base_id = str(args.id or slugify_id(args.title or field["name"]))
    item_id = next_unique_seed_id(base_id, items)
    domain = str(args.domain or (field["domains"][0] if field["domains"] else field["name"]))
    item = {
        "id": item_id,
        "title": str(args.title).strip(),
        "domain": domain,
        "hypothesis": str(args.hypothesis).strip(),
        "priority": int(args.priority),
        "status": "seed",
        "created_at": now(),
        "updated_at": now(),
        "notes": [
            {
                "at": now(),
                "stage": "seed",
                "field": field["name"],
                "source": "patent_loop.py seed command",
            }
        ],
    }
    failures = validate_seed_item(item, config)
    if failures and not args.allow_invalid:
        print(
            json.dumps(
                {
                    "created": False,
                    "id": item_id,
                    "field": field["name"],
                    "validation_failures": failures,
                    "hint": "Pass --allow-invalid to enqueue anyway, or add --field-term/--domain terms that match the seed.",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    if failures:
        item["notes"].append({"at": now(), "stage": "seed_validation", "validation_failures": failures})
    items.append(item)
    save_backlog(items)
    print(
        json.dumps(
            {
                "created": True,
                "id": item_id,
                "field": field["name"],
                "domain": domain,
                "status": "seed",
                "validation_warnings": failures,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    ensure_layout()
    config = apply_field_args(load_config(), args)
    field = field_profile(config)
    if args.mode == "heartbeat" and not args.force and not args.dry_run:
        skip_reason = heartbeat_skip_reason(config)
        if skip_reason:
            print(json.dumps({"ran": False, "mode": args.mode, "reason": skip_reason}, ensure_ascii=False, sort_keys=True))
            return 0
    max_items = args.max_items or int(config["loop"].get("max_items_per_run", 1))
    with LoopLock(LOCK_PATH):
        items = load_backlog()
        if not items:
            print("No backlog items.")
            return 0
        results = []
        for _ in range(max_items):
            item = next_item(items, stage_only=args.stage_only, field=field)
            if item is None:
                break
            scope_result = reject_out_of_scope_seed(item, config)
            if scope_result:
                results.append(scope_result)
                save_backlog(items)
                continue
            if not args.ignore_usage_guard:
                guard_result = usage_guard_for_item(item, config)
                if guard_result:
                    results.append(guard_result)
                    break
            result = run_one(item, config, dry_run=args.dry_run, no_codex=args.no_codex)
            results.append(result)
            if result.get("dry_run"):
                break
            save_backlog(items)
        if not results:
            status = load_json(STATUS_PATH, {})
            status["last_noop_at"] = now()
            status["last_error"] = None
            save_json(STATUS_PATH, status)
            print(json.dumps({"ran": False, "reason": "no runnable backlog items"}, ensure_ascii=False, sort_keys=True))
            return 0
        status = load_json(STATUS_PATH, {})
        if args.dry_run:
            status["last_dry_run_at"] = now()
        else:
            status["last_run_at"] = now()
            status["runs"] = int(status.get("runs", 0)) + 1
        status["last_error"] = None
        if results and not args.dry_run:
            completed = [result for result in results if result.get("ran") and result.get("stage")]
            if completed:
                status["last_completed_stage"] = completed[-1].get("stage")
        save_json(STATUS_PATH, status)
        if not args.dry_run:
            save_json(
                HEARTBEAT_STATE_PATH,
                {
                    "lastChecks": {
                        "patent_loop": int(time.time()),
                    },
                    "last_run_at": now(),
                },
            )
        for result in results:
            printable = dict(result)
            for key in ["prompt_path", "output_path"]:
                if isinstance(printable.get(key), Path):
                    printable[key] = str(printable[key].relative_to(ROOT))
            print(json.dumps(printable, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ensure_layout()
    config = apply_field_args(load_config(), args)
    field = field_profile(config)
    items = load_backlog()
    counts: dict[str, int] = {}
    for item in items:
        counts[item.get("status", "unknown")] = counts.get(item.get("status", "unknown"), 0) + 1
    nxt = next_item(items, field=field)
    status = load_json(STATUS_PATH, {})
    print("Patent loop status")
    print(f"- root: {ROOT}")
    print(f"- field: {field['name']}")
    print(f"- backlog: {len(items)}")
    print(f"- counts: {json.dumps(counts, ensure_ascii=False, sort_keys=True)}")
    print(f"- last_run_at: {status.get('last_run_at')}")
    usage = codex_weekly_usage(config)
    if usage:
        print(f"- codex_weekly_usage: {float(usage['used_percent']):.1f}% ({usage.get('source')})")
    else:
        print("- codex_weekly_usage: unknown")
    if nxt:
        print(f"- next: {nxt['id']} status={nxt.get('status')} stage={stage_for(nxt)} priority={nxt.get('priority')}")
    else:
        print("- next: none")
    if LOCK_PATH.exists():
        print(f"- lock: present ({LOCK_PATH})")
    return 0


def heartbeat_skip_reason(config: dict[str, Any]) -> str | None:
    loop_cfg = config.get("loop", {})
    state = load_json(HEARTBEAT_STATE_PATH, {})
    last = state.get("lastChecks", {}).get("patent_loop")
    min_interval = int(loop_cfg.get("heartbeat_min_interval_minutes", 45)) * 60
    if isinstance(last, int) and time.time() - last < min_interval:
        remaining = int((min_interval - (time.time() - last)) / 60) + 1
        return f"last patent loop run was too recent; wait about {remaining} minutes"

    hour = dt.datetime.now().astimezone().hour
    start = int(loop_cfg.get("quiet_hour_start", 23))
    end = int(loop_cfg.get("quiet_hour_end", 8))
    if start > end:
        quiet = hour >= start or hour < end
    else:
        quiet = start <= hour < end
    if quiet:
        return f"quiet hours active ({start}:00-{end}:00)"
    return None


def cmd_validate(args: argparse.Namespace) -> int:
    config = apply_field_args(load_config(), args)
    items = load_backlog()
    failures_total = 0
    for item in items:
        seed_failures = validate_seed_item(item, config)
        if seed_failures:
            failures_total += len(seed_failures)
            print(f"FAIL {item.get('id', '<missing-id>')} seed backlog: {'; '.join(seed_failures)}")
        checks = [
            ("idea", item.get("idea_path")),
            ("research", item.get("research_path")),
            ("draft", item.get("draft_path")),
            ("examine", item.get("examiner_path")),
            ("redteam", item.get("redteam_path")),
            ("finalize", item.get("final_path")),
            ("verify", item.get("verification_path")),
            ("external_spotcheck", item.get("external_spotcheck_path")),
            ("visualize", item.get("visual_path")),
        ]
        for stage, raw in checks:
            if not raw:
                continue
            path = ROOT / raw
            ok, failures = validate_stage(stage, path, config, item=item)
            if ok:
                print(f"OK {item['id']} {stage} {raw}")
            else:
                failures_total += len(failures)
                print(f"FAIL {item['id']} {stage} {raw}: {'; '.join(failures)}")
    return 1 if failures_total else 0


def cmd_doctor(_: argparse.Namespace) -> int:
    problems: list[str] = []
    if sys.version_info < (3, 11):
        problems.append("Python 3.11+ required")
    for name in ["00_shared_rules.md", *PROMPTS.values()]:
        try:
            read_prompt(name)
        except FileNotFoundError:
            problems.append(f"missing bundled prompt: {name}")
    if shutil.which("codex") is None:
        problems.append("codex CLI not found")
    try:
        load_config()
    except Exception as exc:  # noqa: BLE001
        problems.append(f"config parse failed: {exc}")
    if problems:
        print("Doctor found problems:")
        for problem in problems:
            print(f"- {problem}")
        return 1
    print("Doctor OK")
    print(f"- codex: {shutil.which('codex')}")
    print(f"- root: {ROOT}")
    print(f"- config: {CONFIG_PATH if CONFIG_PATH.exists() else 'bundled default_config.toml'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Autonomous patent generation loop harness")
    sub = parser.add_subparsers(dest="command", required=True)

    seed = sub.add_parser("seed", help="Append a seed backlog item")
    add_field_arguments(seed)
    seed.add_argument("--id", default="", help="optional lowercase-kebab id; -NNN suffix is added when missing")
    seed.add_argument("--title", required=True, help="seed title")
    seed.add_argument("--domain", default="", help="seed domain; defaults to the active field's first domain")
    seed.add_argument("--hypothesis", required=True, help="narrow causal-chain hypothesis for the seed")
    seed.add_argument("--priority", type=int, default=100)
    seed.add_argument("--allow-invalid", action="store_true", help="enqueue even if strict seed validation reports warnings")
    seed.set_defaults(func=cmd_seed)

    run = sub.add_parser("run", help="Run the next loop stage")
    add_field_arguments(run)
    run.add_argument("--mode", default="manual", help="caller mode label: manual, heartbeat, launchd")
    run.add_argument("--max-items", type=int, default=1)
    run.add_argument("--budget-minutes", type=int, default=0, help="reserved for scheduler policy")
    run.add_argument("--stage-only", choices=sorted(PROMPTS), default=None, help="run only items whose next stage matches")
    run.add_argument("--ignore-usage-guard", action="store_true", help="explicitly bypass the new-idea usage guard for this run")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--no-codex", action="store_true", help="write task prompt but do not invoke codex")
    run.add_argument("--force", action="store_true", help="ignore heartbeat cadence checks")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="Show loop status")
    add_field_arguments(status)
    status.set_defaults(func=cmd_status)

    validate = sub.add_parser("validate", help="Validate known artifacts")
    add_field_arguments(validate)
    validate.set_defaults(func=cmd_validate)

    doctor = sub.add_parser("doctor", help="Check local prerequisites")
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001
        status = load_json(STATUS_PATH, {})
        status["last_error"] = {"at": now(), "error": str(exc), "traceback": traceback.format_exc(limit=8)}
        save_json(STATUS_PATH, status)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
