#!/bin/bash
# Builds the PC client for Windows on Linux, in containers:
#   1. pictures, the version and the update address (Linux Python with Pillow, the UI test image)
#   2. PyInstaller under Wine with a Windows Python -> one folder with OpenDMTQ.exe and OpenDMTQ-cmd.exe
#   3. the player for Windows (opendmtq-player-windows.zip, arm32/bundle_windows.sh) into that folder as player\, and
#      the licence texts of what the program carries into its licenses\ (docs/THIRD_PARTY_NOTICES.md)
#   4. Velopack's vpk (.NET) -> Velopack's setup and the update packages: the whole package, and a delta package from
#      the previous release's when it is given (previous.py: a launcher of that version then downloads what changed)
#   5. PyInstaller again -> OpenDMTQ-Setup.exe: the installer's dialogs with Velopack's setup inside
# Usage: [OPENDMTQ_UPDATE_SOURCE=<where releases are published>] [PLAYER_ZIP=<zip>]
#        [OPENDMTQ_PREVIOUS_RELEASE=<package or folder>] [OPENDMTQ_TEST_UPDATE_KEY=<public key>]
#        client/packaging/windows/build.sh OUT_DIR
#   The version is the project's (deploy/helm/opendmtq/Chart.yaml). OPENDMTQ_UPDATE_SOURCE is the GitHub repository URL
#   whose releases the launcher looks at after its server's (client/opendmtq_client/updates.py); without it, only its
#   server's. PLAYER_ZIP is the player for Windows (default _work/arm32/opendmtq-player-windows.zip, where
#   arm32/bundle_windows.sh leaves it). OPENDMTQ_PREVIOUS_RELEASE names the previous release's full package (as its
#   release has it, opendmtq.client-<version>-full.nupkg), or a folder holding it; the last build into OUT_DIR keeps its
#   own too. Without either, no delta package is made. OPENDMTQ_TEST_UPDATE_KEY makes a test build: its launcher also
#   takes releases signed with that key (a test's own key pair, never set for a release, whose check refuses such a
#   launcher: .github/release_assets.py).
# OUT_DIR/releases then holds what a release takes (.github/release_assets.py names them for it): OpenDMTQ-Setup.exe and
# its .version, and Velopack's update feed (releases.win.json) and packages (OpenDMTQ.Client-<version>-full.nupkg, and
# OpenDMTQ.Client-<version>-delta.nupkg when the previous release's package was there).
set -euo pipefail
OUT=$(realpath -m "${1:?usage: build.sh OUT_DIR}")
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
HERE="$REPO/client/packaging/windows"
# No Windows program stays runnable in OUT once the build ends, however it ends: WSL hands a file that starts as Windows'
# programs do (MZ) to Windows when it is run, and the containers write theirs executable. Each such file under OUT loses
# its executable bits; nothing else is touched. Nothing here changes the build's exit status.
windows_programs_not_runnable() {
  local f
  # Only files with an executable bit: each read for its first two bytes.
  find "$OUT" -type f -perm /111 -print0 2>/dev/null | while IFS= read -r -d '' f; do
    if [ "$(head -c 2 "$f" 2>/dev/null)" = MZ ]; then
      chmod a-x "$f" 2>/dev/null || true
    fi
  done || true
  return 0
}
trap windows_programs_not_runnable EXIT
# The project's one version: the chart's, as the release's checks read it.
VERSION=$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([0-9A-Za-z.+-]*\)"\{0,1\}[[:space:]]*$/\1/p' "$REPO/deploy/helm/opendmtq/Chart.yaml" | head -n 1)
[ -n "$VERSION" ] || { echo "no version in deploy/helm/opendmtq/Chart.yaml" >&2; exit 1; }
PLAYER_ZIP=$(realpath -m "${PLAYER_ZIP:-$REPO/_work/arm32/opendmtq-player-windows.zip}")
[ -f "$PLAYER_ZIP" ] || { echo "no player for Windows at $PLAYER_ZIP: run arm32/bundle_windows.sh first" >&2; exit 1; }
# The Windows Python archive, fetched once and checked against this hash before every use.
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz"
PBS_SHA256="590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5"
# Velopack's packaging tool, the same release line as the velopack Python package the launcher bundles.
VPK_VERSION="${VPK_VERSION:-1.2.161}"
mkdir -p "$OUT/cache" "$OUT/assets"
echo "OpenDMTQ client $VERSION -> $OUT"

# ---- the build machines (cached by Docker once made)
# Wine with the player's needs, from the player's own tests; then a Windows Python on it.
docker image inspect opendmtq-arm32-wine >/dev/null 2>&1 \
  || docker build -q -t opendmtq-arm32-wine -f "$REPO/arm32/wine.Dockerfile" "$REPO/arm32" >/dev/null
