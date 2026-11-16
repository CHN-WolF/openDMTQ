#!/usr/bin/env bash
# The update of a host install of an earlier release to this tree's, in a clean computer (a container), as its owner does
# it: the release installed by its own one command and set up by its own setup (which writes .env: this computer's
# address, the port, the password, and in 0.10.0 the admin pages' own port, ADMIN_PORT=8791), then the one command again
# with this tree, which stops the server and puts the new code over the old with the settings and the data kept, and a
# start. Afterwards the server keeps its port (the one the phones' app calls), the players' site, the admin pages and the
# API answer on it, nothing answers on the admin pages' old port, .env no longer names it, status names one address, and
# the owner's ID and password open both doors (DEP-47).
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
inside "cd OpenDMTQ && ./opendmtq start" > "$WORK/start.log" 2>&1 || true
sed 's/^/    /' "$WORK/start.log"
expect "the updated server keeps its port and address, the ones the phones' app calls" \
  sh -c "test '$(setting LISTEN_PORT)' = '$port' && test '$(setting PUBLIC_HOST)' = '$host'"
expect "the players' site answers on it" sh -c "case \$(docker exec -u player $NAME curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1:$port/opendmtq/health.php) in 200 | 503) exit 0 ;; esac; exit 1"
for _ in $(seq 1 30); do
  is 200 "http://127.0.0.1:$port/opendmtq/admin/login" && break
  sleep 2
done
expect "the admin pages answer on that same port" is 200 "http://127.0.0.1:$port/opendmtq/admin/login"
expect "and the API" is 401 "http://127.0.0.1:$port/opendmtq/api/v1/status"
expect "nothing answers on the admin pages' old port ($old_admin)" is 000 "http://127.0.0.1:$old_admin/opendmtq/admin/login"
expect ".env no longer names it, and keeps the rest" \
  sh -c "! docker exec -u player $NAME grep -q '^ADMIN_PORT=' /home/player/OpenDMTQ/.env && test '$(setting ADMIN_PASSWORD)' = '$password'"
inner=$(inside "cat OpenDMTQ/.host/run/admin.port 2>/dev/null" | tr -d '\r\n' || true)
expect "the admin service's own port is neither the old one nor the server's (${inner:-none})" \
  sh -c "test -n '$inner' && test '$inner' != '$old_admin' && test '$inner' != '$port'"
inside "cd OpenDMTQ && ./opendmtq status" > "$WORK/status.log" 2>&1 || true
sed 's/^/    /' "$WORK/status.log"
expect "status names the admin pages at the server's one address" grep -q "http://$host/opendmtq/admin/" "$WORK/status.log"
expect "start and status never name the old port" sh -c "! grep -q ':$old_admin\\b' '$WORK/status.log' '$WORK/start.log'"
# The owner's ID and password from .env, on both doors, each in a browser of its own.
signed=$(inside "j=\$(mktemp); curl -s -m 30 -c \$j -b \$j -o /dev/null http://127.0.0.1:$port/opendmtq/admin/login; curl -s -m 30 -c \$j -b \$j -o /dev/null -w '%{http_code}' --data-urlencode name=admin --data-urlencode 'password=$password' http://127.0.0.1:$port/opendmtq/admin/login" || true)
expect "the owner signs in to the admin pages there ($signed)" test "$signed" = 302
signed=$(inside "j=\$(mktemp); curl -s -m 30 -c \$j -b \$j -o /dev/null http://127.0.0.1:$port/opendmtq/login.php; curl -s -m 30 -c \$j -b \$j -o /dev/null -w '%{http_code}' --data-urlencode user=admin --data-urlencode 'password=$password' -d next=/opendmtq/ http://127.0.0.1:$port/opendmtq/login.php" || true)
expect "and to the players' site with the same ID and password ($signed)" test "$signed" = 303

echo "$([ $failures = 0 ] && echo PASS || echo FAIL) the update of a host install from $FROM on $DISTRO: $failures failure(s)"
exit $((failures > 0))
