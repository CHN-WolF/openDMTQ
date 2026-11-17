# Third-party notices

OpenDMTQ's own code and documentation are under the MIT License ([LICENSE](../LICENSE)). The parts below keep their own
licenses. They are listed by where they go: the site, the phones' runtime, the player for Windows and the PC client, the
tools, the container images and the Windows bundle. None of them is the game: OpenDMTQ contains no game data.

## In the site

| Component | License | Where |
|:---|:---|:---|
| DMTQ Condensed and DMTQ Wide, cut down from Saira | SIL Open Font License 1.1 | `server/portal/fonts`, with `OFL-Saira.txt` |
| DMTQ Text, cut down from Pretendard 1.3.9 | SIL Open Font License 1.1 | `server/portal/fonts`, with `OFL-Pretendard.txt` |
| hls.js 1.5.17, the video player | Apache License 2.0 | `server/portal/hls`, with its `LICENSE` |

A cut-down font is a modified version, and both fonts' licenses reserve the original name, so each file has a name of its
own (`server/portal/fonts/README.md`).

## In the phones' runtime, and so in every app a server builds

| Component | License | Where |
|:---|:---|:---|
| Dynarmic (commit `a466015`), the CPU emulator | 0BSD (its `LICENSE.txt`); the libraries it brings along (fmt, mcl, oaknut, robin-map, xbyak, Zydis and others) under their own | Fetched by `arm32/build.sh`, with local changes in `arm32/patches` |
| Android's 32-bit linker and system libraries (libc, libm, libdl, libstdc++, libc++, libz, liblog), unchanged | Apache License 2.0, and BSD, MIT, ISC, zlib and NCSA licenses | Taken by `arm32/build.sh` from Google's Android 6.0 ARM system image (`armeabi-v7a-23_r06`) |

The runtime is the release's `opendmtq-phone-runtime-<version>-android-arm64-armv7.zip`. The tools image and the Windows
bundle keep it for app builds, and the player for Windows carries it under `runtime/sysroot`. The system image's own
terms leave such parts to their licenses (Android Software Development Kit License Agreement, 3.5). Their notices are
the image's `etc/NOTICE.html.gz`, which goes with them; it does not name libc++, whose license is
`arm32/libc++-LICENSE.txt`. The compiler's runtime in them (libgcc) is under the GCC Runtime Library Exception, which
asks nothing of what is built with it.

Those terms apply to whoever hands the runtime on or shares an app built with it. To make that simple, every app built
with the runtime carries the full texts in `assets/opendmtq` (`NOTICES.txt`, and Android's own
`android-NOTICE.html.gz`), and every server lists the parts at `/opendmtq/licenses.php`, linked from the site's footer.

## In the player for Windows

| Component | License | Where |
|:---|:---|:---|
| ANGLE 2.1.r25748 (`libEGL.dll`, `libGLESv2.dll`) | BSD 3-clause | MSYS2's package at a fixed hash (`arm32/build_windows.sh`) |
| zlib 1.4 (`zlib1.dll`) | zlib license | MSYS2's package at a fixed hash |
| The GCC runtime 16.2.0 that ANGLE's DLLs were built with (`libgcc_s_seh-1.dll`, `libstdc++-6.dll`) | GPL 3 with the GCC Runtime Library Exception, which asks nothing of what is built with it | MSYS2's packages at fixed hashes |
| winpthreads 14.0.0 (`libwinpthread-1.dll`) | Its own permissive license | MSYS2's package at a fixed hash |
| LLVM's libc++, libc++abi, libunwind and compiler-rt, and the mingw-w64 runtime with its winpthreads, built into the player | Apache License 2.0 with LLVM Exceptions; mingw-w64's own permissive licenses | The llvm-mingw 20261006 toolchain (`arm32/windows.Dockerfile`) |
| AMD FidelityFX Super Resolution 1 | MIT License | `arm32/desktop/third_party/fsr`, ported to an OpenGL ES shader |
| NVIDIA Image Scaling | MIT License | `arm32/desktop/third_party/nis`, ported to an OpenGL ES shader |
| SMAA | MIT License | `arm32/desktop/third_party/smaa`, ported to an OpenGL ES shader |
| Intel's CMAA 2 | Apache License 2.0 | `arm32/desktop/third_party/cmaa2`, ported to an OpenGL ES shader |
| Pretendard and DMTQ Wide (a cut of Saira), the fonts of what it draws over the game | SIL Open Font License 1.1 | The PC client's fonts, copied into the player's `fonts` folder by `arm32/bundle_windows.sh` |

