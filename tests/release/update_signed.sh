#!/bin/bash
# Installed PC clients updating under Wine, on a Docker network with no way out, from releases signed with a key made for
# the test (never the project's):
#   server-delta    0.11.0 updates to 0.11.1 through its server's /updates/ (the real server image, the files the tools
#                   kept for it, client_updates.py): the delta package, put together by the installed Update.exe;
#   server-full     the same with the delta package not handed out: the whole package;
#   matched         the server hands out 0.11.0, GitHub has 0.11.1: the launcher stays with its server's version;
#   github          0.11.0 with no server updates to 0.11.1 from a stand-in for GitHub's releases (github_stub.py);
#   tampered        the server hands out a full package with a byte changed: refused, nothing put in;
#   wrong-signature the server hands out checksums signed by another key: refused at the check, nothing fetched;
#   old-github      0.10.0 (the last release, which checks no signature) updates to 0.11.0 by Velopack's GitHub source,
#                   as 0.10.0's launchers make it;
#   old-launcher    0.10.0's own launcher updates to 0.11.0 with --update.
#
#   tests/release/update_signed.sh BUILD_DIR LAST_RELEASE_DIR KEY_DIR OUT_DIR
#
# BUILD_DIR is client/packaging/windows/build.sh's OUT_DIR of a 0.11.0 test build made with OPENDMTQ_TEST_UPDATE_KEY (the
# public key in KEY_DIR/throwaway.pub), OPENDMTQ_UPDATE_SOURCE=http://192.168.248.10/kanggu12/openDMTQ and
# OPENDMTQ_PREVIOUS_RELEASE=the last release's full package (so that it has a delta package from 0.10.0). LAST_RELEASE_DIR
# holds the last release's files as published (0.10.0: OpenDMTQ-Setup.exe, its package and feed). KEY_DIR holds the test's
# key pair (throwaway.key, throwaway.pub: signing.py new-key). 0.11.1 is made here from the build: its launcher's files
# with one changed and one added, packed by vpk into the folder that holds 0.11.0's package, which makes its delta.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
BUILD=$(realpath -m "${1:?usage: update_signed.sh BUILD_DIR LAST_RELEASE_DIR KEY_DIR OUT_DIR}")
LAST=$(realpath -m "${2:?usage: update_signed.sh BUILD_DIR LAST_RELEASE_DIR KEY_DIR OUT_DIR}")
KEYS=$(realpath -m "${3:?usage: update_signed.sh BUILD_DIR LAST_RELEASE_DIR KEY_DIR OUT_DIR}")
OUT=$(realpath -m "${4:?usage: update_signed.sh BUILD_DIR LAST_RELEASE_DIR KEY_DIR OUT_DIR}")
# The updates worker's own names and addresses (no other test uses them).
NET=odq-w8d-net
SUBNET=192.168.248.0/24
STUB=odq-w8d-gh
STUB_IP=192.168.248.10
SERVER=odq-w8d-server
SERVER_IP=192.168.248.20
WINE=odq-w8d-wine
# The images: the PC client's build machine (Wine, a Windows Python with Velopack 1.2.161, the virtual screen), the UI test
# image's Python for the stand-in, vpk with zstd as build.sh makes it, the tools image for the tools' Python and this tree's
# server.
WINE_IMAGE=opendmtq-client-winbuild:local
PY_IMAGE=opendmtq-client-ui:local
VPK_IMAGE=opendmtq-client-vpk:local
TOOLS_IMAGE=opendmtq-tools:local
SERVER_IMAGE=opendmtq-server:w8d
fails=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; fails=$((fails + 1)); }
OLD=0.10.0
V=0.11.0
NEXT=0.11.1
PUBLIC=$(cat "$KEYS/throwaway.pub")

