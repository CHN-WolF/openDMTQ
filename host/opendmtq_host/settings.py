"""The settings in .env: read, written, and filled in on a first start."""

import os
import secrets
import socket

from opendmtq_cli import env
from .paths import ADMIN_PORT, CLI, DEFAULT_PORT, ENV_FILE, RUN, WINDOWS
from .output import die, ok


def settings():
    """The settings in .env (an empty dict before setup)."""
    return env.load(ENV_FILE)


def listen_port(values):
    """The port the server listens on: LISTEN_PORT, else the one in the address, else 80."""
    if values.get("LISTEN_PORT"):
        return int(values["LISTEN_PORT"])
    return env.split(values.get("PUBLIC_HOST", ""))[1] if values.get("PUBLIC_HOST") else 80


# The settings of the admin pages' own port before 0.11.0: no longer read, and taken out of .env at the start.
OLD_ADMIN_KEYS = ("ADMIN_PORT", "ADMIN_BIND")


def admin_port(values):
    """The admin service's own port, on loopback, behind Apache: never an address anybody opens, never the server's own
    port, never one .env names. The one this run's start chose (choose_admin_port), else the first that would be."""
    try:
        with open(os.path.join(RUN, "admin.port"), encoding="ascii") as f:
            chosen = int(f.read().strip())
        if 1024 <= chosen <= 65535 and chosen != listen_port(values):
            return chosen
    except (OSError, ValueError):
        pass
    return next(p for p in range(ADMIN_PORT, ADMIN_PORT + 40) if p != listen_port(values))


def choose_admin_port(values):
    """At a start: the first port from ADMIN_PORT on that this program may listen on (on loopback) and that is not the
    server's own, kept in the run folder for the parts that pass the admin pages on, and for the command line."""
    port = next((p for p in range(ADMIN_PORT, ADMIN_PORT + 40) if p != listen_port(values) and bindable(p, "127.0.0.1")),
                ADMIN_PORT)
    os.makedirs(RUN, exist_ok=True)
    with open(os.path.join(RUN, "admin.port.new"), "w", encoding="ascii") as f:
        f.write(f"{port}\n")
    os.replace(os.path.join(RUN, "admin.port.new"), os.path.join(RUN, "admin.port"))
    return port


def forget_old_admin_port():
    """Takes the admin pages' own port of an install from before 0.11.0 out of .env (ADMIN_PORT, ADMIN_BIND): it is
    read no more, and a line that says 8791 would only send someone looking for the admin pages to a port where nothing
    answers. Returns the settings as they are now."""
    values = settings()
    if any(k in values for k in OLD_ADMIN_KEYS):
        env.drop(ENV_FILE, OLD_ADMIN_KEYS)
    return settings()


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
    if updates:
        env.save(ENV_FILE, updates)
        if not quiet:
            for k, v in updates.items():
                ok(f"{k}={'(made, see below)' if k == 'ADMIN_PASSWORD' else v} written to .env")
    return settings()


def require_settings():
    """The settings, or stop when setup has not run."""
    values = settings()
    if not values.get("PUBLIC_HOST"):
        die(f"not set up yet: run {CLI} setup")
    return values
