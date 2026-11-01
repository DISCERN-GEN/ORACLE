#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then
  echo ".env already exists; leaving it untouched."
  exit 0
fi
cp .env.example .env
api_token="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
db_password="$(python -c 'import secrets; print(secrets.token_urlsafe(36))')"
python - "$api_token" "$db_password" <<'PY'
from pathlib import Path
import sys
p = Path('.env')
s = p.read_text()
s = s.replace('change-this-long-random-token', sys.argv[1])
s = s.replace('change-me-before-use', sys.argv[2])
p.write_text(s)
PY
chmod 600 .env
echo "Created .env with unique local secrets (file permissions 600)."