cleanup() {
  docker rm -f "$STUB" "$SERVER" "$WINE" >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT
cleanup
rm -rf "$OUT" && mkdir -p "$OUT/rel" "$OUT/gh" "$OUT/pack"

echo "== the releases: $V as built, $NEXT made from it, both signed with the test's key $PUBLIC"
python3 "$ROOT/tests/release/client_release.py" "$V" "$BUILD/releases" "$OUT/rel/v$V" "$KEYS/throwaway.key" || exit 1
# 0.11.1: the launcher's folder with a file changed (a patch in the delta) and one added, packed beside 0.11.0's package.
cp -r "$BUILD/dist/OpenDMTQ" "$OUT/pack/dist"
printf '\n%s\n' "$NEXT" >> "$OUT/pack/dist/licenses/NOTICES.txt"
printf '%s' "$NEXT" > "$OUT/pack/dist/update-test.txt"
# And its own version, as a release's build writes it (the launcher's --version reads it).
printf '%s' "$NEXT" > "$OUT/pack/dist/_internal/opendmtq_client/version.txt"
mkdir -p "$OUT/pack/releases"
cp "$BUILD/releases/OpenDMTQ.Client-$V-full.nupkg" "$OUT/pack/releases/"
docker run --rm --network none -v "$OUT/pack:/out" -v "$BUILD/assets:/assets:ro" "$VPK_IMAGE" vpk "[win]" pack \
  --packId OpenDMTQ.Client --packVersion "$NEXT" --packDir /out/dist --mainExe OpenDMTQ.exe --packTitle OpenDMTQ \
  --packAuthors OpenDMTQ --icon /assets/OpenDMTQ.ico --splashImage /assets/splash.png --outputDir /out/releases \
  > "$OUT/vpk-$NEXT.log" 2>&1 || { echo "vpk pack $NEXT failed"; tail -20 "$OUT/vpk-$NEXT.log"; exit 1; }
ls "$OUT/pack/releases/OpenDMTQ.Client-$NEXT-delta.nupkg" >/dev/null || { echo "vpk made no delta package"; exit 1; }
python3 "$ROOT/tests/release/client_release.py" "$NEXT" "$OUT/pack/releases" "$OUT/rel/v$NEXT" "$KEYS/throwaway.key" || exit 1
echo "  $NEXT: full $(stat -c %s "$OUT/rel/v$NEXT/opendmtq.client-$NEXT-full.nupkg") bytes, delta $(stat -c %s "$OUT/rel/v$NEXT/opendmtq.client-$NEXT-delta.nupkg") bytes"
# The project's own key has signed none of it: without the test's key nothing passes.
(cd "$ROOT/tools" && python3 -I opendmtq_tools/signing.py check "$OUT/rel/v$NEXT/opendmtq-$NEXT-sha256sums.txt" >/dev/null) \
  && fail "the made-up release passes for one the project signed" || pass "the made-up releases are signed by the test's key alone"

echo "== the network with no way out, a stand-in for GitHub, and the server of this tree"
docker network create --internal --subnet "$SUBNET" "$NET" >/dev/null
: > "$OUT/gh-requests.log"
docker run -d --name "$STUB" --network "$NET" --ip "$STUB_IP" -v "$OUT:/o" -v "$ROOT/tests/release:/t:ro" \
  --entrypoint python3 "$PY_IMAGE" /t/github_stub.py /o/gh 80 /o/gh-requests.log >/dev/null
docker build -q -t "$SERVER_IMAGE" "$ROOT/server" >/dev/null || { echo "the server image did not build"; exit 1; }
DATA=$OUT/server
mkdir -p "$DATA/content" "$DATA/state" "$DATA/custom" "$DATA/apk/out" "$DATA/apk/pc-client-updates"
chmod -R a+rwX "$DATA"
docker run --rm -u 33:33 --network none -v "$DATA/content:/content" -v "$ROOT/tests/ui:/ui:ro" --entrypoint php "$SERVER_IMAGE" \
  /ui/make_content.php /content >/dev/null
# The tools keep the update files of the installer's version (0.11.1 here) from data/apk, checked: the tools' own copy of
# the code takes the test's key besides the project's (update-test-keys.txt, as a test build's launcher does).
cp -r "$ROOT/tools" "$OUT/tools"
printf '%s\n' "$PUBLIC" > "$OUT/tools/opendmtq_tools/update-test-keys.txt"
cp "$OUT/rel/v$NEXT/releases.win.json" "$OUT/rel/v$NEXT"/opendmtq.client-"$NEXT"-*.nupkg \
  "$OUT/rel/v$NEXT/opendmtq-$NEXT-sha256sums.txt" "$OUT/rel/v$NEXT/opendmtq-$NEXT-sha256sums.txt.sig" "$DATA/apk/pc-client-updates/"
docker run --rm --network none -v "$OUT/tools:/t:ro" -v "$DATA/apk:/apk" -w /t --entrypoint python3 "$TOOLS_IMAGE" -c "
from opendmtq_tools import client_updates
made = client_updates.keep('/apk/out', version='$NEXT')
print('kept', made and made['version'], made and made['source'], made and made['delta_from'])
" > "$OUT/keep.log" 2>&1
cat "$OUT/keep.log"
grep -q "^kept $NEXT data/apk $V$" "$OUT/keep.log" && pass "the tools keep $NEXT's update files, checked, from data/apk" \
  || fail "the tools did not keep $NEXT's update files"
chmod -R a+rX "$DATA/apk"
# The files as the tools kept them, put back before each way.
cp -a "$DATA/apk/out" "$OUT/served"
# And 0.11.0's, kept the same way, for the way where the server hands out the version the launcher has.
mkdir -p "$OUT/apk-$V/out" "$OUT/apk-$V/pc-client-updates"
cp "$OUT/rel/v$V/releases.win.json" "$OUT/rel/v$V"/opendmtq.client-"$V"-*.nupkg "$OUT/rel/v$V/opendmtq-$V-sha256sums.txt" \
  "$OUT/rel/v$V/opendmtq-$V-sha256sums.txt.sig" "$OUT/apk-$V/pc-client-updates/"
docker run --rm --network none -v "$OUT/tools:/t:ro" -v "$OUT/apk-$V:/apk" -w /t --entrypoint python3 "$TOOLS_IMAGE" -c "
from opendmtq_tools import client_updates
made = client_updates.keep('/apk/out', version='$V')
print('kept', made and made['version'], made and made['source'], made and made['delta_from'])
" > "$OUT/keep-$V.log" 2>&1
grep -q "^kept $V data/apk $OLD$" "$OUT/keep-$V.log" && pass "the tools keep $V's update files too, with the delta from $OLD" \
  || fail "the tools did not keep $V's update files: $(cat "$OUT/keep-$V.log")"
chmod -R a+rX "$OUT/apk-$V"
cp -a "$OUT/apk-$V/out" "$OUT/served-$V"
docker run -d --name "$SERVER" --network "$NET" --ip "$SERVER_IP" -u 33:33 --read-only --tmpfs /var/opendmtq:mode=1777 \
  --tmpfs /tmp:mode=1777 -e PUBLIC_HOST="$SERVER_IP:8080" -e OPENDMTQ_VERSION="$NEXT" -e ADMIN_ON_PUBLIC_PORT=no \
  -v "$DATA/content:/srv/content:ro" -v "$DATA/state:/data" -v "$DATA/apk/out:/srv/apk:ro" -v "$DATA/custom:/srv/custom:ro" \
  "$SERVER_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$SERVER" curl -sf -m 3 -o /dev/null http://127.0.0.1:8080/opendmtq/health.php && break
  sleep 1
done
docker exec "$SERVER" curl -sf -m 3 -o /dev/null "http://127.0.0.1:8080/updates/releases.win.json" \
  && pass "the server hands out its feed at /updates/" || fail "the server hands out no feed"
docker exec "$SERVER" curl -s -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:8080/updates/updates.json" | grep -q 404 \
  && pass "and nothing it does not keep for its launchers (404)" || fail "the server hands out a file it does not keep for them"

# Before each way: the server's files as the tools kept them, then what the way changes. The folder itself stays: the
# running server holds it as its bind mount, and a folder made anew in its place would be another it never sees.
serve() {
  local kept=$OUT/served
  # The server of the version the launcher has: 0.11.0's files.
  [ "$1" = matched ] && kept=$OUT/served-$V
  find "$DATA/apk/out" -mindepth 1 -delete && cp -a "$kept/." "$DATA/apk/out/"
  local manifest=$DATA/apk/out/updates.json
  case $1 in
    no-delta)
      # The delta package not handed out: the feed still names it, and the launcher takes the whole package after it.
      python3 - "$manifest" "opendmtq.client-$NEXT-delta.nupkg" <<'PY'
import json, sys
made = json.load(open(sys.argv[1]))
del made["files"][sys.argv[2]]
json.dump(made, open(sys.argv[1], "w"))
PY
      rm -f "$DATA/apk/out/updates/opendmtq.client-$NEXT-delta.nupkg" ;;
    tampered)
      # A byte changed in the middle of the full package, its size the same: only its hash tells. No delta either.
      python3 - "$DATA/apk/out/updates/opendmtq.client-$NEXT-full.nupkg" <<'PY'
