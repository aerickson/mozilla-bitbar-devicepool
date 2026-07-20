# Repository Guidelines

## Project Structure & Module Organization
The core Python package lives in `mozilla_bitbar_devicepool/`, with vendor-specific logic in `bitbar/` and `lambdatest/`. Supporting CLI entry points are defined in `pyproject.toml` and mirrored as helper scripts in `bin/`. Shared utils and report generators sit under `util/` and `device_group_report*.py`, while environment and service configuration lives in `config/` and `service/`. Tests reside in `mozilla_bitbar_devicepool/test/`, alongside fixture data in `test_data/`.

## Build, Test, and Development Commands
Run `poetry install --with=dev` to sync dependencies, then `poetry shell` for an interactive environment. Use `pre-commit install` once per clone to enable formatting and lint hooks. Execute unit tests with `pytest` or the coverage variant `pytest --cov --cov-report=term`. CLI entry points run via `poetry run`, e.g., `poetry run mld` for LambdaTest device runs or `poetry run dgr` for Bitbar reports.

## Coding Style & Naming Conventions
Stick to Python 3.9+ with 4-space indentation and descriptive, snake_case names for modules, functions, and variables. Formatting and imports are enforced by `ruff-format` with a 120-character line limit; structural linting runs via `ruff check --select I --fix` and `pylint` in CI/pre-commit. Configuration files use YAML or TOML—mirror existing key naming and comment styles.

## Testing Guidelines
Place new tests in `mozilla_bitbar_devicepool/test/` following the `<module>_test.py` pattern and reuse helpers in `util_test.py`. Prefer `pytest` fixtures over ad-hoc setup; store serialized inputs in `test_data/`. Validate coverage locally with `pytest --cov --cov-report=html` and ensure critical branches that touch vendor APIs are exercised via mocks.

## Commit & Pull Request Guidelines
Commit messages are short (≤72 characters), lowercase, and often scoped (`lt status: refresh cache`). Group related edits per commit and reference Bugzilla or GitHub IDs when applicable. Pull requests should describe vendor impact, outline testing (`pytest`, manual device run), and include screenshots or log snippets when UI or report output changes. Link configuration updates to rollout plans so reviewers can validate credentials and scheduling.

<!-- br-agent-instructions-v1 -->

---

## Beads Workflow Integration

This project uses [beads_rust](https://github.com/Dicklesworthstone/beads_rust) (`br`/`bd`) for issue tracking. Issues are stored in `.beads/` and tracked in git.

### Essential Commands

```bash
# View ready issues (open, unblocked, not deferred)
br ready              # or: bd ready

# List and search
br list --status=open # All open issues
br show <id>          # Full issue details with dependencies
br search "keyword"   # Full-text search

# Create and update
br create --title="..." --description="..." --type=task --priority=2
br update <id> --status=in_progress
br close <id> --reason="Completed"
br close <id1> <id2>  # Close multiple issues at once

# Sync with git
br sync --flush-only  # Export DB to JSONL
br sync --status      # Check sync status
```

### Workflow Pattern

1. **Start**: Run `br ready` to find actionable work
2. **Claim**: Use `br update <id> --status=in_progress`
3. **Work**: Implement the task
4. **Complete**: Use `br close <id>`
5. **Sync**: Always run `br sync --flush-only` at session end

### Key Concepts

- **Dependencies**: Issues can block other issues. `br ready` shows only open, unblocked work.
- **Priority**: P0=critical, P1=high, P2=medium, P3=low, P4=backlog (use numbers 0-4, not words)
- **Types**: task, bug, feature, epic, chore, docs, question
- **Blocking**: `br dep add <issue> <depends-on>` to add dependencies

### Session Protocol

**Before ending any session, run this checklist:**

```bash
git status              # Check what changed
git add <files>         # Stage code changes
br sync --flush-only    # Export beads changes to JSONL
git commit -m "..."     # Commit everything
git push                # Push to remote
```

### Best Practices

- Check `br ready` at session start to find available work
- Update status as you work (in_progress → closed)
- Create new issues with `br create` when you discover tasks
- Use descriptive titles and set appropriate priority/type
- Always sync before ending session

<!-- end-br-agent-instructions -->
