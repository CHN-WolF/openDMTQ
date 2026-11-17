#!/usr/bin/env bash
# Play on this PC under Wine: the Windows bundle with the PC client's installer in it (host/windows/build.sh after
# client/packaging/windows/build.sh, the installer copied to tools/opendmtq_tools/ first), as the owner uses it on the
# server PC, on a virtual screen and with no network:
#   1. the bundle runs; the owner signs in to the admin pages from this PC (loopback): the App page has Play on this PC
#   2. pressed: the installer the server keeps, set up for it with the owner's ID on its end, installs the PC client with
#      --silent, and the launcher opens; its guide's sign-in step has the owner's ID filled in, the password to type
#   3. the owner signs in there with the admin password
#   4. pressed again, the PC client installed: the launcher open already takes the server and comes to the front, and no
#      second launcher stays
#   5. the same through the API (POST /opendmtq/api/v1/app/play-here) with a token made on the Accounts page
#   6. the PC client's connection test (OpenDMTQ-cmd.exe --test-server) against this server, then against port 80 of the
#      same host as a launcher set up before 0.11.0 has it: nothing there, and the server found on 8791 (run with PORT=8791)
#   7. the PC client's report (OpenDMTQ-cmd.exe --report): its files, and none of the Windows user's name in its paths or
#      of the server's address in it
# Every step leaves a screenshot of the virtual screen and the pages' HTML in OUT_DIR.
#
#   tests/windows/play_here.sh BUNDLE_DIR OUT_DIR      (BUNDLE_DIR: host/windows/build.sh's OUT/OpenDMTQ)
#
# PORT (default 18741) is the server's one port inside the container; NAME_PREFIX names the container.
set -u
ROOT=$(cd "$(dirname "$0")/../.." && pwd)

# ------------------------------------------------------------------------------ outside: the Wine container

if [ -z "${IN_WINE:-}" ]; then
  BUNDLE=$(realpath -m "${1:?usage: play_here.sh BUNDLE_DIR OUT_DIR}")
  OUT=$(realpath -m "${2:?usage: play_here.sh BUNDLE_DIR OUT_DIR}")
  [ -f "$BUNDLE/OpenDMTQ.exe" ] || { echo "FAIL no bundle in $BUNDLE (run host/windows/build.sh)"; exit 1; }
  [ -f "$BUNDLE/app/tools/opendmtq_tools/OpenDMTQ-Setup.exe" ] \
    || { echo "FAIL the bundle has no installer for the PC client (copy it to tools/opendmtq_tools/ before its build)"; exit 1; }
  rm -rf "$OUT" && mkdir -p "$OUT"
  # The PC client's own test machine: Wine 11 with a virtual screen, xdotool and screenshots (client/tests/windows).
  docker image inspect opendmtq-client-e2e:local >/dev/null 2>&1 \
    || docker build -q -t opendmtq-client-e2e:local "$ROOT/client/tests/windows" >/dev/null
  exec docker run --rm --name "${NAME_PREFIX:-odq}-play-here" --network none -e IN_WINE=1 -e PORT="${PORT:-18741}" \
    -e WINEPREFIX=/tmp/wine -e WINEDEBUG=-all -e TZ=Asia/Seoul -v "$BUNDLE:/bundle:ro" -v "$OUT:/out" -v "$ROOT:/repo:ro" \
    opendmtq-client-e2e:local bash /repo/tests/windows/play_here.sh
fi

# ------------------------------------------------------------------------------ inside: the bundle and the PC client

failures=0
pass() { echo "PASS $*"; }
fail() { echo "FAIL $*"; failures=$((failures + 1)); }
expect() {
  local name=$1
  shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}
