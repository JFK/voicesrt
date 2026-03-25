Run all quality checks on the codebase.

Steps:
1. Linting:
   ```
   ruff check src/ tests/
   ```
2. Formatting check:
   ```
   ruff format --check src/ tests/
   ```
3. Run tests:
   ```
   pytest -v --maxfail=5
   ```

Report any issues found with file paths and line numbers.
If issues are found, ask if the user wants them auto-fixed (ruff format, ruff check --fix).
