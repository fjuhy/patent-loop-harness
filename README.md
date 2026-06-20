# Patent Loop Harness

Reusable patent idea and drafting loop harness with field-parameterized prompts.

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

By default, the harness lets the installed `codex` CLI choose its default model.
Set `[codex].model` in a private workbench config when you need a pinned model.

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

## Tests

```bash
python3 -m unittest discover -s tests
python3 -m py_compile src/patent_loop_harness/cli.py
```
