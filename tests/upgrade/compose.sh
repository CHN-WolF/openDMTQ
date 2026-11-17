#!/usr/bin/env bash
# An upgrade of a Docker Compose server, done the way its owner does it: the last release's folder set up and run with
# ./opendmtq up (its admin pages on a port of their own then), the new code put over it with the settings and the data
# kept, and ./opendmtq up again. The release's .env is then made the one a server on port 80 has (an address without a
# port, no LISTEN_PORT: what the release's setup wrote where port 80 was free; this PC's own port 80 is never taken).
# Afterwards the server has left port 80 for the port its admin pages had: the players' site, the admin pages and the
# API answer there and on nothing else of this server, the console says the move once and names that one address,
# status says it once, the site's download page tells players to install the app for the new address, the app builder
# works for it, and the owner's ID and password from .env open both the admin pages and the site, also after a stop and
# a start (DEP-47, DEP-72).
#
# Usage: tests/upgrade/compose.sh      (FROM=v0.10.0, the release to upgrade from; PORT, default 18721, the server's port,
#                                       and PORT+1 the old admin port; NAME_PREFIX names the compose project; KEEP=1
#                                       leaves it up)
# Needs Docker with Compose and git; builds both trees' images under the project's own names.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
FROM=${FROM:-v0.10.0}
PORT=${PORT:-18721}
OLD_ADMIN=$((PORT + 1))
# The compose project: its containers, network and images carry this name, and nothing else's.
PROJECT=${NAME_PREFIX:-odq}-compose-upgrade
PASSWORD=compose-pass
# A made-up local network address: what phones would use, the address written into the app.
HOST=192.168.1.10:$PORT
WORK=$(mktemp -d)
SRV=$WORK/OpenDMTQ
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
# expect <name> <command...>: PASS when the command succeeds.
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
# The HTTP status of an address (000 when nothing answers); more curl options after it.
code() { curl -s -o /dev/null -w '%{http_code}' -m 10 "$@" || true; }
# The server's command line, in the server's folder, as its owner runs it; never changing Windows' firewall on a WSL
# machine (OPENDMTQ_NO_FIREWALL), uninstall and port included.
cli() { (cd "$SRV" && OPENDMTQ_NO_FIREWALL=1 ./opendmtq "$@"); }

