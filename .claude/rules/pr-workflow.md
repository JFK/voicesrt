---
description: Required workflow before merging code changes. Follow this sequence for every feature/fix branch.
---

# PR Workflow Rule

## Required Sequence

1. **`/simplify`** — Review changed code for reuse, quality, and efficiency. Fix issues found.
2. **`/self-review`** — Self-review the diff before creating a PR.
3. **`/quality`** — Run all quality checks (ruff lint, ruff format, pytest).
4. **Create PR** — Push branch and create pull request via `gh pr create`.
5. **PR Review** — Review the PR (or request review from maintainer).
6. **PR Merge** — Merge after approval and CI passes.

## Do NOT
- Push directly to `main` without a PR (except docs-only or config changes explicitly approved)
- Skip `/quality` — CI will catch it anyway, but catching locally is faster
- Merge with failing checks
