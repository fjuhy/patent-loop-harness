# Patent Loop Harness

Reusable patent idea and drafting loop harness with field-parameterized prompts
and pluggable LLM runners.

This public repository is intended to contain only reusable harness code,
generic prompts, example configuration, tests, and documentation. Private
workbench data such as invention notes, backlog state, generated drafts,
verification reports, visuals, logs, and patent history should live in a
separate private repository.

## Install

```bash
python3 -m pip install -e .
patent-loop status
```

For a private workbench repository, use a dependency on this package:

```bash
python3 -m pip install -e ../patent-loop-harness
```

Then run the CLI from the private workbench root:

```bash
cd ../patent-workbench-private
patent-loop run --dry-run --max-items 1
```

The CLI uses the current working directory as the workbench root. You can also
set `PATENT_LOOP_ROOT=/path/to/workbench`.

By default, the harness uses the `codex` runner for backward compatibility and
lets the installed CLI choose its default model. Set `[runner].model` in a
private workbench config when you need a pinned model.

## Agent Skill

This repository also ships an Agent Skills-compatible wrapper at
`skills/patent-loop/`. Install or copy that folder into a skills directory for
Codex, Claude Code, OpenCode, Hermes, OpenClaw, or another compatible agent so
the agent can discover the safe `patent-loop` CLI workflow.

The skill does not replace the CLI. It teaches agents to inspect the active
workbench, respect the public/private repository boundary, prefer status,
doctor, validate, and dry-run commands before live runs, and use
`PATENT_LOOP_ROOT` when the workbench is outside the current directory.

## LLM Runners

The harness has a pluggable runner layer:

- `codex`: runs `codex exec`
- `claude`: runs Claude Code in print mode with `claude -p`
- `shell`: sends the prompt to any command on stdin
- `prompt_only`: writes prompts without invoking an LLM

Select a runner in config:

```toml
[runner]
type = "claude"
model = "sonnet"

[runner.claude]
permission_mode = "acceptEdits"
output_format = "text"
```

Or override it for one invocation:

```bash
patent-loop run --runner claude --max-items 1
patent-loop run --runner prompt_only --max-items 1
```

For fully autonomous Claude Code operation, configure Claude Code locally first
and choose the permission mode that matches your risk tolerance.
The usage guard can apply to multiple runners. Codex can read
`CODEX_WEEKLY_USED_PERCENT`, `state/codex_usage.json`, or Codex session logs.
Claude can read `CLAUDE_WEEKLY_USED_PERCENT` or `state/claude_usage.json`; set
`[runner.claude].max_budget_usd` to pass a per-run budget to `claude -p`.
State files may use a simple shape such as `{"weekly_used_percent": 42.0}`.
Use `patent-loop doctor --runner claude --runner-smoke` when you want a live
end-to-end runner check rather than only an auth/executable check.

## Public And Private Boundary

Public repository:

- `src/patent_loop_harness/`
- bundled generic prompts
- example configuration
- tests and docs

Private repository:

- `state/backlog.jsonl`
- `work/`
- `final/`
- `reports/`
- `visuals/`
- `logs/`
- private notes and invention history
- private config overrides

Do not merge a private workbench branch into this public repository. Move fixes
from private to public only as minimal, reviewed patches that contain no private
artifacts or patent-specific history.

## Field Parameters

The default profile is battery-industry software. Override the target field at
runtime:

```bash
patent-loop run \
  --field "semiconductor packaging control software" \
  --field-domain "advanced packaging inspection" \
  --field-term "package" \
  --field-term "interposer" \
  --max-items 1
```

## Examiner Calibration

The harness tries to approximate real patent examination rather than maximize
either pass rate or rejection rate. Evaluation prompts separate substantive
patentability from harness formatting:

- missing runtime labels or micro-boundary headings are format issues, not
  novelty/inventive-step defects by themselves;
- claim-level elements still must be directly tied to the configured target
  field;
- inventive step uses a realistic KSR-style predictable-combination screen;
- known security, attestation, hash/MAC, freshness, retained-log, HSM, latch,
  or remote-command checks applied to a known field control gate are not enough
  for `DIRECT_OK` unless the claim shows a non-predictable technical coupling.

## Tests

```bash
python3 -m unittest discover -s tests
python3 -m py_compile src/patent_loop_harness/cli.py
```
