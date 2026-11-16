#!/bin/bash
# An installed PC client of the last release updating itself to this release's files, under Wine, from a stand-in for
# GitHub's releases (tests/release/github_stub.py) that holds both releases' files as they are published:
#   1. Velopack's GitHub source, as the installed launchers make it (client/opendmtq_client/updates.py: GithubSource with
#      the repository's address), reads the releases' list, the update feed of each release and the package the newest
#      feed names, and Update.exe puts the new version in. The stand-in answers on GitHub Enterprise's /api/v3, which the
#      same source asks of a host that is not github.com: github.com itself takes TLS the test cannot stand in for.
#   2. The last release's own launcher, OpenDMTQ-cmd.exe --update --yes, from the new release's files as one folder
#      (Velopack's HTTP source, which reads the same two names): it downloads, restarts, and the new launcher runs.
#   3. This release's servers: the tools' fetch of the runtime for newer phones and of the installer, from the latest
#      tag by their new names (tools/opendmtq_tools/runtime.py, windows_client.py).
#
#   tests/release/update.sh OLD_RELEASE_DIR NEW_RELEASE_DIR OUT_DIR
#
# OLD_RELEASE_DIR holds the last release's files (its OpenDMTQ-Setup.exe, releases.win.json and package), NEW_RELEASE_DIR
# this release's as .github/release_assets.py lays them out. Everything runs on a Docker network with no way out.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OLD=$(realpath -m "${1:?usage: update.sh OLD_RELEASE_DIR NEW_RELEASE_DIR OUT_DIR}")
NEW=$(realpath -m "${2:?usage: update.sh OLD_RELEASE_DIR NEW_RELEASE_DIR OUT_DIR}")
OUT=$(realpath -m "${3:?usage: update.sh OLD_RELEASE_DIR NEW_RELEASE_DIR OUT_DIR}")
# The release worker's own names and addresses (no other test uses them).
NET=odq-w4r-net
STUB=odq-w4r-gh
STUB_IP=192.168.244.10
# The images: the PC client's build machine (Wine, a Windows Python with Velopack 1.2.161, the virtual screen) and the
# UI test image's Python for the stand-in.
WINE_IMAGE=opendmtq-client-winbuild:local
PY_IMAGE=opendmtq-client-ui:local
fails=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; fails=$((fails + 1)); }

OLD_VERSION=$(cat "$OLD/OpenDMTQ-Setup.exe.version" 2>/dev/null || true)
NEW_VERSION=$(sed -n 's/.*"Version":"\([^"]*\)".*/\1/p' "$NEW/releases.win.json")
# The package by the name the new feed gives it (the release's, in lower case).
PACKAGE=$(sed -n 's/.*"FileName":"\([^"]*\)".*/\1/p' "$NEW/releases.win.json")
[ -n "$OLD_VERSION" ] && [ -n "$NEW_VERSION" ] || { echo "no versions in $OLD and $NEW" >&2; exit 1; }
echo "from $OLD_VERSION to $NEW_VERSION, the package as $PACKAGE"
# The release's name for it, in lower case (.github/release_assets.py): vpk's own name has the id's capitals.
[ "$PACKAGE" = "$(printf '%s' "$PACKAGE" | tr '[:upper:]' '[:lower:]')" ] && pass "the new feed names its package in lower case" \
  || fail "the new feed names its package with capitals ($PACKAGE)"

