#!/usr/bin/env bash
# The update of a host install of an earlier release to this tree's, in a clean computer (a container), as its owner does
# it: the release installed by its own one command and set up by its own setup (which writes .env: this computer's
# address, port 80, the password, and in 0.10.0 the admin pages' own port, ADMIN_PORT=8791), then the one command again
# with this tree, which stops the server and puts the new code over the old with the settings and the data kept, and a
# start. Afterwards the server has left port 80 for the port its admin pages had (8791): the players' site, the admin
# pages and the API answer there and nothing on port 80, .env names the new address and no longer the admin pages' own
# port, the start says the move once and status once, status names one address, the site's download page tells players to
# install the app for the new address, the app builder works for it, and the owner's ID and password open both doors
# (DEP-47, DEP-72).
#
# Usage: tests/host/update.sh      (FROM=v0.10.0, the release to update from; DISTRO=debian:12 for another system;
#                                   NEW=<a git ref> updates to that ref instead of this working tree, so that the checks can
#                                   be seen to fail on a release that leaves the old port; NAME_PREFIX names the container;
#                                   KEEP=1 leaves it running)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
FROM=${FROM:-v0.10.0}
DISTRO=${DISTRO:-ubuntu:24.04}
NAME=${NAME_PREFIX:-odq}-host-update
IMAGE=opendmtqtest:$(echo "$DISTRO" | tr ':/' '--')
WORK=$(mktemp -d)
failures=0

pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
# expect <name> <command...>: PASS when the command succeeds.
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
# A command as the user inside the computer, in their home folder.
inside() { docker exec -u player -w /home/player "$NAME" bash -lc "$1"; }
# The HTTP status of an address inside the computer (000 when nothing answers there).
code() { inside "curl -s -o /dev/null -w '%{http_code}' -m 10 '$1'" 2>/dev/null || true; }
is() { [ "$(code "$2")" = "$1" ]; }
# A setting from the install's .env.
setting() { inside "sed -n 's/^$1=//p' OpenDMTQ/.env | tr -d '\\r' | tail -n 1"; }

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
if [ -z "${KEEP:-}" ]; then
  trap cleanup EXIT
fi

# The computer: the system, sudo, and a user who may use it without a password, as tests/host/run.sh makes it. On a
# network of its own: its ports, 80 and 8791 included, are the container's, never this computer's.
docker build -q -t "$IMAGE" - >/dev/null <<EOF
FROM $DISTRO
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq sudo ca-certificates curl >/dev/null \
    && useradd -m -s /bin/bash player && echo 'player ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/player
EOF
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" "$IMAGE" sleep infinity >/dev/null

# The release as GitHub hands out its source (one folder on top), its own one command, and the new code likewise.
git -C "$ROOT" archive --prefix="openDMTQ-${FROM#v}/" "$FROM" | gzip > "$WORK/old.tar.gz"
git -C "$ROOT" show "$FROM:host/get.sh" > "$WORK/old-get.sh"
if [ -n "${NEW:-}" ]; then
  git -C "$ROOT" archive --prefix=openDMTQ-main/ "$NEW" | gzip > "$WORK/new.tar.gz"
  git -C "$ROOT" show "$NEW:host/get.sh" > "$WORK/new-get.sh"
else
  tar -C "$ROOT" --exclude=./data --exclude=./_work --exclude=./.host --exclude=./.git --exclude=./.env \
    --transform 's,^\.,openDMTQ-main,' -czf "$WORK/new.tar.gz" .
  cp "$ROOT/host/get.sh" "$WORK/new-get.sh"