import sys
path = sys.argv[1]
data = bytearray(open(path, "rb").read())
data[len(data) // 2] ^= 0xFF
open(path, "wb").write(data)
PY
      serve_part no-delta ;;
    wrong-signature)
      # The checksums signed by another key (64 bytes still, so the server's size check passes).
      python3 - "$DATA/apk/out/updates/opendmtq-$NEXT-sha256sums.txt" "$ROOT/tools/opendmtq_tools/signing.py" <<'PY'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("signing", sys.argv[2])
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)
data = open(sys.argv[1], "rb").read()
open(sys.argv[1] + ".sig", "wb").write(signing.sign(os.urandom(32), data))
PY
      ;;
  esac
  chmod -R a+rX "$DATA/apk/out"
}
# The delta's removal alone, for a way that also changes something else (the files are already put back).
serve_part() {
  python3 - "$DATA/apk/out/updates.json" "opendmtq.client-$NEXT-delta.nupkg" <<'PY'
import json, sys
made = json.load(open(sys.argv[1]))
del made["files"][sys.argv[2]]
json.dump(made, open(sys.argv[1], "w"))
PY
  rm -f "$DATA/apk/out/updates/opendmtq.client-$NEXT-delta.nupkg"
}
# GitHub's releases for a way: the tags named, each as published.
releases() {
  rm -rf "$OUT/gh" && mkdir -p "$OUT/gh"
  local tag
  for tag in "$@"; do
    if [ "$tag" = "v$OLD" ]; then cp -r "$LAST" "$OUT/gh/$tag"; else cp -r "$OUT/rel/$tag" "$OUT/gh/$tag"; fi
  done
}

