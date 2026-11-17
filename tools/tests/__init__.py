"""Unit tests for the tools package.

python3-qrcode is installed in the tools image only. Outside it, empty stand-ins let the patcher
import; no test draws a QR code.
"""

import importlib.util
import os
import sys
import types

# The admin service's webhook loop (admin/webhooks.py) is not started in the tests: the tests that need it turn it
# themselves (run_once), and no thread of its own looks at a test's database meanwhile.
os.environ["OPENDMTQ_WEBHOOK_LOOP"] = "off"

if importlib.util.find_spec("qrcode") is None:
    for _name in ("qrcode", "qrcode.image", "qrcode.image.svg"):
        sys.modules[_name] = types.ModuleType(_name)
