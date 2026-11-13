#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="$(whoami)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: .env not found at $ENV_FILE. Copy .env.example to .env and configure it first."
  exit 1
fi
for required in GOOGLE_CLOUD_PROJECT GOOGLE_DRIVE_FOLDER_ID SESSION_SECRET ADMIN_MOBILE ADMIN_PASSWORD; do
  value="$(sed -n "s/^${required}=//p" "$ENV_FILE" | tail -n1 | tr -d '\r')"
  if [[ -z "$value" || "$value" == REPLACE_* || "$value" == your-* || "$value" == "1234567890" ]]; then
    echo "ERROR: Set a real value for $required in .env"
    exit 1
  fi
done

CREDENTIAL_PATH="$(sed -n 's/^GOOGLE_APPLICATION_CREDENTIALS=//p' "$ENV_FILE" | tail -n1 | tr -d '\r')"
if [[ -n "$CREDENTIAL_PATH" && ! -f "$CREDENTIAL_PATH" ]]; then
  echo "ERROR: Google service-account file not found: $CREDENTIAL_PATH"
  exit 1
fi

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
chmod 600 "$ENV_FILE"

SERVICE_FILE="/etc/systemd/system/mastermind-portal.service"
sudo tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=Master Mind Portal FastAPI service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$ROOT/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable mastermind-portal
sudo systemctl restart mastermind-portal
sleep 3
sudo systemctl --no-pager --full status mastermind-portal || true
if command -v curl >/dev/null 2>&1; then
  echo "Checking local health endpoint..."
  curl --fail --silent --show-error http://127.0.0.1:8000/api/health || {
    echo "Health check failed. Inspect: sudo journalctl -u mastermind-portal -n 100 --no-pager"
    exit 1
  }
  echo
fi

echo "Deployment service installed. Configure Nginx + HTTPS using deploy/nginx-mastermind.conf before public launch."