fi
chmod a+r "$WORK"/*
for f in old.tar.gz old-get.sh new.tar.gz new-get.sh; do
  docker cp "$WORK/$f" "$NAME:/tmp/$f"
done

# 1. The release, installed as its README said, and set up by its own setup: it chooses the port and writes .env, starts
#    the server, and with no game files yet hands over to its pages.
if timeout 1200 docker exec -u player -w /home/player "$NAME" bash -lc \
    "OPENDMTQ_TARBALL=file:///tmp/old.tar.gz OPENDMTQ_DIR=\$HOME/OpenDMTQ OPENDMTQ_NO_SETUP=1 sh /tmp/old-get.sh" \
    > "$WORK/old-install.log" 2>&1; then
  pass "the release installs with its own one command"
else
  tail -n 20 "$WORK/old-install.log"
  fail "the release installs with its own one command"
  exit 1
fi
inside "cd OpenDMTQ && ./opendmtq setup" > "$WORK/old-setup.log" 2>&1 || true
port=$(setting LISTEN_PORT)
host=$(setting PUBLIC_HOST)
password=$(setting ADMIN_PASSWORD)
old_admin=$(setting ADMIN_PORT)
echo "INFO the release's .env: PUBLIC_HOST=$host LISTEN_PORT=$port ADMIN_PORT=${old_admin:-none} (the password not shown)"
expect "the release serves on the port its setup chose (${port:-none})" sh -c "case \$(docker exec -u player $NAME curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:${port:-1}/opendmtq/health.php) in 200 | 503) exit 0 ;; esac; exit 1"
expect "and its admin pages on a port of their own (ADMIN_PORT=${old_admin:-none})" is 200 "http://127.0.0.1:${old_admin:-1}/opendmtq/admin/login"

# 2. The one command again, with the new code: it stops the server, puts the new code over the old, keeps .env and data.
if timeout 1200 docker exec -u player -w /home/player "$NAME" bash -lc \
    "OPENDMTQ_TARBALL=file:///tmp/new.tar.gz OPENDMTQ_DIR=\$HOME/OpenDMTQ OPENDMTQ_NO_SETUP=1 sh /tmp/new-get.sh" \
    > "$WORK/new-install.log" 2>&1; then
  pass "the one command again updates the install"
else
  tail -n 20 "$WORK/new-install.log"
  fail "the one command again updates the install"
fi
expect "the release served port 80 (LISTEN_PORT=$port, PUBLIC_HOST=$host)" sh -c "test '$port' = 80 && test '${host#*:}' = '$host'"
inside "cd OpenDMTQ && ./opendmtq start" > "$WORK/start.log" 2>&1 || true
sed 's/^/    /' "$WORK/start.log"
# The port it moved to, the admin pages' own before (8791), and the address with it.
moved=$(setting LISTEN_PORT)
new_host=$host:$old_admin
expect "the updated server left port 80 for the port its admin pages had ($moved)" \
  sh -c "test '$moved' = '$old_admin' && test '$(setting PUBLIC_HOST)' = '$new_host'"
expect "the players' site answers there" sh -c "case \$(docker exec -u player $NAME curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:$moved/opendmtq/health.php) in 200 | 503) exit 0 ;; esac; exit 1"
for _ in $(seq 1 30); do
  is 200 "http://127.0.0.1:$moved/opendmtq/admin/login" && break
  sleep 2
done
expect "the admin pages answer on that same port" is 200 "http://127.0.0.1:$moved/opendmtq/admin/login"
expect "and the API" is 401 "http://127.0.0.1:$moved/opendmtq/api/v1/status"
expect "nothing answers on port 80, where the release served" is 000 "http://127.0.0.1:80/opendmtq/health.php"
expect ".env no longer names the admin pages' own port, and keeps the rest" \
  sh -c "! docker exec -u player $NAME grep -q '^ADMIN_PORT=' /home/player/OpenDMTQ/.env && test '$(setting ADMIN_PASSWORD)' = '$password'"
inner=$(inside "cat OpenDMTQ/.host/run/admin.port 2>/dev/null" | tr -d '\r\n' || true)
expect "the admin service's own port is not the server's (${inner:-none})" sh -c "test -n '$inner' && test '$inner' != '$moved'"
expect "start says the move from port 80 once" sh -c "test \$(grep -c 'The server moved from port 80 to $moved: http://$new_host/' '$WORK/start.log') = 1"
inside "cd OpenDMTQ && ./opendmtq status" > "$WORK/status.log" 2>&1 || true
inside "cd OpenDMTQ && ./opendmtq status" > "$WORK/status2.log" 2>&1 || true
sed 's/^/    /' "$WORK/status.log"
expect "status names the admin pages at the server's one address" grep -q "http://$new_host/opendmtq/admin/" "$WORK/status.log"
expect "status says the move once" sh -c "grep -q 'moved from port 80 to $moved' '$WORK/status.log' && ! grep -q 'moved from port' '$WORK/status2.log'"
expect "start and status never name the address on port 80" sh -c "! grep -q 'http://$host/' '$WORK/status.log' '$WORK/start.log'"
expect "the app builder works for the new address" sh -c "docker exec -u player $NAME grep -q '\"host\": \"$new_host\"' /home/player/OpenDMTQ/data/apk/out/build.json"
# The owner's ID and password from .env, on both doors, each in a browser of its own.
signed=$(inside "j=\$(mktemp); curl -s -m 30 -c \$j -b \$j -o /dev/null http://127.0.0.1:$moved/opendmtq/admin/login; curl -s -m 30 -c \$j -b \$j -o /dev/null -w '%{http_code}' --data-urlencode name=admin --data-urlencode 'password=$password' http://127.0.0.1:$moved/opendmtq/admin/login" || true)
expect "the owner signs in to the admin pages there ($signed)" test "$signed" = 302
signed=$(inside "j=\$(mktemp); curl -s -m 30 -c \$j -b \$j -o /dev/null http://127.0.0.1:$moved/opendmtq/login.php; curl -s -m 30 -c \$j -b \$j -o /dev/null -w '%{http_code}' --data-urlencode user=admin --data-urlencode 'password=$password' -d next=/opendmtq/ http://127.0.0.1:$moved/opendmtq/login.php" || true)
expect "and to the players' site with the same ID and password ($signed)" test "$signed" = 303
# The download page, to that signed-in browser: where the server is now, and the app for that address.
said=$(inside "j=\$(mktemp); curl -s -m 30 -c \$j -b \$j -o /dev/null http://127.0.0.1:$moved/opendmtq/login.php; curl -s -m 30 -c \$j -b \$j -o /dev/null --data-urlencode user=admin --data-urlencode 'password=$password' -d next=/opendmtq/ http://127.0.0.1:$moved/opendmtq/login.php; curl -s -m 30 -b \$j http://127.0.0.1:$moved/opendmtq/download.php" || true)
expect "the download page says the move" grep -q "it is at $new_host now, $host before" <<<"$said"

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the update of a host install from $FROM on $DISTRO: $failures failure(s)"
exit $((failures > 0))