# The Wine side, once for each way: a new Wine prefix, the release given installed silently, then the update.
wine_run() {
  local way=$1 setup=$2
  docker rm -f "$WINE" >/dev/null 2>&1
  docker run --rm --name "$WINE" --network "$NET" -v "$OUT:/out" -v "$LAST:/last:ro" -e WINEDEBUG=-all -e WAY="$way" \
    -e SETUP="$setup" -e SERVER_URL="http://$SERVER_IP:8080" -e STUB_IP="$STUB_IP" --entrypoint bash "$WINE_IMAGE" -c '
  set -u
  Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &
  export DISPLAY=:99
  for i in $(seq 1 30); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.3; done
  LOCAL=$(winepath -u "C:\users\root\AppData\Local" 2>/dev/null)
  APP=$LOCAL/OpenDMTQ.Client
  installed() { grep -o "<version>[^<]*" "$APP/current/sq.version" 2>/dev/null | cut -c10-; }
  wait_for() { local i; for i in $(seq 1 "$1"); do [ "$(installed)" = "$2" ] && return 0; sleep 1; done; return 1; }
  # No way out: what the launcher reaches is on this network alone.
  curl -s -m 5 -o /dev/null https://github.com && echo "a way out" || echo "no way out"
  wine "$SETUP" --silent --no-start > /out/$WAY-setup.log 2>&1
  BEFORE=$(installed)
  echo "installed $BEFORE"
  CMD=$APP/current/OpenDMTQ-cmd.exe
  # The packages and Update.exe as installed, to compare after a refusal.
  ls "$APP/packages" > /out/$WAY-packages-before.txt
  sha256sum "$APP/Update.exe" | cut -d" " -f1 > /out/$WAY-updater-before.txt
  case $WAY in
    server-*|tampered|wrong-signature|matched)
      # The server PLAY plays on: added as a player adds it.
      wine "$CMD" --server "$SERVER_URL" > /out/$WAY-connect.log 2>&1 ;;
  esac
  case $WAY in
    old-github)
      # Velopack as 0.10.0 launchers make it: GithubSource(repository, no token, no prereleases), the installed app found by
      # its locator; check, download, then Update.exe applies it once this process has ended, and starts the launcher.
      cat > /tmp/update.py <<PY
