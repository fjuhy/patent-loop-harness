# Security Policy

## Reporting

If you find a security issue in the harness code, report it privately to the
repository owner before public disclosure. Include a minimal reproduction that does
not contain private patent material. Do not file private invention disclosures,
draft claims, client data, logs, or API credentials in public issues.

## Operational risks you must understand before running live

This harness drives an LLM coding agent. A live `patent-loop run` (the default,
non-`--dry-run` path) is **autonomous and write-enabled**:

- **Autonomous file write / blast radius.** The default `codex` runner uses
  `approval_policy=never`, `sandbox=workspace-write`, and `--skip-git-repo-check`;
  the `claude` runner uses `--permission-mode acceptEdits` in headless `-p` mode.
  In both cases the agent can create or overwrite files anywhere under the workbench
  root with no human approval, repeatedly, across stages. Run the workbench in a
  dedicated directory (ideally a container or disposable VM). The root must not
  contain unrelated sensitive files. Prefer `--dry-run` or the `prompt_only` runner
  for a first look.

- **Prompt injection from on-disk content.** Prompts are assembled from the backlog
  item JSON, prior-stage artifacts (up to ~50k chars each), `state/guardrails.md`,
  `state/evaluation_lessons.md`, and duplicate-avoidance rows pulled from other
  backlog items. This content is not sanitized or sandboxed as data. Do **not** load
  a backlog, artifacts, or workbench state from an untrusted source into a
  write-enabled run — a poisoned artifact/note can steer the agent, and a compromised
  stage can self-propagate to later stages.

- **Private data via field arguments.** `--field`, `--field-domain`, and especially
  `--field-instruction` inject your text verbatim into every task prompt, which is
  written to `work/.../task_prompt.md` and may appear in `logs/` and your shell
  history. Treat anything you pass there as it will be stored on disk.

- **Cleartext logs.** Runner stdout/stderr and the full prompt are written verbatim
  to `logs/` and `work/.../task_prompt.md`. These are gitignored, but they persist on
  disk and may contain whatever the runner printed. Treat `logs/`, `work/`, `state/`,
  `final/`, `reports/`, and `visuals/` as sensitive; do not share/sync/back them up
  carelessly.

- **`--dangerously-bypass-hook-trust`.** Keep `bypass_hook_trust = false` (the
  default) unless you have read codex's documentation and understand what trust gate
  it disables. The harness prints a warning when it is enabled.

- **Unattended/scheduled operation.** The harness ships no scheduler. If you wire one
  (cron/launchd/systemd) around a write-enabled runner, you are running an autonomous
  agent on a timer — harden the environment accordingly.

## Public/private boundary

Keep only reusable code, generic prompts, example config, tests, and docs in this
public repository. Keep real backlog state, drafts, reports, visuals, logs, and
invention history in a separate private workbench. Run `git ls-files` before every
push and never run the workbench inside a clone of this public repo. See
`docs/PUBLIC_PRIVATE_WORKFLOW.md`.