wait_for() { local _; for _ in $(seq 1 "$1"); do eval "$2" && return 0; sleep 1; done; return 1; }
step=0
snap() { step=$((step + 1)); import -window root "/out/$(printf %02d $step)-$1.png"; echo "screen $step: $1"; }
# The launcher's window by its title, and how many there are.
launchers() { xdotool search --name '^OpenDMTQ$' 2>/dev/null; }
# The guide's Next at the menu column's foot (248 wide at 96 dpi, Next 66 wide, 20 up from the window's foot).
next() {
  local id X=0 Y=0 HEIGHT=0
  id=$(launchers | tail -n 1)
  # No launcher: nothing to press (the checks after it say what is missing).
  [ -n "$id" ] || return 0
  eval "$(xdotool getwindowgeometry --shell "$id")"
  xdotool mousemove $((X + 196)) $((Y + HEIGHT - 38)) click 1
  sleep 3
}

# The virtual screen, then Wine set up on it.
Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
export DISPLAY=:99
for _ in $(seq 1 30); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.3; done
WINEDLLOVERRIDES="mscoree=;mshtml=" wineboot -i >/dev/null 2>&1
LOCAL=$(winepath -u 'C:\users\root\AppData\Local' 2>/dev/null)
TEMPDIR=$(winepath -u 'C:\users\root\AppData\Local\Temp' 2>/dev/null)
# The logs, whatever happens: a failure needs them most.
collect() {
  cp "$LOCAL"/OpenDMTQ/client/logs/launcher.log /out/ 2>/dev/null
  cp "$TEMPDIR"/OpenDMTQ-setup*.log /out/ 2>/dev/null
  cp "/tmp/Open DMTQ/data/state/logs/programs.log" /out/ 2>/dev/null
  chmod -R a+rwX /out
}
trap collect EXIT

# The bundle's copy with tests/windows/wine.sh's changes for Wine (its WMI module, which Wine cannot load, and Wine's
# own C runtime), in a folder with a space in its name. The C runtime the program's own folder has, else Wine's: the
# PC client's installer, which the server starts and which inherits this, has none of its own beside it for every part
# of it, and with Wine told to take none but a program's own it waits for ever before its first line.
cp -r /bundle "/tmp/Open DMTQ"
cd "/tmp/Open DMTQ" || exit 1
rm -f runtime/python/_wmi.pyd
sed -i '/runtime\/python\/_wmi\.pyd$/d' app/MANIFEST.sha256 2>/dev/null || true
export WINEDLLOVERRIDES="vcruntime140=n,b;vcruntime140_1=n,b"
PASSWORD=winetest
printf 'PUBLIC_HOST=127.0.0.1:%s\r\nLISTEN_PORT=%s\r\nADMIN_PASSWORD=%s\r\n' "$PORT" "$PORT" "$PASSWORD" > .env
(OPENDMTQ_START_WAIT=5 timeout 1800 wine OpenDMTQ.exe 2>&1 | cat > /out/server.log &)
A="http://127.0.0.1:$PORT/opendmtq/admin"
wait_for 300 "[ \"\$(curl -s -o /dev/null -w '%{http_code}' -m 10 $A/login)\" = 200 ]" \
  || { tail -n 30 /out/server.log; fail "the bundle's admin pages answer"; exit 1; }
pass "the bundle runs, its admin pages answer on the server's one port"

# 1. The owner, signed in from this PC, on the App page.
jar=/tmp/admin.cookies
web() { curl -s -m 120 -c "$jar" -b "$jar" "$@"; }
token() { grep -o 'name="csrf" value="[^"]*"' | head -n 1 | cut -d'"' -f4; }
web -o /dev/null "$A/login"
web -o /dev/null --data-urlencode name=admin --data-urlencode "password=$PASSWORD" "$A/login"
web "$A/app" > /out/app-1.html
expect "the App page, from this PC, has Play on this PC" grep -q 'id="this-pc"' /out/app-1.html
expect "it installs the PC client with the owner's ID filled in" grep -q 'opens it with your ID (admin) filled in' /out/app-1.html
expect "and its button" grep -q '>Play on this PC</button>' /out/app-1.html

