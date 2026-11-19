#!/usr/bin/env bash
# The local quality gate: everything that needs the game's own files, which CI does not have, plus the tests CI also runs, on
# this machine, for the commit checked out. When all of it passes the commit gets the status qa/local on GitHub; a release
# (.github/workflows/release.yml) and ./opendmtq deploy ask for that status. See docs/testing.md.
#
# Usage: tests/qa.sh [--no-status]       --no-status: run everything, tell GitHub nothing (for a tree with changes in it)
#        EMULATOR=1 APP_FOLDER=<a test server's data/apk/out> tests/qa.sh
#                                        also the tour of the game on a running emulator (tests/game/tour.sh)
#        CLIENTS=<folder> tests/qa.sh    also every edit of the patcher against each APK in that folder: the game's other
#                                        version, a copy changed for another server (tools/tests/test_real_client.py)
#        SERIAL=1 tests/qa.sh            one step after another, for a machine with few processors
#        NAME_PREFIX, TAG, PORTS         a run's containers (NAME_PREFIX-*), images (opendmtq-*:TAG, default qa) and nine
#                                        ports in a row from PORTS, apart from another run's; without PORTS each step's own
#
# The launcher's flicker film runs first, with nothing else of the gate beside it: it counts the frames a change shows, which
# a machine busy with the other steps adds to. Then the server's and the tools' images are built once for every step, and
# the steps that share nothing run side by side in four lanes: the launcher's other parts; the pages; the server on the
# real game files, under load, upgraded and as a host install; and the quick ones. Each step has its own log and its own
# line in the report, as when they ran one after another.
#
# One report per commit under _work/qa, the newest five kept: each step's whole output and the list of results.
set -uo pipefail
# No step changes this computer's Windows firewall or asks for its administrator (a WSL machine): every command line the
# steps run takes this, as --no-firewall.
export OPENDMTQ_NO_FIREWALL=1

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1
SHA=$(git rev-parse HEAD)
SHORT=${SHA:0:7}
REPORT=$ROOT/_work/qa/$SHORT
POST_STATUS=yes
if [ "${1:-}" = --no-status ]; then
  POST_STATUS=no
fi
# The steps, in the order the report lists them.
STEPS="shell tools cli client access game live load ui upgrade host tour"
# A run's own names and images, which every step takes: the images built here once, for all of them.
export NAME_PREFIX=${NAME_PREFIX:-odq}
export TAG=${TAG:-qa}
export NO_BUILD=1
BEGAN=$(date +%s)

# A status says "this commit passed": with other changes in the tree the tests are not about that commit.
if [ "$POST_STATUS" = yes ] && [ -n "$(git status --porcelain)" ]; then
  echo "qa: the tree has changes that are not committed; commit them, or use --no-status" >&2
  exit 2
fi

mkdir -p "$REPORT"
# The newest five reports stay; these are large with their screenshots.
# (What a browser wrote in one may be another user's: then from inside an image, or _work would only ever grow.)
find "$ROOT/_work/qa" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn | tail -n +6 | cut -d' ' -f2- | while read -r old; do
  rm -rf "$old" 2>/dev/null || docker run --rm -u 0 -v "$ROOT/_work/qa:/q" --entrypoint rm "opendmtq-server:$TAG" -rf "/q/$(basename "$old")" || true
done

