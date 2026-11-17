"""The admin pages as the Windows bundle shows them, for the pages' tests, which run them on Linux (tests/ui/run.sh's
thispc stage): the install's kind said to be the bundle's (lifecycle.install_kind), so that Play on this PC is the
button that installs the PC client here. Nothing else differs: the same app, its pages and their checks.

    gunicorn --pythonpath tests/ui as_windows:app
"""

from opendmtq_tools import admin
from opendmtq_tools.admin import lifecycle

# The Windows bundle, as the Server page and Play on this PC tell it.
lifecycle.install_kind = lambda: "windows"
# What gunicorn serves.
app = admin.app