# ---- the stand-in: both releases as tag folders, the old one as published (its own names), the new one as laid out
rm -rf "$OUT" && mkdir -p "$OUT/rel/v$OLD_VERSION" "$OUT/rel/v$NEW_VERSION"
cp "$OLD"/* "$OUT/rel/v$OLD_VERSION/"
cp "$NEW"/* "$OUT/rel/v$NEW_VERSION/"
: > "$OUT/requests.log"
docker rm -f "$STUB" >/dev/null 2>&1
docker network rm "$NET" >/dev/null 2>&1
docker network create --internal --subnet 192.168.244.0/24 "$NET" >/dev/null
docker run -d --name "$STUB" --network "$NET" --ip "$STUB_IP" -v "$OUT:/o" -v "$ROOT/tests/release:/t:ro" \
  --entrypoint python3 "$PY_IMAGE" /t/github_stub.py /o/rel 80 /o/requests.log >/dev/null
cleanup() { docker rm -f "$STUB" >/dev/null 2>&1; docker network rm "$NET" >/dev/null 2>&1; }
trap cleanup EXIT

# The Wine side, run once for each way: install the old release silently, then the update named by $1.
wine_run() {
  docker run --rm --network "$NET" -v "$OUT:/out" -v "$OLD:/old:ro" -e WINEDEBUG=-all -e WAY="$1" -e NEW_VERSION="$NEW_VERSION" \
    --entrypoint bash "$WINE_IMAGE" -c '
  set -u
  Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/dev/null 2>&1 &
  export DISPLAY=:99
  for i in $(seq 1 30); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.3; done
  LOCAL=$(winepath -u "C:\users\root\AppData\Local" 2>/dev/null)
  installed() { grep -o "<version>[^<]*" "$LOCAL/OpenDMTQ.Client/current/sq.version" 2>/dev/null | cut -c10-; }
  wait_for() { local i; for i in $(seq 1 "$1"); do [ "$(installed)" = "$2" ] && return 0; sleep 1; done; return 1; }
  wine "Z:\old\OpenDMTQ-Setup.exe" --silent --no-start > /out/$WAY-setup.log 2>&1
  echo "installed $(installed)"
  case $WAY in
    github)
      # Velopack as 0.10.0 launchers make it: GithubSource(repository, no token, no prereleases), the installed app found
      # by its locator; check, download, then Update.exe applies it once this process has ended, and starts the launcher.
      cat > /tmp/update.py <<PY
import sys, velopack
local = sys.argv[1]
app = local + "\\\\OpenDMTQ.Client"
locator = velopack.VelopackLocatorConfig(app, app + "\\\\Update.exe", app + "\\\\packages", app + "\\\\current\\\\sq.version",
                                         app + "\\\\current", False)
manager = velopack.UpdateManager(velopack.GithubSource("http://192.168.244.10/kanggu12/openDMTQ", None, False), None, locator)
print("current", manager.get_current_version())
info = manager.check_for_updates()
print("offered", info.TargetFullRelease.Version if info else None, info.TargetFullRelease.FileName if info else None)
manager.download_updates(info)
manager.wait_exit_then_apply_updates(info, True, True)
print("handed to Update.exe")
PY
      wine "C:\python\python.exe" "Z:\tmp\update.py" "C:\users\root\AppData\Local" > /out/$WAY-update.log 2>&1 ;;
    launcher)
      # The 0.10.0 launcher itself, its update address from the variable it reads first (a folder: the trailing slash
      # keeps the folder in the address Velopack joins the file names to).
      OPENDMTQ_UPDATE_SOURCE=http://192.168.244.10/feed/ wine "$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe" --update --yes \
        > /out/$WAY-update.log 2>&1 ;;
  esac
  wait_for 180 "$NEW_VERSION" && echo "updated $(installed)" || echo "not updated: $(installed)"
  # The new launcher as installed, by its command line: the version it shows.
  sleep 5
  wine "$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe" --version > /out/$WAY-version.log 2>&1
  tr -d "\r" < /out/$WAY-version.log | tail -n 3
  # The packages the update left, by name: the release'"'"'s, as its feed names it.
  echo "packages: $(ls "$LOCAL/OpenDMTQ.Client/packages" | tr "\n" " ")"
  # Repair from that package: a file of the program gone, put back from it (the launcher finds the package in any case).
  wineserver -k 2>/dev/null
  rm -f "$LOCAL/OpenDMTQ.Client/current/licenses/NOTICES.txt"
  wine "$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe" --repair > /out/$WAY-repair.log 2>&1
  tr -d "\r" < /out/$WAY-repair.log | tail -n 3
  [ -f "$LOCAL/OpenDMTQ.Client/current/licenses/NOTICES.txt" ] && echo "repaired: NOTICES.txt back" || echo "not repaired"
  cp "$LOCAL"/velopack/*.log /out/ 2>/dev/null
  wineserver -k 2>/dev/null
  chmod -R a+rwX /out' > "$OUT/$1.log" 2>&1
  cat "$OUT/$1.log"
}

for way in github launcher; do
  : > "$OUT/requests.log"
  wine_run "$way"
  grep -q "^installed $OLD_VERSION$" "$OUT/$way.log" && pass "$way: $OLD_VERSION installed by its own installer" \
    || fail "$way: $OLD_VERSION did not install"
  grep -q "^updated $NEW_VERSION$" "$OUT/$way.log" && pass "$way: updated to $NEW_VERSION" || fail "$way: not updated"
  grep -q "$NEW_VERSION" "$OUT/$way-version.log" && pass "$way: the new launcher runs and says $NEW_VERSION" \
    || fail "$way: the new launcher does not say $NEW_VERSION"
  # What was asked for: the feed by its name and the package by the name the feed gives, in lower case exactly.
  grep -E "releases.win.json|nupkg|/releases" "$OUT/requests.log" | sed 's/?.*//' | sort | uniq -c | sed "s/^/  $way asked: /"
  grep -q "/$PACKAGE\( \|?\|$\)" "$OUT/requests.log" && pass "$way: the package came by the feed's name ($PACKAGE)" \
    || fail "$way: the package was not downloaded by the feed's name ($PACKAGE)"
  grep -q "^packages: .*$PACKAGE" "$OUT/$way.log" && pass "$way: the update keeps the package under that name" \
    || fail "$way: the update did not keep $PACKAGE"
  grep -q "^repaired: NOTICES.txt back$" "$OUT/$way.log" && pass "$way: repair puts a file back from the updated package" \
    || fail "$way: repair did not put the file back"
  cp "$OUT/requests.log" "$OUT/$way-requests.log"
done

# ---- 3. this release's servers fetching from it: the tools' own code, its releases' address pointed at the stand-in
: > "$OUT/requests.log"
docker run --rm --network "$NET" -v "$ROOT/tools:/t:ro" -v "$OUT:/out" -w /t --entrypoint python3 "$PY_IMAGE" -c "
import os, tempfile
from opendmtq_tools import runtime, windows_client
runtime.RELEASES = windows_client.RELEASES = 'http://$STUB_IP/kanggu12/openDMTQ/releases'
runtime.HERE = windows_client.HERE = '/nowhere'
apk = tempfile.mkdtemp()
runtime.add_runtime(apk)
print('runtime', runtime.version_in_place(os.path.join(apk, 'arm32')))
print('installer', windows_client.find(apk))
" > "$OUT/servers.log" 2>&1
cat "$OUT/servers.log"
grep -q "^runtime v$NEW_VERSION" "$OUT/servers.log" && pass "a server takes the runtime from the latest release" \
  || fail "a server did not take the runtime"
grep -q "^installer (.*OpenDMTQ-Setup.exe', '$NEW_VERSION')" "$OUT/servers.log" \
  && pass "a server takes the installer from the latest release, with its version" || fail "a server did not take the installer"
sed 's/^/  servers asked: /' "$OUT/requests.log"
cp "$OUT/requests.log" "$OUT/servers-requests.log"

echo "$fails failed"
[ "$fails" = 0 ]
