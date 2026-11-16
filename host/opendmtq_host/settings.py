"""The settings in .env: read, written, and filled in on a first start."""

import secrets
import socket

from opendmtq_cli import env
from .paths import ADMIN_PORT, CLI, DEFAULT_PORT, ENV_FILE, WINDOWS
from .output import die, ok


def settings():
    """The settings in .env (an empty dict before setup)."""
    return env.load(ENV_FILE)


def listen_port(values):
    """The port the server listens on: LISTEN_PORT, else the one in the address, else 80."""
    if values.get("LISTEN_PORT"):
        return int(values["LISTEN_PORT"])
    return env.split(values.get("PUBLIC_HOST", ""))[1] if values.get("PUBLIC_HOST") else 80


def admin_port(values):
    """The admin service's own port, on loopback, behind Apache: never an address anybody opens. Never the server's own
    port: an install from before 0.11.0 has 8791 here, which the server may since have been moved to by hand."""
    port = int(values.get("ADMIN_PORT") or ADMIN_PORT)
    if port != listen_port(values):
        return port
    return ADMIN_PORT if ADMIN_PORT != port else ADMIN_PORT + 1


def site_url(values):
    """The server's one address: the players' site, with the admin pages and the API under it."""
    return f"http://{values['PUBLIC_HOST']}/"


def admin_url(values):
    """Where the owner opens the admin pages: on the server's one port, under /opendmtq/admin/. At the address phones use
    on a local network; on an internet address (or with ADMIN_ON_PUBLIC_PORT=no) on the server PC itself, as localhost
    (this install has no HTTPS to carry the password from anywhere else)."""
    if values.get("ADMIN_ON_PUBLIC_PORT", "yes") == "yes" and env.is_lan_only(values.get("PUBLIC_HOST", "")):
        return f"http://{values['PUBLIC_HOST']}/opendmtq/admin/"
    return f"http://localhost:{listen_port(values)}/opendmtq/admin/"


def bindable(port, address="0.0.0.0"):
    """True when this program may listen on the port (nothing else holds it, and the system allows it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Windows lets a second program take a port another holds unless this is set.
        if WINDOWS:
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0), 1)
        try:
            s.bind((address, port))
            return True
        except OSError:
            return False


def choose_port():
    """The port for a new install: 8791 when it is free, else the first free one after it."""
    for port in range(DEFAULT_PORT, DEFAULT_PORT + 9):
        if bindable(port):
            return port
    die(f"no free port for the server among {DEFAULT_PORT} to {DEFAULT_PORT + 8}: close the program that uses them, or "
        "set another one as LISTEN_PORT in the file .env" + (" (Notepad opens it)" if WINDOWS else ""))


def ensure_settings(host=None, quiet=False):
    """Write what .env lacks: the address phones use, the port, the admin pages' password. Returns the settings."""
    values = settings()
    updates = {}
    # The port first: the address carries it when it is not 80.
    port = listen_port(values) if values.get("PUBLIC_HOST") or values.get("LISTEN_PORT") else choose_port()
    if host:
        # An address given on the command line, with or without its port.
        problem = env.check_host(host)
        if problem:
            die(problem)
        h, p = env.split(host)
        port = p if ":" in host else port
        updates["PUBLIC_HOST"] = env.join(h, port)
    elif not values.get("PUBLIC_HOST"):
        # This machine's address on its network: what phones on the same Wi-Fi reach.
        found = env.detect_host()
        if not found or env.check_host(found):
            die("could not find this PC's network address. Connect it to the same Wi-Fi as the phones, then start "
                "OpenDMTQ.exe again" if WINDOWS else
                "could not find this computer's network address; pass it with --host 192.168.x.y")
        updates["PUBLIC_HOST"] = env.join(found, port)
    if str(values.get("LISTEN_PORT", "")) != str(port):
        updates["LISTEN_PORT"] = str(port)
    # The owner's password for the admin pages, made once and kept.
    if not values.get("ADMIN_PASSWORD"):
        updates["ADMIN_PASSWORD"] = secrets.token_urlsafe(12)
    # The admin service's own port on loopback, free on this machine and never the server's own (an install from
    # before 0.11.0 has 8791 there, which a server moved to 8791 would then hold twice).
    if not values.get("ADMIN_PORT") or int(values["ADMIN_PORT"]) == port:
        updates["ADMIN_PORT"] = str(next((p for p in range(ADMIN_PORT, ADMIN_PORT + 20)
                                          if p != port and bindable(p, "127.0.0.1")), ADMIN_PORT))
    if updates:
        env.save(ENV_FILE, updates)
        if not quiet:
            for k, v in updates.items():
                # The admin service's own port is this program's business, not the owner's: not said.
                if k != "ADMIN_PORT":
                    ok(f"{k}={'(made, see below)' if k == 'ADMIN_PASSWORD' else v} written to .env")
    return settings()


def require_settings():
    """The settings, or stop when setup has not run."""
    values = settings()
    if not values.get("PUBLIC_HOST"):
        die(f"not set up yet: run {CLI} setup")
    return values
