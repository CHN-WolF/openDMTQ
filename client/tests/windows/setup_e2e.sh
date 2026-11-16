#!/bin/bash
# The installer from end to end under Wine, as a person uses it, with no server and no game:
#   1. OpenDMTQ-Setup.exe on a PC without OpenDMTQ: its Install page, Enter, the progress, the end page; Windows' entry
#      opens OpenDMTQ's own uninstall (UninstallString) and Velopack's quiet one stays (QuietUninstallString); both
#      shortcuts made; Enter on the end page's Open OpenDMTQ starts the launcher
#   2. OpenDMTQ-Setup.exe again, the launcher open: what to do with it; Repair puts back a file of the program that went,
#      the launcher closed for it
#   3. OpenDMTQ-Setup.exe again: Uninstall, keeping the data: the program, both shortcuts, Windows' entry and OpenDMTQ's
#      logs elsewhere gone, the data kept
#   4. installed again with --silent; Windows' quiet uninstall (QuietUninstallString, as a tool runs it): nothing on
#      screen, the program gone, the data kept
#   5. installed again with --silent; Windows' Settings, Apps' Uninstall (UninstallString): the same uninstall page from a
#      copy of the launcher outside the program's folder; Delete everything: nothing of OpenDMTQ's left on the PC (its
#      folders, its shortcuts, its entry, its logs, the copy itself)
# Every step leaves a screenshot of the virtual screen in OUT_DIR, and the installer's logs.
#
#   client/tests/windows/setup_e2e.sh BUILD_DIR OUT_DIR
#
# BUILD_DIR is client/packaging/windows/build.sh's OUT_DIR. The container has no network; E2E_NAME names it (else
# odq-setup-e2e-<pid>).
set -u
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
BUILD=$(realpath -m "${1:?usage: setup_e2e.sh BUILD_DIR OUT_DIR}")
OUT=$(realpath -m "${2:?usage: setup_e2e.sh BUILD_DIR OUT_DIR}")
[ -f "$BUILD/releases/OpenDMTQ-Setup.exe" ] || { echo "no $BUILD/releases/OpenDMTQ-Setup.exe: run build.sh first" >&2; exit 1; }
rm -rf "$OUT" && mkdir -p "$OUT"
# The test machine: Wine with xdotool and screenshots, as e2e.sh's (built once).
docker image inspect opendmtq-arm32-wine >/dev/null 2>&1 \
  || docker build -q -t opendmtq-arm32-wine -f "$ROOT/arm32/wine.Dockerfile" "$ROOT/arm32" >/dev/null
docker image inspect opendmtq-client-e2e:local >/dev/null 2>&1 \
  || docker build -q -t opendmtq-client-e2e:local "$ROOT/client/tests/windows" >/dev/null
