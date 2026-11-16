#!/usr/bin/env bash
# The server's life with Docker Compose, as its owner goes through it with the commands the admin pages' Server page names:
# delete-data (the parts listed, then some deleted with a backup made first), repair (the images built again, the data's
# checks, every part started again) and uninstall (keeping the data, then whole). On a folder of this tree with the pages'
# stand-in game files, under a compose project of its own.
#
# Usage: tests/lifecycle/compose.sh     (PORT, default 18741, the server's one port; NAME_PREFIX names the compose project;
#                                         KEEP=1 leaves what is left)
# Needs Docker with Compose; builds this tree's images under the project's own names.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PORT=${PORT:-18741}
# The compose project: its containers, network and images carry this name, and nothing else's.
PROJECT=${NAME_PREFIX:-odq}-compose-life
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
# answers <address>: waits until the address answers 200 (two minutes at most).
answers() {
  for _ in $(seq 1 120); do
    [ "$(code "$1")" = 200 ] && return 0
    sleep 1
  done
  return 1
}
# The server's command line, in the server's folder, as its owner runs it.
cli() { (cd "$SRV" && ./opendmtq "$@"); }

cleanup() {
  (cd "$SRV" 2>/dev/null && COMPOSE_PROJECT_NAME=$PROJECT docker compose --profile tools down -v --remove-orphans >/dev/null 2>&1) || true
  # What the containers wrote belongs to their user: removed from inside an image (the edge's, which stays here).
  docker run --rm -u 0 -v "$WORK:/w" --entrypoint sh nginxinc/nginx-unprivileged:1.27.5-alpine -c 'rm -rf /w/* /w/.[!.]*' \
    >/dev/null 2>&1 || true
  docker image rm "$PROJECT-server:local" "$PROJECT-tools:local" >/dev/null 2>&1 || true
  rm -rf "$WORK" 2>/dev/null || true
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

# This tree as a folder of its own, as a clone or a release's zip unpacks (without data/ and the scratch folders).
copy_tree() {
  mkdir -p "$SRV"
  tar -C "$ROOT" --exclude=./data --exclude=./_work --exclude=./.host --exclude=./.git --exclude=./.env -cf - . | tar -x -C "$SRV"
}

# The admin pages' Server page, signed in as the owner: on Docker Compose it names the commands.
server_page() {
  local jar
  jar=$(mktemp)
  curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null "http://127.0.0.1:$PORT/opendmtq/admin/login"
  curl -s -m 30 -c "$jar" -b "$jar" -o /dev/null --data-urlencode "name=admin" --data-urlencode "password=$PASSWORD" \
    "http://127.0.0.1:$PORT/opendmtq/admin/login"
  curl -s -m 30 -c "$jar" -b "$jar" "http://127.0.0.1:$PORT/opendmtq/admin/server"
  rm -f "$jar"
}

# 1. A server set up and running, with the stand-in game files.
copy_tree
printf 'COMPOSE_PROJECT_NAME=%s\nPUBLIC_HOST=%s\nLISTEN_PORT=%s\nADMIN_PASSWORD=%s\n' "$PROJECT" "$HOST" "$PORT" "$PASSWORD" \
  > "$SRV/.env"
mkdir -p "$SRV/data/content"
docker build -q -t "$PROJECT-server:local" "$SRV/server" >/dev/null
docker run --rm -u "$(id -u):$(id -g)" -v "$SRV/data/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php \
  "$PROJECT-server:local" /ui/make_content.php /content >/dev/null
cli up > "$WORK/up.log" 2>&1 || true
expect "the server answers on its port" answers "http://127.0.0.1:$PORT/opendmtq/health.php"
expect "the admin pages answer on it" answers "http://127.0.0.1:$PORT/opendmtq/admin/login"
page=$(server_page)
names() { for c in "./opendmtq down" "./opendmtq restart" "./opendmtq repair" "./opendmtq uninstall"; do grep -qF "$c" <<<"$page" || return 1; done; }
expect "the Server page names the commands that stop, restart, repair and uninstall it (ADM-115)" names

# 2. The data: listed by part with its size, then the logs deleted, a backup made first and kept (SRV-48).
cli delete-data > "$WORK/list.log" 2>&1 || true
expect "delete-data lists the parts with their size" grep -q '^database' "$WORK/list.log"
expect "and the game files" grep -q '^game' "$WORK/list.log"
# The owner's sign-in above is in the log of changes: what the deletion of the logs must empty.
expect "the log of changes has the owner's sign-in" test -s "$SRV/data/state/changes.log"
cli delete-data logs recordings --yes > "$WORK/delete.log" 2>&1 || true
sed 's/^/    /' "$WORK/delete.log"
expect "delete-data logs recordings --yes makes a backup first" grep -q 'backup data/backups/opendmtq-.*-before-delete' "$WORK/delete.log"
expect "and deletes them" grep -q 'deleted: logs, recordings' "$WORK/delete.log"
expect "the backup is kept" sh -c "ls '$SRV/data/backups' | grep -q before-delete"
expect "the log of changes is empty now" test ! -s "$SRV/data/state/changes.log"
expect "the database was not touched" grep -q 'database' "$WORK/list.log"
expect "the server still answers" answers "http://127.0.0.1:$PORT/opendmtq/health.php"

# 3. The repair: a data folder and the owner's sign-in for the site gone, then everything again (SRV-49).
rm -rf "$SRV/data/state/live-rec" "$SRV/data/state/owner.pass"
cli repair > "$WORK/repair.log" 2>&1 || true
sed 's/^/    /' "$WORK/repair.log"
expect "repair builds the images again" grep -q 'images built from this folder' "$WORK/repair.log"
expect "and starts the server again with them" grep -q 'the server runs again' "$WORK/repair.log"
expect "every step of the data's checks found it right or put it right" sh -c "grep -E '^(folders|database|owner|songs|files): ' '$WORK/repair.log' | grep -vq ': bad' && ! grep -qE '^(folders|database|owner|songs): bad' '$WORK/repair.log'"
expect "the database was looked at" grep -q '^database: ok' "$WORK/repair.log"
expect "the data folder is there again" test -d "$SRV/data/state/live-rec"
expect "and the owner's sign-in for the site" test -s "$SRV/data/state/owner.pass"
expect "the server answers" answers "http://127.0.0.1:$PORT/opendmtq/admin/login"

# 4. Uninstall, keeping the data: the containers and the images go, data/ and .env stay (DEP-49).
cli uninstall --keep-data --yes > "$WORK/uninstall.log" 2>&1 || true
sed 's/^/    /' "$WORK/uninstall.log"
expect "uninstall --keep-data removes the containers" test -z "$(docker ps -aq --filter "name=^$PROJECT-")"
expect "and the images built for it" sh -c "! docker image inspect '$PROJECT-server:local' >/dev/null 2>&1 && ! docker image inspect '$PROJECT-tools:local' >/dev/null 2>&1"
expect "and leaves only data/ and .env in the folder" test "$(ls -A "$SRV" | tr '\n' ' ')" = ".env data "
expect "nothing answers on the port" test "$(code "http://127.0.0.1:$PORT/opendmtq/health.php")" = 000

# 5. The program put back over the data, the server as it was, then uninstalled whole.
copy_tree
cli up > "$WORK/up2.log" 2>&1 || true
expect "put back over the data kept, the server answers" answers "http://127.0.0.1:$PORT/opendmtq/health.php"
cli uninstall --yes > "$WORK/uninstall2.log" 2>&1 || true
sed 's/^/    /' "$WORK/uninstall2.log"
expect "uninstall --yes removes the folder, the data with it" test ! -e "$SRV"
expect "and the containers" test -z "$(docker ps -aq --filter "name=^$PROJECT-")"

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the server's life with Docker Compose: $failures failure(s)"
exit $((failures > 0))
