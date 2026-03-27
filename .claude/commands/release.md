---
description: Bump version, update CHANGELOG, create git tag
---

Release a new version. Argument should be: patch, minor, or major (default: patch).

## Steps

1. Read current version from `pyproject.toml` (line: `version = "X.Y.Z"`)
2. Bump version based on argument:
   - `patch`: 0.1.0 → 0.1.1
   - `minor`: 0.1.0 → 0.2.0
   - `major`: 0.1.0 → 1.0.0
3. Get commits since last tag (or all commits if no tags):
   ```bash
   git log $(git describe --tags --abbrev=0 2>/dev/null || git rev-list --max-parents=0 HEAD)..HEAD --oneline
   ```
4. Update `pyproject.toml` with new version
5. Prepend new version section to `CHANGELOG.md`:
   - Group commits by type (feat/fix/refactor/docs/chore)
   - Use today's date
6. Stage and commit: `chore(release): vX.Y.Z`
7. Create annotated git tag: `git tag -a vX.Y.Z -m "Release vX.Y.Z"`
8. Show summary and ASK the user before pushing:
   - New version number
   - Changelog entries
   - "Push to remote? (git push origin main --tags)"