if ! docker image inspect opendmtq-client-winbuild:local >/dev/null 2>&1; then
  [ -f "$OUT/cache/pbs.tar.gz" ] || curl -fsSL -o "$OUT/cache/pbs.tar.gz" "$PBS_URL"
  echo "$PBS_SHA256  $OUT/cache/pbs.tar.gz" | sha256sum -c --quiet
  ctx=$(mktemp -d)
  cp "$HERE/Dockerfile" "$OUT/cache/pbs.tar.gz" "$ctx/"
  docker build -q -t opendmtq-client-winbuild:local "$ctx" >/dev/null
  rm -rf "$ctx"
fi
docker image inspect opendmtq-client-ui:local >/dev/null 2>&1 \
  || docker build -q -t opendmtq-client-ui:local "$REPO/client/tests/ui" >/dev/null
# What a container wrote in OUT, back to whoever runs this script: the containers run as root, and the steps after them
# write into what they made (CI's runner is no root; as root this changes nothing).
own() {
  [ "$(id -u)" = 0 ] && return 0
  docker run --rm --network none -v "$OUT:/out" --entrypoint chown opendmtq-client-ui:local -R "$(id -u):$(id -g)" /out
}

# ---- 1. pictures, the version and the update address
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -v "$REPO:/src:ro" -v "$OUT/assets:/out" -w /src/client \
  opendmtq-client-ui:local python packaging/windows/assets.py /out "$VERSION"
own
# The version and the update address go into the launcher as files (an empty address: this build looks for none).
printf '%s' "$VERSION" > "$OUT/assets/version.txt"
printf '%s' "${OPENDMTQ_UPDATE_SOURCE:-}" > "$OUT/assets/update-source.txt"
echo "update address: ${OPENDMTQ_UPDATE_SOURCE:-(none)}"
# A test build's own public key goes in the same way, beside signing.py (empty: the launcher takes the project's key
# alone, as every release's does). Anything but a public key stops the build: it would be a launcher that takes none.
TEST_KEY=${OPENDMTQ_TEST_UPDATE_KEY:-}
[[ -z "$TEST_KEY" || "$TEST_KEY" =~ ^[0-9a-fA-F]{64}$ ]] \
  || { echo "OPENDMTQ_TEST_UPDATE_KEY is not a public key (64 hex digits)" >&2; exit 2; }
printf '%s' "$TEST_KEY" > "$OUT/assets/update-test-keys.txt"
[ -z "$TEST_KEY" ] || echo "TEST BUILD, not for a release: its launcher also takes releases signed with the key $TEST_KEY"

# ---- 2. PyInstaller under Wine (no network: everything it needs is in the image)
rm -rf "$OUT/dist" "$OUT/work"
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e OPENDMTQ_BUILD_DIR='Z:\out\assets' \
  -v "$REPO:/src:ro" -v "$OUT:/out" -w /src/client opendmtq-client-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' -m PyInstaller --noconfirm --log-level WARN \
      --distpath 'Z:\\out\\dist' --workpath 'Z:\\out\\work' 'Z:\\src\\client\\packaging\\windows\\OpenDMTQ.spec' \
      > /out/pyinstaller.log 2>&1; code=\$?; wineserver -w; exit \$code" || { tail -n 30 "$OUT/pyinstaller.log"; exit 1; }
own
ls "$OUT/dist/OpenDMTQ/OpenDMTQ.exe" "$OUT/dist/OpenDMTQ/OpenDMTQ-cmd.exe" >/dev/null

# ---- 3. the player for Windows beside the launcher, as player\ (the launcher looks for it there)
rm -rf "$OUT/player" && mkdir -p "$OUT/player"
python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$PLAYER_ZIP" "$OUT/player"
[ -f "$OUT/player/OpenDMTQ-Player/OpenDMTQ-Player.exe" ] || { echo "$PLAYER_ZIP holds no OpenDMTQ-Player.exe" >&2; exit 1; }
cp -R "$OUT/player/OpenDMTQ-Player" "$OUT/dist/OpenDMTQ/player"
# Which player this is, for a report and the release notes.
cp "$OUT/player/bundle.json" "$OUT/dist/OpenDMTQ/player/bundle.json"