: > "$REPORT/report.txt"
# Made by the launcher's suite once its flicker film is over (client/tests/ui/run.sh).
QUIET=$(mktemp -u)
# Set when the images did not build: the steps that need them fail at once, with the build's words in their logs.
IMAGES_FAILED=
# One step: its output to a file of its own, one line for it in the report and on the screen. The steps of a lane run in
# a shell of their own, with this step's ports (PORTS) in its environment.
step() {
  local name=$1
  shift
  local start status line ports=()
  start=$(date +%s)
  # Nine ports in a row, one block for each lane: the pages three, the server's lane five (the live test's
  # servers), the contract one.
  if [ -n "${PORTS:-}" ]; then
    case $name in
      ui) ports=("SITE_PORT=$PORTS" "ADMIN_PORT=$((PORTS + 1))" "CHAT_PORT=$((PORTS + 2))") ;;
      live | load | upgrade) ports=("SITE_PORT=$((PORTS + 3))" "ADMIN_PORT=$((PORTS + 4))") ;;
      host) ports=("PORT=$((PORTS + 3))") ;;
      game) ports=("PORT=$((PORTS + 8))") ;;
    esac
  fi
  case $name in
    tools | access | game | live | load | ui | upgrade)
      if [ -n "$IMAGES_FAILED" ]; then
        cp "$REPORT/images.log" "$REPORT/$name.log"
        echo "the images did not build (above): nothing of this step ran" >> "$REPORT/$name.log"
        echo "FAIL $name (0 s): see $REPORT/$name.log" | tee -a "$REPORT/report.txt"
        return
      fi
      ;;
  esac
  (
    [ "${#ports[@]}" -eq 0 ] || export "${ports[@]}"
    "$@"
  ) > "$REPORT/$name.log" 2>&1
  status=$?
  if [ "$status" -eq 0 ]; then
    line="PASS $name ($(($(date +%s) - start)) s)"
  else
    line="FAIL $name ($(($(date +%s) - start)) s): see $REPORT/$name.log"
  fi
  echo "$line" | tee -a "$REPORT/report.txt"
}

tools_tests() {
  # The real game client, for the edits that must find their bytes and objects in it: the file ./opendmtq import brought.
  local base
  base=$(find data/apk/base -maxdepth 1 -name '*.apk' 2>/dev/null | head -1)
  # Without it those tests would skip themselves, and this gate would pass without having looked.
  if [ -z "$base" ]; then
    echo "no game client in data/apk/base: run ./opendmtq import first"
    return 1
  fi
  # More clients for the same edits, when a folder of them is named.
  local more=()
  if [ -n "${CLIENTS:-}" ]; then
    [ -d "$CLIENTS" ] || { echo "CLIENTS is not a folder: $CLIENTS"; return 1; }
    more=(-v "$(cd "$CLIENTS" && pwd):/clients:ro" -e OPENDMTQ_CLIENTS=/clients)
  fi
  # server/portal, the game server and the runtime's build beside tools/, as in the repository: the tests read them too.
  docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$ROOT/tools:/t:ro" -v "$ROOT/server/portal:/server/portal:ro" \
    -v "$ROOT/server/game:/server/game:ro" \
    -v "$ROOT/arm32:/arm32:ro" \
    -v "$ROOT/data/apk/base:/base:ro" ${more[@]+"${more[@]}"} \
    -e OPENDMTQ_BASE_APK="/base/$(basename "$base")" --entrypoint sh "opendmtq-tools:$TAG" \
    -c 'cd /t && python3 -m unittest discover -s tests -t . -v'
}

cli_tests() {
  (cd cli && python3 -m unittest discover -s tests -t . -v)
}

# CI's shell step, with the ShellCheck GitHub's runners have: another version passes what theirs does not, and the first run of
# CI after going public would have been the first to say so.
shell_tests() {
  local shellcheck=(docker run --rm -v "$ROOT:/mnt:ro" -w /mnt koalaman/shellcheck:v0.9.0 --severity=warning)
  git ls-files -z '*.sh' | grep -zv '^arm32/' | xargs -0 "${shellcheck[@]}" || return 1
  "${shellcheck[@]}" -x -P arm32 arm32/build.sh arm32/bundle.sh arm32/test.sh arm32/ndk.sh arm32/build_desktop.sh arm32/build_windows.sh \
    arm32/bundle_windows.sh arm32/test_desktop.sh arm32/test_windows.sh
}

# The PC client's launcher, as CI's client job runs it: its unit tests, then every screen on a virtual screen with the
# layout check, the screenshots kept with the report. The suite's flicker film comes first; QUIET says when it is over.
client_tests() {
  docker build -q -t opendmtq-client-ui:local client/tests/ui >/dev/null || return 1
  docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$ROOT:/src:ro" -w /src/client opendmtq-client-ui:local \
    python -m unittest discover -s tests -t . -v || return 1
  QUIET_DONE=$QUIET client/tests/ui/run.sh "$REPORT/client-ui"
}

# Without containers: host/install.sh on a clean Ubuntu, the server run by ./opendmtq, and the phone app built from the
# game client here (CI runs the same without a client).
host_tests() {
  APK="$ROOT/$(find data/apk/base -maxdepth 1 -name '*.apk' | head -1)" tests/host/run.sh
}

