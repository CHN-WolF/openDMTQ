"""The Windows build's script (client/packaging/windows/build.sh) leaves no Windows program runnable in the folder it
builds into, however the build ends: WSL hands a file that starts as Windows' programs do (MZ) to Windows when it is run,
and the build's containers write their programs executable."""

import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# The script, beside the launcher's code.
BUILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "packaging", "windows", "build.sh")


@unittest.skipIf(sys.platform == "win32" or not shutil.which("bash"), "the build runs in bash on Linux")
class NoProgramLeftRunnable(unittest.TestCase):
    def test_the_build_takes_the_executable_bits_off_windows_programs_however_it_ends(self):
        with open(BUILD, encoding="utf-8") as f:
            script = f.read()
        # The function as build.sh has it, and its trap on the script's exit (whether the build passes or fails).
        found = re.search(r"^windows_programs_not_runnable\(\) \{\n.*?^\}\n", script, re.M | re.S)
        self.assertIsNotNone(found, "build.sh has no windows_programs_not_runnable")
        self.assertRegex(script, r"(?m)^trap windows_programs_not_runnable EXIT$")
        out = tempfile.mkdtemp(prefix="odq-build-test-")
        self.addCleanup(shutil.rmtree, out)
        # What a build leaves, with the modes its containers give them: the installer, Velopack's setup, a library, a
        # script of its own and a text file that starts with the same letters as a program.
        made = {"releases/OpenDMTQ-Setup.exe": (b"MZ\x90\x00\x03", 0o755), "setup/velopack-setup.exe": (b"MZ\x90", 0o775),
                "dist/OpenDMTQ/_internal/python312.dll": (b"MZ\x90\x00", 0o755), "dist/run.sh": (b"#!/bin/sh\n", 0o755),
                "dist/notes.txt": (b"MZ is how a program starts", 0o644)}
        for name, (data, mode) in made.items():
            path = os.path.join(out, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, mode)
        # The build's own options and function, ending in a failure: its exit status stays the failure's.
        done = subprocess.run(["bash", "-c", 'set -euo pipefail\nOUT="$1"\n%s\ntrap windows_programs_not_runnable EXIT\n'
                                             "exit 3" % found.group(0), "build", out], capture_output=True, timeout=60)
        self.assertEqual(done.returncode, 3, done.stderr)
        modes = {name: stat.S_IMODE(os.stat(os.path.join(out, name)).st_mode) for name in made}
        self.assertEqual(modes, {"releases/OpenDMTQ-Setup.exe": 0o644, "setup/velopack-setup.exe": 0o664,
                                 "dist/OpenDMTQ/_internal/python312.dll": 0o644, "dist/run.sh": 0o755,
                                 "dist/notes.txt": 0o644})