docker run --rm --name "${E2E_NAME:-odq-setup-e2e-$$}" --network none -v "$BUILD/releases:/rel:ro" -v "$OUT:/out" -w /out \
  -e WINEPREFIX=/tmp/wine -e WINEDEBUG=-all -e TZ=Asia/Seoul opendmtq-client-e2e:local bash -c '
  set -u
  Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp >/dev/null 2>&1 &
  export DISPLAY=:99
  for i in $(seq 1 30); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.3; done
  WINEDLLOVERRIDES="mscoree=;mshtml=" wineboot -i >/dev/null 2>&1
  LOCAL=$(winepath -u "C:\\users\\root\\AppData\\Local" 2>/dev/null)
  TEMPDIR=$(winepath -u "C:\\users\\root\\AppData\\Local\\Temp" 2>/dev/null)
  PROGRAM="$LOCAL/OpenDMTQ.Client"
  DATA="$LOCAL/OpenDMTQ"
  KEY="HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\OpenDMTQ.Client"
  cp /rel/OpenDMTQ-Setup.exe /tmp/OpenDMTQ-Setup.exe
  step=0
  snap() { step=$((step + 1)); import -window root "/out/$(printf %02d $step)-$1.png"; echo "screen $step: $1"; }
  wait_for() { local i; for i in $(seq 1 $1); do eval "$2" && return 0; sleep 1; done; return 1; }
  # The installer'"'"'s window by its title, the keys a person presses on it.
  setup_window() { xdotool search --name "^OpenDMTQ Setup\$" 2>/dev/null | tail -n 1; }
  launcher_window() { xdotool search --name "^OpenDMTQ\$" 2>/dev/null | tail -n 1; }
  press() { xdotool windowfocus --sync "$(setup_window)" 2>/dev/null; sleep 0.3; xdotool key "$@"; }
  # One of the entry'"'"'s values as Windows keeps it, and the entry itself.
  entry() { wine reg query "$KEY" /v "$1" 2>/dev/null | tr -d "\r" | sed -n "s/.*REG_SZ *//p"; }
  has_entry() { wine reg query "$KEY" >/dev/null 2>&1; }
  shortcuts() { find /tmp/wine/drive_c -iname "OpenDMTQ*.lnk" 2>/dev/null; }
  # A command line from the entry run as Windows runs it: the quoted program, then its arguments.
  run_entry() { local line; line=$(entry "$1" | sed "s/\\\\/\\\\\\\\/g"); eval "set -- $line"; wine "$@" > "/out/entry-$2.log" 2>&1 & }
  # How many times the installer has said its setup ended well (its log, kept in the temporary folder).
  setups_done() { cat "$TEMPDIR"/OpenDMTQ-setup.log* 2>/dev/null | grep -c "Velopack.s setup ended with 0"; }
  # The data a player has after playing: the launcher'"'"'s settings and a game'"'"'s folder with its id.
  make_data() {
    mkdir -p "$DATA/client" "$DATA/com.example.game/data"
    printf "{\"version\": 1, \"language\": \"en\", \"guide_done\": true}" > "$DATA/client/settings.json"
    echo 0123456789abcdef > "$DATA/com.example.game/data/android_id"
    head -c 3000000 /dev/zero > "$DATA/com.example.game/data/songs.bin"
  }
  # Whatever of OpenDMTQ'"'"'s is still on the PC (its folders, its logs, its shortcuts, the uninstall'"'"'s copy).
  leftovers() {
    { find "$LOCAL" "$TEMPDIR" -maxdepth 1 -iname "*opendmtq*" 2>/dev/null
      ls "$LOCAL"/velopack/velopack_OpenDMTQ* 2>/dev/null; shortcuts; } | sort
  }
  collect() { cp "$TEMPDIR"/OpenDMTQ-setup*.log /out/ 2>/dev/null; cp "$LOCAL"/velopack/*.log /out/ 2>/dev/null; chmod -R a+rwX /out; }
  trap collect EXIT

  # ---- 1. install through the window: Enter on Install, the end page.
  wine /tmp/OpenDMTQ-Setup.exe > /out/setup-1.log 2>&1 &
  wait_for 120 "[ -n \"\$(setup_window)\" ]" || { snap no-window; echo "FAIL: no installer window"; exit 1; }
  sleep 4; snap install-page
  press Return
  sleep 1.5; snap installing
  wait_for 240 "[ \"\$(setups_done)\" -ge 1 ]" || { snap install-stuck; echo "FAIL: the install did not end"; exit 1; }
  sleep 3; snap install-done
  echo "installed: $(grep -o "<version>[^<]*" "$PROGRAM/current/sq.version" | cut -c10-)"
  un=$(entry UninstallString); quiet=$(entry QuietUninstallString)
  echo "UninstallString: $un"; echo "QuietUninstallString: $quiet"
  echo "$un" | grep -q "current\\\\OpenDMTQ.exe\" --uninstall-window\$" || { echo "FAIL: the entry does not open OpenDMTQ'"'"'s own uninstall"; exit 1; }
  echo "$quiet" | grep -q "Update.exe\" --uninstall --silent\$" || { echo "FAIL: the quiet entry is not Velopack'"'"'s silent one"; exit 1; }
  [ "$(shortcuts | wc -l)" = 2 ] || { echo "FAIL: shortcuts: $(shortcuts)"; exit 1; }
  # Enter on the end page: Open OpenDMTQ starts the launcher, and the installer closes.
  press Return
  wait_for 60 "[ -n \"\$(launcher_window)\" ]" || { snap no-launcher; echo "FAIL: Open OpenDMTQ did not start the launcher"; exit 1; }
  wait_for 20 "[ -z \"\$(setup_window)\" ]" || { snap install-stays; echo "FAIL: the installer stayed after Open OpenDMTQ"; exit 1; }
  sleep 6; snap launcher-opened
  echo "1. installed through the window: the entry opens OpenDMTQ'"'"'s uninstall, both shortcuts made, Open OpenDMTQ started the launcher"

  # ---- 2. Repair through the window: a file of the program back as it came.
  damaged="$(cd "$PROGRAM/current" && find _internal -name "*.ttf" | head -n 1)"
  sum=$(cd "$PROGRAM/current" && md5sum "$damaged")
  rm "$PROGRAM/current/$damaged"
  wine /tmp/OpenDMTQ-Setup.exe > /out/setup-2.log 2>&1 &
  wait_for 120 "[ -n \"\$(setup_window)\" ]" || { echo "FAIL: no installer window for the repair"; exit 1; }
  sleep 4; snap choose
  press Down; sleep 1; snap choose-repair
  press Return
  wait_for 240 "[ \"\$(setups_done)\" -ge 2 ]" || { snap repair-stuck; echo "FAIL: the repair did not end"; exit 1; }
  sleep 3; snap repaired
  (cd "$PROGRAM/current" && echo "$sum" | md5sum -c --quiet) || { echo "FAIL: the repair did not put the file back"; exit 1; }
  # The launcher that was open was closed for it (Velopack ends what runs from the program'"'"'s folder).
  [ -z "$(launcher_window)" ] || { echo "FAIL: the launcher stayed open through the repair"; exit 1; }
  press Escape
  wait_for 20 "[ -z \"\$(setup_window)\" ]" || { echo "FAIL: Esc did not close the repair'"'"'s end page"; exit 1; }
  echo "2. repaired through the window: $damaged back as installed"

  # ---- 3. Uninstall through the window, keeping the data.
  make_data
  wine /tmp/OpenDMTQ-Setup.exe > /out/setup-3.log 2>&1 &
  wait_for 120 "[ -n \"\$(setup_window)\" ]" || { echo "FAIL: no installer window for the uninstall"; exit 1; }
  sleep 4; press Down Down; sleep 1; snap choose-uninstall
  press Return; sleep 3; snap uninstall-page
  # Keep my data is chosen at first: Enter on the choices uninstalls.
  press Return
  sleep 1; snap uninstalling
  wait_for 120 "[ ! -e \"\$PROGRAM/current\" ]" || { snap uninstall-stuck; echo "FAIL: the program stayed"; exit 1; }
  wait_for 60 "[ ! -e \"\$PROGRAM\" ]" || { echo "FAIL: the program folder stayed: $(ls "$PROGRAM")"; exit 1; }
  sleep 3; snap uninstalled-keep
  has_entry && { echo "FAIL: Windows'"'"' entry stayed"; exit 1; }
  [ -z "$(shortcuts)" ] || { echo "FAIL: shortcuts stayed: $(shortcuts)"; exit 1; }
  [ -f "$DATA/com.example.game/data/android_id" ] && [ -f "$DATA/client/settings.json" ] || { echo "FAIL: the data did not stay"; exit 1; }
  left=$(leftovers | grep -v "^$DATA\$")
  [ -z "$left" ] || { echo "FAIL: left after the uninstall that keeps the data: $left"; exit 1; }
  press Escape
  wait_for 20 "[ -z \"\$(setup_window)\" ]" || { echo "FAIL: Esc did not close the uninstall'"'"'s end page"; exit 1; }
  echo "3. uninstalled through the window, the data kept: nothing else of OpenDMTQ'"'"'s left"

  # ---- 4. installed again quietly; Windows'"'"' quiet uninstall: nothing on screen, the data kept.
  wine /tmp/OpenDMTQ-Setup.exe --silent --no-start > /out/setup-4.log 2>&1 || { echo "FAIL: the silent install failed"; exit 1; }
  echo "$(entry UninstallString)" | grep -q -- "--uninstall-window" || { echo "FAIL: the silent install left Velopack'"'"'s entry"; exit 1; }
  run_entry QuietUninstallString
  seen=""
  for i in $(seq 1 30); do [ -n "$(setup_window)" ] && seen=yes; [ -e "$PROGRAM/current" ] || break; sleep 1; done
  wait_for 60 "[ ! -e \"\$PROGRAM\" ]" || { echo "FAIL: the quiet uninstall left the program"; exit 1; }
  [ -z "$seen" ] || { snap quiet-window; echo "FAIL: the quiet uninstall showed a window"; exit 1; }
  [ -f "$DATA/com.example.game/data/android_id" ] || { echo "FAIL: the quiet uninstall took the data"; exit 1; }
  has_entry && { echo "FAIL: Windows'"'"' entry stayed after the quiet uninstall"; exit 1; }
  echo "4. the quiet uninstall: nothing on screen, the program gone, the data kept"

  # ---- 5. installed again; Windows'"'"' Settings, Apps: the uninstall page from a copy; Delete everything.
  wine /tmp/OpenDMTQ-Setup.exe --silent --no-start > /out/setup-5.log 2>&1 || { echo "FAIL: the second silent install failed"; exit 1; }
  make_data
  run_entry UninstallString
  wait_for 120 "[ -n \"\$(setup_window)\" ]" || { snap apps-no-window; echo "FAIL: Windows'"'"' Apps opened no uninstall"; exit 1; }
  sleep 4; snap apps-uninstall
  ls -d "$TEMPDIR"/OpenDMTQ-uninstall-* >/dev/null 2>&1 || { echo "FAIL: the uninstall does not run from a copy"; exit 1; }
  press Down; sleep 1; snap apps-delete-everything
  press Return
  wait_for 120 "[ ! -e \"\$PROGRAM\" ] && [ ! -e \"\$DATA\" ]" || { snap apps-stuck; echo "FAIL: left: $(leftovers)"; exit 1; }
  sleep 3; snap apps-uninstalled
  press Escape
  wait_for 20 "[ -z \"\$(setup_window)\" ]" || { echo "FAIL: Esc did not close the Apps uninstall'"'"'s end page"; exit 1; }
  # The copy goes a few seconds after its window (Windows'"'"' command processor removes it).
  wait_for 30 "[ -z \"\$(leftovers)\" ]" || { echo "FAIL: left after Delete everything: $(leftovers)"; exit 1; }
  has_entry && { echo "FAIL: Windows'"'"' entry stayed after the Apps uninstall"; exit 1; }
  echo "5. Windows'"'"' Apps uninstall with Delete everything: nothing of OpenDMTQ'"'"'s left on the PC"
  wineserver -k
  echo "setup e2e done"
  touch /out/setup-e2e-done
'
status=$?
# Ended with 0 but short of its last step: a failure.
if [ "$status" = 0 ] && [ ! -f "$OUT/setup-e2e-done" ]; then
  echo "FAIL: the run inside ended before its last step"
  status=1
fi
echo "screens and logs in $OUT"
exit $status