# Each step by its name.
run_step() {
  case $1 in
    shell) step shell shell_tests ;;
    tools) step tools tools_tests ;;
    cli) step cli cli_tests ;;
    client) step client client_tests ;;
    # Who reaches the admin pages and the API on an exposed server's one port, proxies on the server PC among them.
    access) step access tests/access/run.sh ;;
    # The game server's contract with the game, on stand-in game files: every reply the client reads, and its quirks.
    game) step game tests/game/protocol.sh ;;
    # The server on the real game files: the game's own requests, broadcasts, recordings, and a real video in Chromium.
    live) step live env BROWSER=1 tests/live/run.sh ;;
    # Players sharing one server on two cores, on the real game files: one address saving as fast as it can, broadcasts
    # with thirty viewers, a backup and a build of the app; not one player's save may fail. Then the server killed
    # mid-save and a full disk: nothing answered as stored is lost, and the database stays whole.
    load) step load tests/load/run.sh "$REPORT/load" ;;
    # The pages in a real browser. In CI too; here also for what the screenshots show.
    ui) step ui tests/ui/run.sh "$REPORT/ui" ;;
    # An upgrade: the last release's images used as people use them, then this tree's on the same data. In CI too.
    upgrade) step upgrade tests/upgrade/run.sh ;;
    host) step host host_tests ;;
    # On a test server's app (APP_FOLDER): a first start makes a new player on the server the app belongs to.
    tour) step tour tests/game/tour.sh "$REPORT/game" ;;
  esac
}
# A lane: its steps one after another, beside the other lanes.
lane() {
  local name
  for name in "$@"; do
    run_step "$name"
  done
}

# The launcher's suite first: until its flicker film is over (or the step has ended), nothing else starts.
lane client &
client_lane=$!
while [ ! -e "$QUIET" ] && kill -0 "$client_lane" 2>/dev/null; do
  sleep 1
done
rm -f "$QUIET"
# The images every step runs, built once from this tree (the steps take them with NO_BUILD and TAG).
if ! { docker build -q -t "opendmtq-server:$TAG" server && docker build -q -t "opendmtq-tools:$TAG" tools; } > "$REPORT/images.log" 2>&1; then
  IMAGES_FAILED=yes
  echo "qa: the images did not build: see $REPORT/images.log"
fi
if [ -n "${SERIAL:-}" ]; then
  # One step after another, the launcher's suite before them.
  wait "$client_lane"
  lane shell tools cli access game live load ui upgrade host
else
  lane shell cli tools access game &
  lane live load upgrade host &
  lane ui &
  wait
fi
if [ -n "${EMULATOR:-}" ]; then
  run_step tour
fi

# The report in the steps' own order, whatever order they ended in; a step that left no line (its lane stopped) fails.
sorted=$(for name in $STEPS; do grep -E "^(PASS|FAIL) $name \(" "$REPORT/report.txt"; done)
printf '%s\n' "$sorted" > "$REPORT/report.txt"
took="in $(($(date +%s) - BEGAN)) s"
missing=
for name in $STEPS; do
  [ "$name" != tour ] || [ -n "${EMULATOR:-}" ] || continue
  grep -qE "^(PASS|FAIL) $name \(" "$REPORT/report.txt" || missing="$missing $name"
done
if [ -n "$missing" ]; then
  echo "qa: no result from:$missing"
fi

if [ -n "$missing" ] || grep -q '^FAIL' "$REPORT/report.txt"; then
  echo "qa: FAILED on $SHORT $took, report in $REPORT"
  exit 1
fi

passed="$(grep -c '^PASS' "$REPORT/report.txt") steps passed on this machine"
if [ "$POST_STATUS" = yes ]; then
  # The tree may have moved on during a run this long: the status would then be about something that was not tested.
  if [ -n "$(git status --porcelain)" ] || [ "$(git rev-parse HEAD)" != "$SHA" ]; then
    echo "qa: passed, but the tree changed during the run; no status sent" >&2
    exit 1
  fi
  if ! gh api "repos/{owner}/{repo}/statuses/$SHA" -f state=success -f context=qa/local -f description="$passed" > /dev/null; then
    echo "qa: passed, but the status could not be sent (is gh signed in, is the commit pushed?)" >&2
    exit 1
  fi
  echo "qa: $SHORT passed $took: status qa/local sent"
else
  echo "qa: $SHORT passed $took (no status sent)"
fi