# 2. Pressed: the installer, then the launcher. The install takes longer than a form waits: the page follows its job.
csrf=$(token < /out/app-1.html)
where=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$csrf" --data-urlencode back=app "$A/app/play-here")
echo "the press went to $where"
job=$(echo "$where" | sed -n 's/.*here=\([0-9a-f]*\).*/\1/p')
if [ -n "$job" ]; then
  web "$where" > /out/app-2-following.html
  expect "the page follows the install in its log box" grep -q 'id="here-log"' /out/app-2-following.html
  wait_for 420 "! web $A/jobs/$job | grep -Eq '\"state\": ?\"running\"'"
  web "$A/jobs/$job" > /out/job-1.json
fi
web "${where:-$A/app}" > /out/app-3-after.html
expect "the page says the PC client is installed" grep -q 'Installed the PC client. Its launcher opens with this server and your ID (admin) filled in.' /out/app-3-after.html
expect "the PC client is installed for this Windows user" test -f "$LOCAL/OpenDMTQ.Client/OpenDMTQ.exe"
echo "installed: $(grep -o '<version>[^<]*' "$LOCAL/OpenDMTQ.Client/current/sq.version" 2>/dev/null | cut -c10-)"
expect "the copy it ran is gone" sh -c "! ls -d '$TEMPDIR'/opendmtq-play-here-* >/dev/null 2>&1"
wait_for 120 '[ -n "$(launchers)" ]' || snap no-launcher
expect "the launcher opens" test -n "$(launchers)"
sleep 8
snap guide-welcome
settings="$LOCAL/OpenDMTQ/client/settings.json"
expect "it plays on this server" grep -q "\"url\": \"http://127.0.0.1:$PORT\"" "$settings"
expect "with the owner's ID to sign in with, no sign-in said to have ended" sh -c "grep -q '\"fill\": \"admin\"' '$settings' && grep -q '\"account\": null' '$settings'"
expect "and took what the installer left for it" test ! -f "$LOCAL/OpenDMTQ/client/preset.json"
# The guide: its server step (the server answers by itself), then the sign-in with the ID filled in.
next
snap guide-server
next
snap guide-login
grep "the installer brought the ID admin" "$LOCAL/OpenDMTQ/client/logs/launcher.log" >/dev/null \
  && pass "the launcher's log says the installer brought the ID" || fail "the launcher's log says the installer brought the ID"

# 3. The password, typed where the keyboard is (the password field: the ID is there already), and Enter.
xdotool windowfocus --sync "$(launchers | tail -n 1)" 2>/dev/null
xdotool type --delay 40 "$PASSWORD"
xdotool key Return
wait_for 30 "grep -q '\"account\": \"admin\"' '$settings'"
snap guide-signed-in
expect "the owner signs in with the admin password, and the ID filled in has done its part" \
  sh -c "grep -q '\"account\": \"admin\"' '$settings' && grep -q '\"fill\": null' '$settings'"

# 4. Pressed again, the PC client installed and its launcher open: it takes the server, comes to the front, and stays one.
web "$A/app" > /out/app-4-installed.html
expect "installed, the App page says so" grep -q 'is installed on this PC. It opens set up for this server' /out/app-4-installed.html
csrf=$(token < /out/app-4-installed.html)
where=$(web -o /dev/null -w '%{redirect_url}' --data-urlencode "csrf=$csrf" --data-urlencode back=app "$A/app/play-here")
web "${where:-$A/app}" > /out/app-5-opened.html
expect "the page says the launcher opens" grep -q 'The launcher opens with this server and your ID (admin) filled in.' /out/app-5-opened.html
wait_for 20 "[ ! -f '$LOCAL/OpenDMTQ/client/preset.json' ]"
expect "the launcher open already took the server" test ! -f "$LOCAL/OpenDMTQ/client/preset.json"
sleep 6
expect "one launcher window, not two" test "$(launchers | wc -l)" = 1
snap opened-again

