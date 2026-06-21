# Contributing

Thanks for your interest. This repository is the **public upstream** for reusable
harness code only.

## Ground rules

- Read `USAGE_POLICY.md` and `docs/PUBLIC_PRIVATE_WORKFLOW.md` first.
- **Never** commit private workbench data: backlog state, drafts, reports, visuals,
  logs, invention titles, prior-art strategy, or personal paths. Run `git ls-files`
  before every push and confirm no workbench runtime paths are tracked.
- Only public-allowed paths belong here: `src/`, bundled prompts, example config,
  tests, and docs.

## Development

```bash
python3 -m pip install -e .
python3 -m unittest discover -s tests
python3 -m py_compile src/patent_loop_harness/cli.py
ruff check .        # optional, if installed
```

- Requires Python 3.11+.
- The package is intentionally dependency-free (standard library only). Do not add
  runtime third-party dependencies without discussion.
- Add or update tests for any behavior change. Keep tests hermetic (no network, no
  real LLM runner) — use the `prompt_only` runner or fakes.

## Pull requests

1. Reproduce any issue with dummy data (never private patent material).
2. Keep patches minimal and scoped to public-allowed paths.
3. Ensure `unittest` passes and `py_compile` is clean.
4. Describe the user-facing behavior change and any new config keys.