The player carries every text in `licenses/NOTICES.txt`. It goes out inside the PC client's installer
(`opendmtq-pc-client-<version>-windows-x64-setup.exe`), which the tools image and the Windows bundle keep for the site to
hand out. The app holds none of these parts.

## In the PC client

| Component | License |
|:---|:---|
| Python 3.12, with the Microsoft C runtime it ships | PSF License, with bzip2's and Tcl/Tk's terms, and Microsoft's for its C runtime |
| Tcl/Tk | Its BSD-style license |
| OpenSSL, libffi and zlib, in Python's modules | Apache License 2.0, MIT License, zlib license |
| Pillow 11.3.0 | MIT-CMU, with the licenses of the image libraries in it |
| Velopack 1.2.161 | MIT License |
| PyInstaller 6.16.0's bootloader | GPL 2 with the Bootloader Exception, which allows it in a program under any license |
| DMTQ Wide (a cut of Saira) and Pretendard | SIL Open Font License 1.1 |
| Material Icons | Apache License 2.0 |

`client/packaging/windows/build.sh` builds them into the installer and the program it installs, with the player above.
The installed program carries every text in `licenses/`, with `NOTICES.txt` saying which is whose, and the player's in
`player/licenses/`. A release hands the installer out, and the tools image and the Windows bundle keep it for the site
to hand out. The app holds none of these parts.

## In the tools

| Component | License |
|:---|:---|
| 7-Zip 25.01 | GNU LGPL with the unRAR restriction; its `License.txt` is in the tools image at `/usr/local/share/doc/7-zip` and in `.host/share/7-zip`, its source at 7-zip.org |
| Apktool 2.12.1 | Apache License 2.0, inside its jar |
| uber-apk-signer 1.3.0 | Apache License 2.0, inside its jar |

`tools/Dockerfile` fetches them into the tools image, and `host/install.sh` into `.host/`. The app holds none of them.

## In the container images

A release publishes `opendmtq-server` and `opendmtq-tools`, built on the official `php:8.3-apache` and
`eclipse-temurin:21-jre-noble` images with their systems' packages: PHP and the Apache HTTP Server, Python with Flask,
gunicorn, qrcode, Pillow and lz4. Each keeps its own license: PHP License 3.01, Apache License 2.0, GPL v2 with the
Classpath Exception, PSF License, BSD, MIT and HPND. The packages' copyright files are in each image under
`/usr/share/doc`.

## In the Windows bundle

| Component | License |
|:---|:---|
| Apache HTTP Server 2.4.69 (Apache Lounge build) | Apache License 2.0 |
| PHP 8.3.36 | PHP License 3.01 |
| Python 3.12.10, with the Microsoft C runtime it ships, and the libraries of `host/windows/requirements.txt` | PSF License; the libraries' own BSD, MIT, PSF, HPND and ZPL licenses |
| Eclipse Temurin 21.0.13+9 (Java) | GPL v2 with the Classpath Exception, source at github.com/adoptium/jdk21u |
| 7-Zip 25.01 | GNU LGPL with the unRAR restriction |
| Apktool 2.12.1 and uber-apk-signer 1.3.0 | Apache License 2.0 |

They sit in the bundle's `runtime/` folder unchanged, as `host/windows/build.sh` downloads them. The bundle also holds
the phones' runtime (`app/tools/opendmtq_tools/opendmtq-arm32-runtime.zip`, with its licenses inside). The bundle's
`THIRD-PARTY-NOTICES.txt` says where each full text is.

## Credits

What the game asks a server for was first written down by earlier DMTQ servers. The site follows the look of the DJMAX
Technika "Platinum Crew" site, with original artwork.