# ---- 3b. the licence texts of what the program carries, in its own licenses\ (the player keeps its own in player\)
LIC="$OUT/dist/OpenDMTQ/licenses"
rm -rf "$LIC" && mkdir -p "$LIC"
# From the build machine's Windows Python: Python's (with bzip2's, Tcl/Tk's and the Microsoft C runtime's terms), Tk's
# own, Pillow's (with the image libraries in it), PyInstaller's (its bootloader's exception) and Velopack's list of the
# libraries in its Python module.
docker run --rm --network none -v "$OUT:/out" --entrypoint sh opendmtq-client-winbuild:local -c '
  set -e
  py=/wine/drive_c/python; site=$py/Lib/site-packages; lic=/out/dist/OpenDMTQ/licenses
  cp "$py/LICENSE.txt" "$lic/Python-LICENSE.txt"
  cp "$py/tcl/tk8.6/license.terms" "$lic/Tcl-Tk-license.terms.txt"
  cp "$site"/pillow-*.dist-info/licenses/LICENSE "$lic/Pillow-LICENSE.txt"
  cp "$site"/pyinstaller-*.dist-info/licenses/COPYING.txt "$lic/PyInstaller-COPYING.txt"
  cp "$site"/velopack-*.dist-info/sboms/velopack_python.cyclonedx.json "$lic/Velopack-sbom.cyclonedx.json"'
own
# From the repository: OpenDMTQ's own, the fonts', and those the build machine does not have (licenses/README.md).
cp "$REPO/LICENSE" "$LIC/OpenDMTQ-LICENSE.txt"
cp "$REPO/client/opendmtq_client/assets/fonts/Saira-OFL.txt" "$REPO/client/opendmtq_client/assets/fonts/Pretendard-OFL.txt" \
  "$REPO/client/opendmtq_client/assets/fonts/MaterialIcons-LICENSE.txt" "$HERE/licenses/"*-LICENSE.txt "$LIC/"
# Which text is whose, as the Windows bundle's THIRD-PARTY-NOTICES.txt says it (host/windows/build.sh).
python3 - "$LIC" <<'PY'
import pathlib, sys
lic = pathlib.Path(sys.argv[1])
rows = [
    ("Python 3.12, with the Microsoft C runtime it ships (vcruntime140.dll)",
     "PSF License Agreement, with bzip2's terms; the C runtime under Microsoft's terms for its distributable code",
     "Python-LICENSE.txt"),
    ("Tcl/Tk 8.6, the launcher's window", "Tcl/Tk license (BSD-style)", "Tcl-Tk-license.terms.txt"),
    ("OpenSSL 3, libffi 3.4.4 and zlib 1.3.1, in Python's ssl, ctypes and zlib",
     "Apache License 2.0 (OpenSSL), MIT (libffi), zlib license (zlib)",
     "MaterialIcons-LICENSE.txt (the Apache License 2.0 text), libffi-LICENSE.txt, zlib-LICENSE.txt"),
    ("Pillow, with the image libraries in it", "MIT-CMU; the libraries' own licenses follow it in the same file",
     "Pillow-LICENSE.txt"),
    ("Velopack: the installer's setup, Update.exe and the launcher's updates",
     "MIT; the libraries in its Python module and their licenses are listed in Velopack-sbom.cyclonedx.json",
     "Velopack-LICENSE.txt"),
    ("PyInstaller's bootloader, which starts OpenDMTQ.exe, OpenDMTQ-cmd.exe and the installer",
     "GPL 2 with the Bootloader Exception, which allows it in a program under any license", "PyInstaller-COPYING.txt"),
    ("The fonts: DMTQ Wide (a cut of Saira), Pretendard, Material Icons",
     "SIL Open Font License 1.1 (DMTQ Wide, Pretendard), Apache License 2.0 (Material Icons)",
     "Saira-OFL.txt, Pretendard-OFL.txt, MaterialIcons-LICENSE.txt"),
    ("The player for Windows: the arm32 runtime (Dynarmic and the libraries it brings, Android's 32-bit linker and system "
     "libraries), ANGLE, zlib, the GCC runtime, winpthreads and LLVM's runtime libraries",
     "0BSD, MIT, Apache License 2.0, BSD, ISC, zlib and NCSA licenses, GPL 3 with the GCC Runtime Library Exception, "
     "Apache License 2.0 with LLVM Exceptions",
     "..\\player\\licenses\\ (NOTICES.txt, android-NOTICE.html.gz)"),
]
text = ["The OpenDMTQ PC client brings these programs and parts, each under its own license. The full texts are in this",
        "folder, or in the folder named. OpenDMTQ's own code is under the MIT License (OpenDMTQ-LICENSE.txt).", ""]
for name, licence, where in rows:
    text += [name, "  License: " + licence, "  Text:    " + where, ""]
(lic / "NOTICES.txt").write_text("\r\n".join(text), encoding="utf-8")
missing = [w.strip() for _, _, ws in rows for w in ws.split(",") if w.strip().endswith(".txt") and " " not in w.strip()
           and not (lic / w.strip()).is_file()]
if missing:
    sys.exit("licenses: missing " + ", ".join(missing))
print(len(rows), "notices,", len(list(lic.iterdir())), "files in licenses")
PY

