#!/bin/sh
set -e

# Run migrations before starting the server
python -c "
from src.database import ensure_dirs, run_migrations
ensure_dirs()
run_migrations()
print('Migrations complete.')
"

# Start uvicorn
exec uvicorn src.main:app --host 0.0.0.0 --port 8000