cleanup() {
  (cd "$SRV" 2>/dev/null && COMPOSE_PROJECT_NAME=$PROJECT docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  # What the containers wrote belongs to their user: removed from inside an image.
  docker run --rm -u 0 -v "$WORK:/w" --entrypoint sh "$PROJECT-server:local" -c 'rm -rf /w/* /w/.[!.]*' >/dev/null 2>&1 || true
  docker image rm "$PROJECT-server:local" "$PROJECT-tools:local" >/dev/null 2>&1 || true
  rm -rf "$WORK" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

# owner_signs_in <when>: the ID and password in .env open the admin pages on the server's one port and the players' site,
# each in a browser of its own (ADM-105). From this PC, as localhost: the visit stays on plain HTTP.
owner_signs_in() {
  local jar status
  jar=$(mktemp)
  curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/admin/login"
  status=$(curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' --data-urlencode "name=admin" \
    --data-urlencode "password=$PASSWORD" "http://127.0.0.1:$PORT/opendmtq/admin/login")
  expect "$1, the owner signs in to the admin pages on the server's port ($status)" test "$status" = 302
  rm -f "$jar"
  jar=$(mktemp)
  curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/login.php"
  status=$(curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null -w '%{http_code}' --data-urlencode "user=admin" \
    --data-urlencode "password=$PASSWORD" -d "next=/opendmtq/" "http://127.0.0.1:$PORT/opendmtq/login.php")
  expect "$1, the owner signs in to the players' site with the same ID and password ($status)" test "$status" = 303
  rm -f "$jar"
}

# answers <address>: waits until the address answers 200 (two minutes at most).
answers() {
  for _ in $(seq 1 120); do
    [ "$(code "$1")" = 200 ] && return 0
    sleep 1
  done
  return 1
}

# 1. The release's folder, as its zip unpacks, set up as two copies on one PC are: a port of its own and an admin port
#    beside it (what ./opendmtq picked then; a server alone on its PC has 8791 there, which on this PC is the live
#    server's, outside this test's ports), the stand-in game files imported.
mkdir -p "$SRV"
git -C "$ROOT" archive "$FROM" | tar -x -C "$SRV"
printf 'COMPOSE_PROJECT_NAME=%s\nPUBLIC_HOST=%s\nLISTEN_PORT=%s\nADMIN_PORT=%s\nADMIN_PASSWORD=%s\n' \
  "$PROJECT" "$HOST" "$PORT" "$OLD_ADMIN" "$PASSWORD" > "$SRV/.env"
mkdir -p "$SRV/data/content"
docker build -q -t "$PROJECT-server:local" "$SRV/server" >/dev/null
docker run --rm -u "$(id -u):$(id -g)" -v "$SRV/data/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php \
  "$PROJECT-server:local" /ui/make_content.php /content >/dev/null
cli up > "$WORK/old-up.log" 2>&1 || true
expect "the release's server answers on its port" answers "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "and its admin pages on a port of their own, as they did" answers "http://127.0.0.1:$OLD_ADMIN/opendmtq/admin/login"
# What the release did with the owner's ID and password on the players' site, for the record (it refused them: 200, the
# sign-in page again).
jar=$(mktemp)
curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/login.php"
echo "INFO the release's players' site, signed in to with the owner's ID and password: $(curl -s -m 30 -c "$jar" -b "$jar" \
  -o /dev/null -w '%{http_code}' --data-urlencode "user=admin" --data-urlencode "password=$PASSWORD" -d "next=/opendmtq/" \
  "http://127.0.0.1:$PORT/opendmtq/login.php") (303 signs in)"
rm -f "$jar"
cli down > /dev/null 2>&1 || true

# 2. The release's .env as a server on port 80 has it: its address without a port, and no LISTEN_PORT.
OLD_HOST=${HOST%:*}
sed -i -e "s/^PUBLIC_HOST=.*/PUBLIC_HOST=$OLD_HOST/" -e '/^LISTEN_PORT=/d' "$SRV/.env"
# The new code over it, as an update brings it (the folder's files replaced, .env and data/ kept), then up again.
find "$SRV" -mindepth 1 -maxdepth 1 ! -name data ! -name .env -exec rm -rf {} +
tar -C "$ROOT" --exclude=./data --exclude=./_work --exclude=./.host --exclude=./.git --exclude=./.env -cf - . | tar -x -C "$SRV"
# --no-firewall: under WSL the move would take the Windows firewall's rule for port 80 to the new port, and this machine's
# firewall belongs to its own servers, never to a test's.
cli up --no-firewall > "$WORK/up.log" 2>&1 || true
sed 's/^/    /' "$WORK/up.log"
# Where it moved: the port its admin pages had, and the address with it.
PORT=$OLD_ADMIN
HOST=$OLD_HOST:$PORT
expect "the upgraded server left port 80 for the port its admin pages had: LISTEN_PORT=$PORT" grep -qx "LISTEN_PORT=$PORT" "$SRV/.env"
expect "and the address carries it" grep -qx "PUBLIC_HOST=$HOST" "$SRV/.env"
expect "the players' site answers there" answers "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "the admin pages answer on that same port (DEP-47)" answers "http://127.0.0.1:$PORT/opendmtq/admin/login"
expect "and the API" sh -c "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:$PORT/opendmtq/api/v1/status)\" = 401 ]"
expect "the server publishes that one port and no other" sh -c "[ \"\$(docker port $PROJECT-edge 8790/tcp | sed 's/.*://' | sort -u)\" = $PORT ]"
expect "the release's port is closed" test "$(code "http://127.0.0.1:$((OLD_ADMIN - 1))/opendmtq/health.php")" = 000
expect "and .env no longer names the admin pages' own port (ADMIN_PORT gone, the rest kept)" sh -c "! grep -q '^ADMIN_PORT=' '$SRV/.env' && grep -q '^ADMIN_PASSWORD=$PASSWORD' '$SRV/.env'"
expect "up says the move once" sh -c "[ \"\$(grep -c 'The server moved from port 80 to $PORT: http://$HOST/' '$WORK/up.log')\" = 1 ]"
expect "up names the admin pages at the one address" grep -Eq "Admin pages +http://$HOST/opendmtq/admin/" "$WORK/up.log"
expect "and never the address on port 80" sh -c "! grep -q 'http://$OLD_HOST/' '$WORK/up.log'"
expect "the app builder works for the new address" grep -q "\"host\": \"$HOST\"" "$SRV/data/apk/out/build.json"
# From another computer, by the address phones use: sent to HTTPS while it works, as before.
went=$(code -H "Host: $HOST" "http://127.0.0.1:$PORT/opendmtq/admin/login")
expect "from another computer the admin pages go to HTTPS ($went)" test "$went" = 302
owner_signs_in "upgraded"
cli status > "$WORK/status.log" 2>&1 || true
expect "status names the one address" grep -q "http://$HOST/opendmtq/admin/" "$WORK/status.log"
cli status > "$WORK/status2.log" 2>&1 || true
expect "status says the move once" sh -c "grep -q 'moved from port 80 to $PORT' '$WORK/status.log' && ! grep -q 'moved from port' '$WORK/status2.log'"
# The site's download page, to a player signed in: where the server is now, and the app for that address.
jar=$(mktemp)
curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/login.php"
curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null --data-urlencode "user=admin" --data-urlencode "password=$PASSWORD" \
  -d "next=/opendmtq/" "http://127.0.0.1:$PORT/opendmtq/login.php"
expect "the download page says the move" sh -c "curl -s -m 30 -b '$jar' http://127.0.0.1:$PORT/opendmtq/download.php | grep -q 'it is at $HOST now, $OLD_HOST before'"
rm -f "$jar"

# 3. Stopped and started again, the owner's own steps before the password no longer worked.
cli down > /dev/null 2>&1 || true
expect "stopped: nothing answers" test "$(code "http://127.0.0.1:$PORT/opendmtq/health.php")" = 000
cli up --no-firewall > "$WORK/up2.log" 2>&1 || true
expect "started again, the site answers" answers "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "and the admin pages" answers "http://127.0.0.1:$PORT/opendmtq/admin/login"
owner_signs_in "stopped and started again"

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the upgrade of a Docker Compose server from $FROM: $failures failure(s)"
exit $((failures > 0))