# ---- 4. Velopack: the installer and the update packages
# Made again when VPK_VERSION or the recipe changes (the image's label holds both): vpk makes delta packages with zstd's
# own program (--patch-from), which the .NET image does not have, and an image made before would build no delta.
VPK_RECIPE="vpk-$VPK_VERSION-zstd"
if [ "$(docker image inspect -f '{{index .Config.Labels "opendmtq.recipe"}}' opendmtq-client-vpk:local 2>/dev/null)" != "$VPK_RECIPE" ]; then
  ctx=$(mktemp -d)
  printf 'FROM mcr.microsoft.com/dotnet/sdk:8.0\nRUN apt-get update && apt-get install -y --no-install-recommends zstd && rm -rf /var/lib/apt/lists/*\nRUN dotnet tool install -g vpk --version %s\nENV PATH="${PATH}:/root/.dotnet/tools"\n' "$VPK_VERSION" > "$ctx/Dockerfile"
  docker build -q --label "opendmtq.recipe=$VPK_RECIPE" -t opendmtq-client-vpk:local "$ctx" >/dev/null
  rm -rf "$ctx"
fi
# The previous release's full package stays beside the new one, and nothing else of an earlier build: vpk makes the
# delta package from it, and lists it in the feed as the package the delta starts from (previous.py).
previous=$(python3 "$HERE/previous.py" "$OUT/releases" "$VERSION" ${OPENDMTQ_PREVIOUS_RELEASE:+"$(realpath -m "$OPENDMTQ_PREVIOUS_RELEASE")"})
echo "delta package from: $previous"
# The package id names the install folder (%LOCALAPPDATA%\OpenDMTQ.Client), apart from the player's data in OpenDMTQ.
docker run --rm --network none -v "$OUT:/out" opendmtq-client-vpk:local vpk "[win]" pack \
  --packId OpenDMTQ.Client --packVersion "$VERSION" --packDir /out/dist/OpenDMTQ --mainExe OpenDMTQ.exe \
  --packTitle OpenDMTQ --packAuthors OpenDMTQ --icon /out/assets/OpenDMTQ.ico \
  --splashImage /out/assets/splash.png --outputDir /out/releases > "$OUT/vpk.log" 2>&1 || { cat "$OUT/vpk.log"; exit 1; }
own
# The portable zip vpk also makes is no part of a release: OpenDMTQ-Setup.exe installs, and the feed and the package update.
rm -f "$OUT/releases/"*-Portable.zip
# Nor are vpk's two other lists: RELEASES is the older Squirrel feed and assets.win.json the list vpk's own upload reads;
# Velopack's GitHub source in the launcher reads releases.win.json alone (its sources/github.rs and sources/mod.rs).
rm -f "$OUT/releases/RELEASES" "$OUT/releases/assets.win.json"
# Nor is the previous release's package the delta was made from: it is in its own release, which the feed names.
if [ "$previous" != none ]; then
  find "$OUT/releases" -maxdepth 1 -iname "opendmtq.client-$previous-full.nupkg" -delete
  ls "$OUT/releases/OpenDMTQ.Client-$VERSION-delta.nupkg" >/dev/null || { echo "vpk made no delta package from $previous" >&2; exit 1; }
fi
ls -la "$OUT/releases"

# ---- 5. the installer people run: the launcher's dialogs around Velopack's setup, in one file
rm -rf "$OUT/setup" && mkdir -p "$OUT/setup"
mv "$OUT/releases/OpenDMTQ.Client-win-Setup.exe" "$OUT/setup/velopack-setup.exe"
docker run --rm --network none -e PYTHONDONTWRITEBYTECODE=1 -e OPENDMTQ_BUILD_DIR='Z:\out\assets' \
  -e OPENDMTQ_VELOPACK_SETUP='Z:\out\setup\velopack-setup.exe' \
  -v "$REPO:/src:ro" -v "$OUT:/out" -w /src/client opendmtq-client-winbuild:local bash -c "
    wine 'C:\\python\\python.exe' -m PyInstaller --noconfirm --log-level WARN \
      --distpath 'Z:\\out\\setup\\dist' --workpath 'Z:\\out\\setup\\work' 'Z:\\src\\client\\packaging\\windows\\setup.spec' \
      > /out/pyinstaller-setup.log 2>&1; code=\$?; wineserver -w; exit \$code" || { tail -n 30 "$OUT/pyinstaller-setup.log"; exit 1; }
own
cp "$OUT/setup/dist/OpenDMTQ-Setup.exe" "$OUT/releases/OpenDMTQ-Setup.exe"
# The version beside it, which a server reads when it hands the installer out (tools/opendmtq_tools/windows_client.py).
printf '%s\n' "$VERSION" > "$OUT/releases/OpenDMTQ-Setup.exe.version"
ls -la "$OUT/releases/OpenDMTQ-Setup.exe"
sha256sum "$OUT/releases/OpenDMTQ-Setup.exe"