import sys, velopack
app = sys.argv[1] + "\\\\OpenDMTQ.Client"
locator = velopack.VelopackLocatorConfig(app, app + "\\\\Update.exe", app + "\\\\packages", app + "\\\\current\\\\sq.version",
                                         app + "\\\\current", False)
manager = velopack.UpdateManager(velopack.GithubSource("http://192.168.248.10/kanggu12/openDMTQ", None, False), None, locator)
info = manager.check_for_updates()
print("offered", info.TargetFullRelease.Version if info else None, "deltas", [d.FileName for d in info.DeltasToTarget] if info else None)
manager.download_updates(info)
manager.wait_exit_then_apply_updates(info, True, True)
print("handed to Update.exe")
PY
      wine "C:\python\python.exe" "Z:\tmp\update.py" "C:\users\root\AppData\Local" > /out/$WAY-update.log 2>&1 ;;
    old-launcher)
      # The 0.10.0 launcher itself, its update address from the variable it reads first (a folder: the trailing slash keeps
      # the folder in the address Velopack joins the file names to).
      OPENDMTQ_UPDATE_SOURCE=http://$STUB_IP/feed/ wine "$CMD" --update --yes > /out/$WAY-update.log 2>&1 ;;
    *)
      wine "$CMD" --update --yes > /out/$WAY-update.log 2>&1 ;;
  esac
  echo "update exit $?"
  case $WAY in
    tampered|wrong-signature|matched)
      # Refused, or nothing newer: nothing changes, however long one waits.
      sleep 20; echo "now $(installed)" ;;
    old-*)
      wait_for 240 "0.11.0" && echo "updated $(installed)" || echo "not updated: $(installed)" ;;
    *)
      wait_for 240 "0.11.1" && echo "updated $(installed)" || echo "not updated: $(installed)" ;;
  esac
  sleep 5
  # The launcher as installed now, by its command line: the version it shows.
  wine "$CMD" --version > /out/$WAY-version.log 2>&1
  tr -d "\r" < /out/$WAY-version.log | tail -n 2
  echo "packages: $(ls "$APP/packages" | tr "\n" " ")"
  sha256sum "$APP/Update.exe" | cut -d" " -f1 > /out/$WAY-updater-after.txt
  mkdir -p /out/$WAY-logs
  cp "$LOCAL"/OpenDMTQ/client/logs/*.log /out/$WAY-logs/ 2>/dev/null
  cp "$LOCAL"/velopack/*.log /out/$WAY-logs/ 2>/dev/null
  wineserver -k 2>/dev/null
  chmod -R a+rwX /out' > "$OUT/$way.log" 2>&1
  sed "s/^/  $way: /" "$OUT/$way.log"
}
# What the server and the stand-in were asked during one way.
asked_server() { docker logs "$SERVER" 2>&1 | grep -o 'GET /updates/[^ ]*' | sed "s/^/  $1 server asked: /" | sort | uniq -c; }
server_got() { docker logs --since "$2" "$SERVER" 2>&1 | grep -q "GET /updates/$1 "; }
launcher_said() { tr -d '\r' < "$OUT/$1-update.log" | grep -qF "$2"; }
logged() { cat "$OUT/$1-logs"/launcher.log* 2>/dev/null | grep -qF "$2"; }

echo "== server-delta: $V through its server's feed, by the delta package"
serve as-kept; releases "v$NEXT"; : > "$OUT/gh-requests.log"; t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
wine_run server-delta "Z:\\out\\rel\\v$V\\opendmtq-pc-client-$V-windows-x64-setup.exe"
grep -q "^no way out$" "$OUT/server-delta.log" && pass "server-delta: the network has no way out" || fail "server-delta: the network has a way out"
grep -q "^installed $V$" "$OUT/server-delta.log" && pass "server-delta: $V installed by its own installer" || fail "server-delta: $V did not install"
launcher_said server-delta "OpenDMTQ $NEXT is available from" && pass "server-delta: the launcher names its server as where $NEXT comes from" \
  || fail "server-delta: the launcher did not find $NEXT on its server"
grep -q "^updated $NEXT$" "$OUT/server-delta.log" && pass "server-delta: updated to $NEXT" || fail "server-delta: not updated"
grep -q "OpenDMTQ $NEXT\|$NEXT" "$OUT/server-delta-version.log" && pass "server-delta: the new launcher runs and says $NEXT" \
  || fail "server-delta: the new launcher does not say $NEXT"
logged server-delta "put together from the delta package" && pass "server-delta: the package was put together from the delta package and checked" \
  || fail "server-delta: the launcher did not take the delta package"
server_got "opendmtq.client-$NEXT-delta.nupkg" "$t0" && ! server_got "opendmtq.client-$NEXT-full.nupkg" "$t0" \
  && pass "server-delta: the server handed out the delta package and not the full one" || fail "server-delta: the server handed out the full package"
[ ! -s "$OUT/gh-requests.log" ] && pass "server-delta: GitHub was never asked" || fail "server-delta: GitHub was asked: $(head -3 "$OUT/gh-requests.log")"
asked_server server-delta

echo "== server-full: the delta package not handed out, the whole one instead"
serve no-delta; t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
wine_run server-full "Z:\\out\\rel\\v$V\\opendmtq-pc-client-$V-windows-x64-setup.exe"
launcher_said server-full "The whole update is downloading." && pass "server-full: the launcher says the whole update comes" \
  || fail "server-full: the launcher did not turn to the whole package"
grep -q "^updated $NEXT$" "$OUT/server-full.log" && pass "server-full: updated to $NEXT" || fail "server-full: not updated"
server_got "opendmtq.client-$NEXT-full.nupkg" "$t0" && pass "server-full: the server handed out the full package" \
  || fail "server-full: the full package was not asked for"
logged server-full "is the package the release signed" && pass "server-full: the full package checked against the signed checksums" \
  || fail "server-full: the launcher did not say the package checked out"

echo "== matched: the server hands out $V, GitHub has $NEXT: the launcher stays with its server's version"
serve matched; releases "v$V" "v$NEXT"; : > "$OUT/gh-requests.log"
wine_run matched "Z:\\out\\rel\\v$V\\opendmtq-pc-client-$V-windows-x64-setup.exe"
launcher_said matched "This is the newest version for" && pass "matched: the newest version for its server, said so" \
  || fail "matched: the launcher did not say it is the newest for its server"
grep -q "^update exit 0$" "$OUT/matched.log" && pass "matched: --update ends with 0" || fail "matched: --update did not end with 0"
grep -q "^now $V$" "$OUT/matched.log" && pass "matched: still $V" || fail "matched: the version changed"
[ ! -s "$OUT/gh-requests.log" ] && pass "matched: GitHub was never asked" || fail "matched: GitHub was asked"

echo "== github: no server, the stand-in for GitHub's releases"
serve as-kept; releases "v$V" "v$NEXT"; : > "$OUT/gh-requests.log"
wine_run github "Z:\\out\\rel\\v$V\\opendmtq-pc-client-$V-windows-x64-setup.exe"
launcher_said github "OpenDMTQ $NEXT is available (this is $V)" && pass "github: $NEXT found on GitHub" || fail "github: $NEXT not found"
grep -q "^updated $NEXT$" "$OUT/github.log" && pass "github: updated to $NEXT" || fail "github: not updated"
grep -q "releases/download/v$NEXT/opendmtq-$NEXT-sha256sums.txt.sig" "$OUT/gh-requests.log" \
  && grep -q "releases/download/v$NEXT/opendmtq.client-$NEXT-delta.nupkg" "$OUT/gh-requests.log" \
  && pass "github: the checksums' signature and the delta package came by the tag" || fail "github: not fetched by the tag"
sed "s/^/  github asked: /" "$OUT/gh-requests.log" | sed 's/?.*//' | sort | uniq -c