# 5. The API, with a write token made as the owner makes one on the Accounts page.
csrf=$(web "$A/accounts" | token)
# The page after it shows the token once: the redirect followed.
web -L "$A/accounts" -o /out/accounts.html --data-urlencode "csrf=$csrf" --data-urlencode action=token \
  --data-urlencode "token_name=play here" --data-urlencode scope=write
secret=$(grep -o 'odq_[0-9a-f]\{12\}_[A-Za-z0-9_-]\{43\}' /out/accounts.html | head -n 1)
status=$(curl -s -m 60 -H "Authorization: Bearer $secret" -X POST -o /out/api-play-here.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/opendmtq/api/v1/app/play-here")
expect "the API's POST /app/play-here answers 202 ($status) with its job" \
  sh -c "test '$status' = 202 && grep -Eq '\"kind\": ?\"pc-client\"' /out/api-play-here.json"

# 6. The connection test from the PC client the press installed, against this server: each step's line as it ends, the
# exit code 1 exactly when a step failed (this server has no game files: its game server says so).
cmd="$LOCAL/OpenDMTQ.Client/current/OpenDMTQ-cmd.exe"
wine "$cmd" --test-server > /out/test-server.txt 2>&1
code=$?
cat /out/test-server.txt
for step in Address "Name lookup" Port "OpenDMTQ server" Version Sign-in; do
  expect "--test-server: $step through" grep -q "^  \[ok  \] $step: " /out/test-server.txt
done
expect "--test-server: the game server, the broadcasts, the downloads and the round trip each said" \
  sh -c "for s in 'Game server' Broadcasts Downloads 'Round trip'; do grep -q \"^  \\[[a-z ]*\\] \$s: \" /out/test-server.txt || exit 1; done"
expect "--test-server: exit $code, 1 exactly when a step failed" \
  sh -c "if grep -q '^  \[fail\]' /out/test-server.txt; then test $code = 1; else test $code = 0; fi"
if [ "$PORT" = 8791 ]; then
  # A launcher set up for port 80, before 0.11.0: nothing answers there, and the test finds the server on 8791.
  wine "$cmd" --test-server http://127.0.0.1:80 > /out/test-server-80.txt 2>&1
  code=$?
  cat /out/test-server-80.txt
  expect "--test-server on port 80 finds the server on 8791 ($code)" sh -c "test $code = 1 && grep -q \
    'refuses the connection on port 80. An OpenDMTQ server answers at http://127.0.0.1:8791.' /out/test-server-80.txt"
fi

# 7. The report from the PC client under Wine: one zip with its files, read back by the bundle's own Python; the user's
# name (root, in every path of Wine's user) and the server's address left out.
wine "$cmd" --report 'Z:\out\report.zip' > /out/report.txt 2>&1
code=$?
cat /out/report.txt
expect "--report writes one zip ($code)" sh -c "test $code = 0 && test -s /out/report.zip"
cat > /out/read-report.py <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
for name in z.namelist():
    print(name)
text = "".join(z.read(name).decode("utf-8", "replace") for name in z.namelist()).lower()
print("LEAK" if ("\\users\\root" in text or "127.0.0.1:" + sys.argv[2] in text) else "CLEAN")
PY
wine "/tmp/Open DMTQ/runtime/python/python.exe" -I 'Z:\out\read-report.py' 'Z:\out\report.zip' "$PORT" > /out/report-list.txt 2>&1
cat /out/report-list.txt
# The player's settings file is written when the launcher starts the game, which this run never does: not asked for.
for name in about.txt launcher/launcher.log settings/settings.json system/displays.txt system/sound.txt system/connection-test.txt; do
  expect "the report has $name" grep -q "^$name" /out/report-list.txt
done
expect "and none of the user's name in its paths, nor the server's address" grep -q '^CLEAN' /out/report-list.txt

echo "play here under Wine: $failures failed"
[ "$failures" -eq 0 ]
