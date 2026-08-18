#!/usr/bin/env bash
# Read-only smoke checks against a running self-host stack: gateway healthy,
# frontend proxying to it, workers alive. Invoked via `make self-host-smoke`.
set -euo pipefail
: "${SELFHOST_COMPOSE:?the make target passes the compose invocation}"

curl -fsS http://localhost:8000/health && echo
curl -fsS http://localhost/api/health && echo
curl -fsS -o /dev/null http://localhost/

# Workers load their models during startup, so zero restarts means imports and
# model load survived.
for svc in kokoro-cpu yolo-cpu; do
  cid=$($SELFHOST_COMPOSE ps -q "$svc")
  docker inspect -f "$svc: {{.State.Status}}, {{.RestartCount}} restarts" "$cid"
  [ "$(docker inspect -f '{{.State.Status}}/{{.RestartCount}}' "$cid")" = "running/0" ]
done
echo "self-host smoke: OK"
