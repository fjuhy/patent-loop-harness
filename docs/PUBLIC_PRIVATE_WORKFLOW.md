# Public/Private Repository Workflow

Use this repository as the public upstream for reusable harness code. Keep
private invention work in a separate private workbench repository.

## Direction Of Change

Safe direction:

- public harness -> private workbench

High-risk direction:

- private workbench -> public harness

Never merge private history into the public repository. Private history may
contain draft claims, invention names, prior-art strategy, personal paths, logs,
or commit messages that should not become public.

## Moving A Fix From Private To Public

1. Reproduce the issue with dummy data.
2. Create a minimal patch touching only public-allowed paths.
3. Search the patch for private paths, invention titles, names, and generated
   artifacts.
4. Add or update tests in this repository.
5. Run `git ls-files` and confirm no workbench runtime paths are tracked.
6. Commit the cleaned patch in the public repository.
7. Update the private workbench dependency to the new public commit or version.

## Private Workbench Layout

Recommended private layout:

```text
patent-workbench-private/
  pyproject.toml
  config/
  state/
  work/
  final/
  reports/
  visuals/
  logs/
  memory/
```

The private repository should depend on `patent-loop-harness` instead of copying
the harness source code.
