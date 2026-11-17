"""One-time sign-in links to the players' site, made here for the API (POST /site/link) as the site makes them for the PC
client's My page on the site (server/portal/auth.php once_issue(), client.php?link): a link that signs a browser in to an
account once, in the minute after it was made, at /opendmtq/login.php?once=<token>.

The site keeps them beside the database, in signin-links/, a file a link named by the SHA-256 of its token (the token
itself is written nowhere): {"account", "next", "expires"}. The site takes one by renaming it, so that a link opened
twice signs in once; links that ran out go whenever a new one is made, on either side.
"""

import hashlib
import json
import os
import re
import secrets
import time

from . import core
from .core import Refused

# How long a link works after it was made (seconds): ONCE_LIFE in server/portal/auth.php.
LIFE = 60
# Their folder beside the database (once_dir() in auth.php).
FOLDER = "signin-links"
# A page of the site to go on to, as the site's safe_next() takes one: a path on this site, nothing that leads elsewhere.
PAGE = re.compile(r"/(?!/)[A-Za-z0-9/_.?=&%-]*\Z")


def folder():
    """The links' folder, beside the database as the site's state is."""
    return os.path.join(os.path.dirname(core.DB), FOLDER)


def issue(account, page="/opendmtq/"):
    """A new link that signs a browser in to the players' site as `account` and opens `page` (a path on the site):
    (its address on the site, when it stops working). Refused: a page that is no path on the site (400), or a folder
    that cannot be written (503)."""
    if not PAGE.match(page or ""):
        raise Refused(400, "bad_field", message="next is not a page of the players' site: a path such as "
                                                "/opendmtq/player.php?id=7.")
    where = folder()
    now = time.time()
    try:
        os.makedirs(where, mode=0o700, exist_ok=True)
        # What ran out, and what a taking cut off left: gone, as the site does it.
        for name in os.listdir(where):
            path = os.path.join(where, name)
            try:
                if os.path.getmtime(path) < now - LIFE:
                    os.remove(path)
            except OSError:
                # Taken by the site meanwhile.
                pass
        # 32 random bytes in the letters an address keeps as they are: 43 of them, as the site makes its own.
        token = secrets.token_urlsafe(32)
        path = os.path.join(where, hashlib.sha256(token.encode("ascii")).hexdigest() + ".json")
        temp = f"{path}.{secrets.token_hex(4)}.new"
        expires = int(now) + LIFE
        # Written beside it, then put in its place: the site never reads half of it.
        with open(temp, "w", encoding="utf-8") as f:
            json.dump({"account": account, "next": page, "expires": expires}, f)
        os.replace(temp, path)
    except OSError as e:
        raise Refused(503, "links_unavailable", message=f"The link could not be kept beside the database: {e.strerror or e}.")
    return "/opendmtq/login.php?once=" + token, expires
