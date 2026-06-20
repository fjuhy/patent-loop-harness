---
name: patent-loop
description: Operate the Patent Loop Harness from an agent session. Use when the user asks to inspect, configure, seed, dry-run, run, validate, troubleshoot, or explain a patent-loop workbench that uses the `patent-loop` CLI, `state/backlog.jsonl`, `config/patent_loop.toml`, and the `work/`, `final/`, `reports/`, or `visuals/` artifact folders.
---

# Patent Loop

## Overview

Use the installed `patent-loop` CLI as the stable execution surface. Treat the current directory or `PATENT_LOOP_ROOT` as the private workbench, and keep reusable harness changes separate from private invention data.

## Safety First

- Prefer `patent-loop status`, `patent-loop doctor`, `patent-loop validate`, and `patent-loop run --dry-run` before starting a live loop.
- Ask before running `patent-loop run` without `--dry-run` unless the user explicitly requested a live run.
- Do not copy private workbench artifacts, invention titles, drafts, reports, logs, or backlog contents into a public harness repo.
- Do not treat generated drafts or examiner reports as legal advice. Remind the user that real filing decisions require patent-counsel review when relevant.
- If the command would invoke another agent runner, note the configured runner first with `patent-loop status` or `patent-loop doctor`.

## Locate The Workbench

1. Check whether the current directory contains workbench markers: `config/patent_loop.toml`, `state/backlog.jsonl`, `state/`, or `work/`.
2. If the user is in the public harness repo, ask for the private workbench path or use `PATENT_LOOP_ROOT=/path/to/workbench`.
3. If the CLI is unavailable, install the harness from the public repo:

```bash
python3 -m pip install -e /path/to/patent-loop-harness
```

## Common Tasks

Inspect status:

```bash
patent-loop status
```

Check local prerequisites:

```bash
patent-loop doctor
```

Write the next stage prompt without invoking an LLM:

```bash
patent-loop run --dry-run --max-items 1
```

Run one live stage only after the user asks for it:

```bash
patent-loop run --max-items 1
```

Use a specific runner for one invocation:

```bash
patent-loop run --runner prompt_only --max-items 1
patent-loop run --runner claude --max-items 1
```

Validate known artifacts:

```bash
patent-loop validate
```

Add a seed with a narrow hypothesis:

```bash
patent-loop seed \
  --title "Short descriptive title" \
  --hypothesis "A narrow technical causal-chain hypothesis tied to the configured field."
```

Override the research field at runtime:

```bash
patent-loop run \
  --field "semiconductor packaging control software" \
  --field-domain "advanced packaging inspection" \
  --field-term "package" \
  --max-items 1
```

## Interpreting Results

- `status` shows the active root, field, runner, backlog counts, usage guard, and next runnable item.
- `run --dry-run` writes `task_prompt.md` and prints `prompt_path` plus `output_path`; inspect those files when debugging prompt construction.
- A live run updates `state/backlog.jsonl`, `state/status.json`, `logs/metrics.jsonl`, and a stage artifact under `work/`, `final/`, `reports/`, or `visuals/`.
- `blocked` means the harness could not validate the generated artifact after allowed repair attempts. Inspect the artifact, runner logs, and appended guardrail note.
- `rejected` can be an expected high-confidence outcome, especially after prior-art or red-team gates.

## Public/Private Boundary

Keep reusable code, generic prompts, example config, tests, and this skill in the public harness. Keep real backlog state, drafts, reports, visuals, logs, and invention history in the private workbench.