echo "== tampered: the server hands out a full package with a byte changed"
serve tampered; t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
wine_run tampered "Z:\\out\\rel\\v$V\\opendmtq-pc-client-$V-windows-x64-setup.exe"
launcher_said tampered "The update to $NEXT from" && launcher_said tampered "is not signed by the OpenDMTQ project, so it was not installed." \
  && pass "tampered: refused in the window's words" || fail "tampered: not refused in words"
grep -q "^update exit 2$" "$OUT/tampered.log" && pass "tampered: --update ends with 2" || fail "tampered: --update did not end with 2"
grep -q "^now $V$" "$OUT/tampered.log" && pass "tampered: still $V" || fail "tampered: the version changed"
cmp -s "$OUT/tampered-packages-before.txt" <(grep -o "^packages: .*" "$OUT/tampered.log" | cut -c11- | tr ' ' '\n' | sed '/^$/d') \
  && pass "tampered: nothing new in packages\\" || fail "tampered: packages\\ changed: $(grep "^packages" "$OUT/tampered.log")"
cmp -s "$OUT/tampered-updater-before.txt" "$OUT/tampered-updater-after.txt" && pass "tampered: Update.exe as installed" \
  || fail "tampered: Update.exe changed"

echo "== wrong-signature: the server hands out checksums signed by another key"
serve wrong-signature; t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
wine_run wrong-signature "Z:\\out\\rel\\v$V\\opendmtq-pc-client-$V-windows-x64-setup.exe"
launcher_said wrong-signature "is not signed by the OpenDMTQ project, so the launcher does not install it." \
  && pass "wrong-signature: refused at the check, in the window's words" || fail "wrong-signature: not refused"
