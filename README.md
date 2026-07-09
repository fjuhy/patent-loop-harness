# Patent Loop Harness

Reusable patent idea and drafting loop harness with field-parameterized prompts
and pluggable LLM runners.

This public repository is intended to contain only reusable harness code,
generic prompts, example configuration, tests, and documentation. Private
workbench data such as invention notes, backlog state, generated drafts,
verification reports, visuals, logs, and patent history should live in a
separate private repository.

## What this is (and isn't)

This harness selects patent *ideas* and drafts patent specifications for a target
field. It is a **drafting and prior-art-stress-test aid with a human in the loop**,
not a filing tool.

- Outputs are **AI-generated drafts**. A human — and a qualified patent attorney
  (변리사) — must review, correct, and substantively rework them before any use.
  **Do not file the output as-is.**
- `DIRECT_OK`, the `finalized` status, and the "최종본 / final candidate" labels mean
  a draft **passed the harness's internal self-checks**. They are **not** a grant
  prediction and **not** a signal that the draft is ready to file.
- **Live web search is mandatory and enforced (fail-closed).** The prior-art /
  examiner / red-team / external-spot-check stages must perform real web search.
  The harness enables it by default and **verifies it actually happened**; if no
  `web_search` activity is detected for one of those stages, the stage fails closed
  (the item is blocked) instead of advancing on possibly-unsearched analysis.
  - **Codex** is invoked with `--search` (the native live `web_search` tool). On by
    default; it prints a `web search: <query>` line per call, which the harness uses
    as proof of search.
  - **Claude Code** is invoked with `--allowedTools WebSearch,WebFetch` and defaults
    to `output_format = "json"` so the harness can read the actual web-search count
    from the result envelope (`usage.server_tool_use.web_search_requests` and
    `modelUsage[...].webSearchRequests`). Plain `text` output cannot prove a tool
    call, so with `output_format = "text"` search-required stages fail closed.
    WebSearch availability is provider-gated (Anthropic API / Vertex Claude 4 /
    Foundry; not Bedrock).
  - **`prompt_only`** and **`shell`** are not subject to this enforcement.

  Set `[runner].require_web_search = false` only if you knowingly want to disable
  this safety gate, and per-runner `web_search = false` to drop the search flags.
  Run `patent-loop doctor --runner-smoke` to confirm live web search works
  end-to-end. The harness still does **not** verify that cited references actually
  resolve, so re-check prior art with a human and counsel before relying on it.
- **Inventorship.** An AI cannot be a named inventor (Thaler v. Vidal; the DABUS
  decisions at KIPO/EPO/UK and elsewhere). A natural person must make a significant
  intellectual contribution to the conception of each claim — editorial polishing of
  an AI-drafted claim is not, by itself, an inventive contribution. Confirm valid
  human inventorship before filing.

This software provides **no legal or patent advice** and is not a substitute for a
licensed patent attorney (변리사). Generated specifications and the technical-overview
HTML may describe an unfiled invention; do not disclose them publicly before making a
filing/priority decision with counsel, because pre-filing disclosure can destroy
novelty (notably in the EPO's absolute-novelty regime).

## Limitations and responsible use

- **Validation is structural, not substantive.** `validate_stage` checks section
  presence, counts, a regex-extracted grade, and the `FINAL_VERDICT` / `GO_DECISION`
  token. It is a format/lint layer; passing it is not a patentability judgment.
- **Evaluation stages share one model.** The writer, examiner, red-team, verifier,
  spot-check, HTML writer, implementation-readiness reviewer, and HTML reviser all
  use the same configured `[runner]` model. Despite the `context_free` / `independent` /
  `external` stage names, they are the same model re-applying the standard from a fresh
  prompt — not an independent second-provider opinion. For a genuine cross-check, point
  those stages at a different model/provider, or review with a human.
- **Output is Korean / KIPO-oriented.** The prompts and the validator's required
  section headings are Korean. `--field` retargets the *subject*, not the output
  language; non-Korean output will not pass validation as shipped.
- **No completeness guarantee.** Web search is enforced (above), but the harness does
  not verify that cited references resolve or that the search was exhaustive. Treat
  results as leads for a human/counsel prior-art search.

See `USAGE_POLICY.md` for intended use and explicit non-goals.

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
output_format = "json"   # default; required so web search can be verified (fail-closed otherwise)
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

## Final HTML Deliverable

A successful item does not stop at the Markdown specification. After independent
verification and the external prior-art spot check, the harness now produces one
standalone HTML technical document under `visuals/`, then runs an independent
implementation-readiness review of that HTML.

The item reaches `finalized` only after the HTML review returns `DIRECT_OK`.
A rejected HTML enters a bounded `visual_revise -> visual_review` loop. The
`max_visual_revision_cycles` value counts completed HTML rewrites; the default `3`
therefore allows three actual revision attempts before the next unresolved rejection
blocks the item. Review reports also fail closed when they contain only headings: each
substantive section, component-evidence rows, and verdict-consistent remediation must
be present.

New HTML artifacts are tagged with `visual_contract_version = 2` in backlog state.
`patent-loop validate` applies the strict v2 contract to them, while finalized artifacts
created before v2 continue to use the legacy overview validator. This compatibility path
does not weaken validation for newly generated files.

The HTML contract is intentionally strict:

- one individual-invention file, with inline CSS and at least three inline SVG diagrams;
- source-faithful use of the final specification plus the source draft — no unsupported
  mechanisms, formulas, thresholds, fields, control effects, or example values;
- Korean technical-document `한다체`, industry-standard Korean terminology, and no
  one-sentence-summary/reviewer-request/generation-process metadata sections;
- implementation-level explanation of inputs, sources, measurement/generation,
  calculations, thresholds, pass/fail behavior, result hooks, records, examples, and recovery;
- no JavaScript, external assets, unresolved placeholders, or mechanical-replacement corruption.

The reader-facing HTML remains an internal draft unless and until filing/public-disclosure
risk has been reviewed with counsel.

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
