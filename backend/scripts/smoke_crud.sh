#!/usr/bin/env bash
# Smoke test the full CRUD lifecycle against a local PrintShelf instance.
# Assumes server is running at $BASE (default http://127.0.0.1:8765).
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8765}"
JQ() { python3 -c "import json,sys; d=json.load(sys.stdin); $*"; }
J() { python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), indent=2))"; }

EMAIL="smoke-$(date +%s)@printshelf.app"
USER="smoke$(date +%s)"

echo "== register =="
REG=$(curl -sf -X POST "$BASE/api/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"correcthorse\",\"username\":\"$USER\"}")
TOKEN=$(echo "$REG" | JQ "print(d['token'])")
APIKEY=$(echo "$REG" | JQ "print(d['user']['apiKey'])")
H="Authorization: Bearer $TOKEN"
HK="Authorization: Bearer $APIKEY"

echo "== create printer =="
PRINTER=$(curl -sf -X POST "$BASE/api/printers" -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"My X1C","brand":"Bambu Lab","model":"X1 Carbon"}')
echo "$PRINTER" | J
PID=$(echo "$PRINTER" | JQ "print(d['id'])")

echo "== create filament (via API key, simulating Chrome extension) =="
FIL=$(curl -sf -X POST "$BASE/api/filaments" -H "$HK" -H 'Content-Type: application/json' \
  -d '{"brand":"Bambu Lab","material":"PLA","color_name":"Galaxy Black","color_hex":"111111","diameter":1.75,"status":"own"}')
echo "$FIL" | J
FID=$(echo "$FIL" | JQ "print(d['id'])")

echo "== queue a print via /api/prints/queue (Chrome extension path) =="
QP=$(curl -sf -X POST "$BASE/api/prints/queue" -H "$HK" -H 'Content-Type: application/json' \
  -d "{\"title\":\"Articulated Dragon\",\"designer\":\"Cinderwing3D\",\"source_platform\":\"printables\",\"source_url\":\"https://www.printables.com/model/3\",\"printer_id\":$PID,\"filament_ids\":[$FID]}")
echo "$QP" | J
QPID=$(echo "$QP" | JQ "print(d['id'])")

echo "== list queued =="
curl -sf "$BASE/api/prints?queued=true" -H "$H" | J

echo "== mark printed =="
curl -sf -X POST "$BASE/api/prints/$QPID/printed" -H "$H" | J

echo "== list all prints =="
curl -sf "$BASE/api/prints" -H "$H" | J

echo "== patch filament: status=used_up =="
curl -sf -X PATCH "$BASE/api/filaments/$FID" -H "$H" -H 'Content-Type: application/json' \
  -d '{"status":"used_up"}' | J

echo "== bad status (expect 400) =="
curl -s -o /dev/null -w "  HTTP %{http_code}\n" -X PATCH "$BASE/api/filaments/$FID" -H "$H" -H 'Content-Type: application/json' \
  -d '{"status":"bogus"}'

echo "== cross-user isolation (expect 404 for foreign user) =="
REG2=$(curl -sf -X POST "$BASE/api/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"other-$EMAIL\",\"password\":\"correcthorse\",\"username\":\"other$USER\"}")
T2=$(echo "$REG2" | JQ "print(d['token'])")
curl -s -o /dev/null -w "  GET foreign printer HTTP %{http_code}\n" "$BASE/api/printers/$PID" -H "Authorization: Bearer $T2"

echo "== delete printer =="
curl -s -o /dev/null -w "  HTTP %{http_code}\n" -X DELETE "$BASE/api/printers/$PID" -H "$H"

echo "OK"