grep -q "^now $V$" "$OUT/wrong-signature.log" && pass "wrong-signature: still $V" || fail "wrong-signature: the version changed"
! server_got "opendmtq.client-$NEXT-full.nupkg" "$t0" && ! server_got "opendmtq.client-$NEXT-delta.nupkg" "$t0" \
  && pass "wrong-signature: no package asked for" || fail "wrong-signature: a package was asked for"

echo "== old-github and old-launcher: $OLD, which checks no signature, updates to $V"
serve as-kept
for way in old-github old-launcher; do
  releases "v$OLD" "v$V"; : > "$OUT/gh-requests.log"
  wine_run "$way" "Z:\\last\\OpenDMTQ-Setup.exe"
  grep -q "^installed $OLD$" "$OUT/$way.log" && pass "$way: $OLD installed by its own installer" || fail "$way: $OLD did not install"
  grep -q "^updated $V$" "$OUT/$way.log" && pass "$way: updated to $V" || fail "$way: not updated"
  grep -q "$V" "$OUT/$way-version.log" && pass "$way: the new launcher runs and says $V" || fail "$way: the new launcher does not say $V"
  grep -q "opendmtq.client-$V-delta.nupkg" "$OUT/gh-requests.log" && pass "$way: Velopack took the delta package from $OLD" \
    || echo "  note $way: Velopack did not ask for the delta package ($(grep -c nupkg "$OUT/gh-requests.log") package requests)"
  sed "s/^/  $way asked: /" "$OUT/gh-requests.log" | sed 's/?.*//' | grep -E "nupkg|json" | sort | uniq -c
  cp "$OUT/gh-requests.log" "$OUT/$way-requests.log"
done

echo "$fails failed"
[ "$fails" = 0 ]
