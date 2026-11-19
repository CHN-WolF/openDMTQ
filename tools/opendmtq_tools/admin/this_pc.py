"""Play on this PC: the PC client on the server PC itself, for an owner who plays there, alone or beside the players. On
the App page and the setup's last step, for a visit from the server PC alone (a browser on it), and through the API:

  the Windows bundle   the installer this server keeps for the site (windows_client.py), set up for this server, with
                       the ID of whoever presses it on its end (the owner's own), run with --silent: it installs the
                       launcher for this Windows user and opens it, the server in place and the ID in the sign-in form.
                       With the PC client installed already, the launcher opens the same way: the server and the ID left
                       where the installer leaves them (preset.json in the launcher's folder), then its own start.
  Linux and macOS      the PC client is a Windows program: the page says how to play from a Windows PC instead. Nothing
                       is run here (no Wine from the server).

A visit from another PC never sees it, and the API refuses it there: what it runs, it runs on the server PC, for the
Windows user the server runs as.
"""

import errno
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time

from flask import flash, g, redirect, request, session, url_for

from .. import windows_client
from . import apps, auth, core, jobs, lifecycle, setup
from .core import Refused, app, BASE, changed, t

# Where Velopack installs the PC client for a Windows user, in %LOCALAPPDATA% (client/opendmtq_client/installer.py
# app_dir()), its launcher's stub in that folder (the shortcuts start it), and the version it keeps installed.
CLIENT_FOLDER = "OpenDMTQ.Client"
LAUNCHER = "OpenDMTQ.exe"
VERSION_FILE = os.path.join("current", "sq.version")
# Where an installer leaves its server for the launcher to take at its next start, or within two seconds while its
# window is open (client/opendmtq_client/preset.py hand_over(), state.py config_dir()).
HAND_OVER = os.path.join("OpenDMTQ", "client", "preset.json")
# The installer's own log and its folder (client/opendmtq_client/installer.py LOG_NAME, log_folder()): a failure names it.
INSTALLER_LOG = "OpenDMTQ-setup.log"
# How long the installer may take before the job stops waiting: its own limit on Velopack's setup is 300 seconds, and a
# frozen program needs a few more to unpack itself.
INSTALL_LIMIT = 420
# The installer's own codes (installer.py main()): 3 while a game is open (it installs nothing then).
GAME_OPEN = 3
# The usual reasons a program does not start, in the page's words: the system's own are in its language, which may not be
# the page's ("Permission denied" in a Korean sentence). Windows' error number first, where it gives one, then the kind of
# error: refused (an antivirus, the file's rights), gone, not a program this PC runs, the disk full, a question of
# Windows' answered No.
WINDOWS_WHY = {5: "here.why_denied", 740: "here.why_denied", 1260: "here.why_denied", 2: "here.why_missing",
               3: "here.why_missing", 193: "here.why_damaged", 216: "here.why_damaged", 112: "err.disk_full",
               39: "err.disk_full", 1223: "here.why_cancelled"}
ERRNO_WHY = {errno.EACCES: "here.why_denied", errno.EPERM: "here.why_denied", errno.ENOENT: "here.why_missing",
             errno.ENOEXEC: "here.why_damaged", errno.ENOSPC: "err.disk_full"}
# This PC's own addresses, looked up again after a minute: a visit to the server by one of them is the server PC's own.
_own = {"at": 0.0, "addresses": frozenset()}
_own_lock = threading.Lock()
# What runs, one at a time: two presses never run two installers.
_running = threading.Lock()


# ------------------------------------------------------------------------------ where the visit comes from

def own_addresses():
    """This computer's own addresses (as it reaches itself, and as its networks know it), looked up again after a
    minute."""
    with _own_lock:
        if time.time() - _own["at"] < 60:
            return _own["addresses"]
    found = set(setup.this_pcs_addresses())
    try:
        # Every address the computer's own name has, IPv6 ones too.
        found.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None))
    except OSError:
        pass
    with _own_lock:
        _own.update(at=time.time(), addresses=frozenset(found))
    return _own["addresses"]


def passed_on_by_a_proxy():
    """True when a proxy other than the server's own passed the visit on, whatever address it comes from (a reverse proxy
    or a tunnel on the server PC passes on visits from elsewhere from loopback): Forwarded or Via, or X-Forwarded-For or
    X-Forwarded-Host naming more hops than the server's own Apache adds to a visit through it (one; none to a visit that
    did not come through it). A browser sends none of these."""
    # The standard header, or the one each proxy adds of itself: neither comes from a browser, nor from the server.
    if request.headers.get("Forwarded") or request.headers.get("Via"):
        return True
    # The server's own hop, when the visit came through it (from its address).
    own = 1 if request.remote_addr in auth.server_addresses() else 0
    # Apache adds the address it took the visit from, and the Host it was sent with, after any a proxy before it gave.
    return any(len([hop for hop in request.headers.get(name, "").split(",") if hop.strip()]) > own
               for name in ("X-Forwarded-For", "X-Forwarded-Host"))


def from_the_stack_gateway(ip):
    """True for a visit Docker Engine passes on from the server PC: through the server, from the stack network's gateway,
    as the server's own rule for the admin pages takes it (server/entrypoint.sh LOCAL_FROM) where the command line says
    that is how this PC's visits come (ADMIN_LOCAL=gateway; under Docker Desktop and rootless Docker every visit comes
    from such an address, and none counts)."""
    # Docker Compose under Docker Engine alone: a host install and Kubernetes have no stack network's gateway.
    if os.environ.get("ADMIN_LOCAL") != "gateway" or setup.HOST_INSTALL or setup.IN_KUBERNETES:
        return False
    # Through the server (its X-Real-IP believed), from the gateway this service's own network has too.
    return request.remote_addr in auth.server_addresses() and ip == auth.stack_gateway()


def from_this_pc():
    """True when the visit (a page, or an API call) comes from the server PC itself, and no proxy passed it on: from
    loopback, from one of this computer's own addresses (a browser on it that opened the server's address on the
    network), or, with Docker Engine, through the server from the stack network's gateway."""
    # Whatever address it comes from, a visit another proxy passed on comes from elsewhere.
    if passed_on_by_a_proxy():
        return False
    ip = auth.client_ip()
    try:
        address = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if setup.HOST_INSTALL and ip in own_addresses():
        # The server runs on this computer, and the visitor's address is one of its own: the visitor is on it too.
        return True
    # With Docker Engine, a visit to localhost on the server PC reaches the server from the stack network's gateway.
    return from_the_stack_gateway(ip)


def here_kind():
    """What Play on this PC is for this visit: "windows" (the Windows bundle: it installs or opens the PC client here),
    "elsewhere" (a server on Linux or macOS: how to play from a Windows PC), or None (a visit from another PC, or a
    server in Kubernetes, which has no PC of its own to play on)."""
    if setup.IN_KUBERNETES or not from_this_pc():
        return None
    # The Windows bundle, as the Server page tells it (the admin pages run on Windows, as the Windows user who started
    # the server); a host install on Linux or macOS, or Docker on Linux.
    return "windows" if lifecycle.install_kind() == "windows" else "elsewhere"


# ------------------------------------------------------------------------------ the PC client on this PC

def local_dir():
    """This Windows user's own folder for programs' data (%LOCALAPPDATA%), as the PC client's installer and launcher
    find it."""
    return os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")


def launcher_path():
    """The installed launcher's stub (the shortcuts' target), when the PC client is installed for this Windows user."""
    path = os.path.join(local_dir(), CLIENT_FOLDER, LAUNCHER)
    return path if os.path.isfile(path) else None


def installed_version():
    """The PC client's version installed for this Windows user ("0.11.0"), "" when it is installed without saying one,
    None when it is not installed."""
    if launcher_path() is None:
        return None
    try:
        # Velopack's own note of it: <version>0.11.0</version>. A copy saved by hand may have a byte order mark.
        with open(os.path.join(local_dir(), CLIENT_FOLDER, VERSION_FILE), encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    start, end = text.find("<version>"), text.find("</version>")
    return text[start + len("<version>"):end].strip() if 0 <= start < end else ""


def installer():
    """The PC client's installer this server keeps, and its version: the copy the site hands out (data/apk/out, once the
    app is built), else the one beside this code (the Windows bundle brings it) or put in data/apk by hand, whole; (None,
    None) without one. Nothing is fetched for it here: a server without one says so."""
    made = apps.windows_offer()
    if made:
        return os.path.join(core.APK, "out", os.path.basename(str(made["file"]))), str(made.get("version") or "")
    for path in (None, os.path.join(core.APK, windows_client.SETUP_NAME)):
        found, version = windows_client.bundled(path)
        if found:
            return found, version or ""
    return None, None


def acting_id():
    """The site ID of whoever presses it, for the launcher's sign-in: the admin signed in to these pages (the owner's ID
    for the owner), or through the API the admin whose token it is."""
    if core.in_api():
        row = g.get("api_token") or {}
        return str(row.get("admin") or "")
    return str(session.get("who") or "")


def site_url():
    """The address the launcher reaches the site by, as the installers the site hands out have it (apps.installer_scheme,
    windows_client.site_url)."""
    return windows_client.site_url(apps.installer_scheme() == "https", core.PUBLIC_HOST)


def offer():
    """What the App page and the setup's last step show of Play on this PC for this visit, or None (nothing: a visit from
    another PC): {"kind", "installed" (the version, "" or None), "installer" (True when this server keeps one), "id"
    (the ID filled in), "url" (the site's address)}."""
    kind = here_kind()
    if kind is None:
        return None
    return {"kind": kind, "installed": installed_version() if kind == "windows" else None,
            "installer": installer()[0] is not None, "id": acting_id(), "url": site_url()}


def refuse_unless_here():
    """Refused unless Play on this PC can run for this visit: from another PC (403), on a server that is no Windows
    bundle (404, with how to play from a Windows PC), or with nothing to run (the PC client not installed and no
    installer kept)."""
    kind = here_kind()
    if kind is None:
        raise Refused(403, "not_this_pc", t("here.not_this_pc"))
    if kind != "windows":
        raise Refused(404, "not_windows", t("here.elsewhere", url=site_url() + "/opendmtq/download.php", id=acting_id()))
    if launcher_path() is None and installer()[0] is None:
        raise Refused(404, "no_installer", t("here.no_installer"))


def start():
    """Play on this PC, as a job: the PC client installed and opened, or opened when it is there. Returns the job's id.
    Refused as refuse_unless_here() says, or while the last press still runs (409 busy)."""
    refuse_unless_here()
    who = acting_id()
    url = site_url()
    https = url.startswith("https://")
    # The server's details as the site's installers carry them, with the ID to fill in: the server's own authority over
    # HTTPS, for the launcher to trust for this server alone.
    details = {"url": url, "name": core.server_name(), "ca": windows_client.own_ca() if https else "", "account": who}
    if not _running.acquire(blocking=False):
        raise Refused(409, "busy", t("here.busy"))

    def work(say):
        try:
            return (open_launcher(details, say) if launcher_path() else install(details, say))
        finally:
            _running.release()

    try:
        job = jobs.start_page_task("pc-client", work)
    except BaseException:
        # Nothing started: the next press may.
        _running.release()
        raise
    changed("app:play_here", who)
    return job


def open_launcher(details, say):
    """The installed launcher opened with this server and the ID: both left where an installer leaves them, then the
    launcher's own start (an open window takes them within two seconds, and comes to the front). Returns (what the page
    says, whether it worked)."""
    say(t("here.working_open"))
    try:
        hand_over(details)
        start_program([launcher_path()], cwd=os.path.dirname(launcher_path()))
    except OSError as e:
        return [("bad", not_started(e))], False
    return [("ok", t("here.opened", id=details["account"]))], True


def hand_over(details):
    """The server and the ID, left for the launcher as its installer leaves them (client/opendmtq_client/preset.py
    hand_over(): {"version", "url", "name", and "ca", "account" when there are}), written whole or not at all."""
    path = os.path.join(local_dir(), HAND_OVER)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kept = {"version": windows_client.PRESET_FORMAT, "url": details["url"], "name": details["name"]}
    for key in ("ca", "account"):
        if details.get(key):
            kept[key] = details[key]
    fd, temp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".preset-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False)
    os.replace(temp, path)


def install(details, say):
    """The installer this server keeps, set up for it with the ID on its end, run with --silent: it installs the PC
    client for this Windows user and opens its launcher, which takes the server and the ID. Returns (what the page says,
    whether it worked)."""
    source, version = installer()
    if source is None:
        return [("bad", t("here.no_installer"))], False
    say(t("here.working_install", v=version or "?"))
    # A folder of its own in the temporary folder, under the name the site hands it out by: Windows shows that name
    # while it runs.
    folder = tempfile.mkdtemp(prefix="opendmtq-play-here-")
    target = os.path.join(folder, windows_client.download_name(core.PUBLIC_HOST, version))
    try:
        tail = windows_client.preset(details["url"], details["name"], details["ca"], details["account"])
        with open(source, "rb") as original, open(target, "wb") as copy:
            shutil.copyfileobj(original, copy, 1 << 20)
            copy.write(tail)
        process = start_program([target, "--silent"], cwd=folder)
        try:
            code = process.wait(timeout=INSTALL_LIMIT)
        except subprocess.TimeoutExpired:
            # Past its time: stopped, never left running behind a page that says it failed.
            process.kill()
            code = None
    except OSError as e:
        return [("bad", not_started(e))], False
    finally:
        # The copy has done its work (or could not): the installer keeps what it installs elsewhere.
        shutil.rmtree(folder, ignore_errors=True)
    if code == 0:
        return [("ok", t("here.installed", id=details["account"]))], True
    if code == GAME_OPEN:
        return [("bad", t("here.game_open"))], False
    return [("bad", t("here.failed", code="?" if code is None else code,
                      log=os.path.join(tempfile.gettempdir(), INSTALLER_LOG)))], False


def not_started(e):
    """Why the PC client did not start, as the page says it: the usual reasons in its own words (WINDOWS_WHY, ERRNO_WHY),
    any other in the system's."""
    key = WINDOWS_WHY.get(getattr(e, "winerror", None)) or ERRNO_WHY.get(e.errno)
    return t("here.not_started", why=t(key) if key else (e.strerror or str(e)))


def start_program(command, cwd):
    """A program of the PC client started on its own: no console window of its own, apart from this service (it goes on
    when the server stops), its output nowhere."""
    flags = 0
    if os.name == "nt":
        # DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP: the launcher outlives the server's window, and Ctrl+C there
        # never reaches it.
        flags = 0x00000008 | 0x00000200
    return subprocess.Popen(command, cwd=cwd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------------------ the pages

@app.route(BASE + "/app/play-here", methods=["POST"])
def play_here():
    """Play on this PC, from the App page or the setup's last step (back=setup): back there, following the job when it
    takes longer than a form waits, with what it said once it ends."""
    to_setup = request.form.get("back") == "setup"
    endpoint, extra = ("setup_page", {"step": "app"}) if to_setup else ("app_page", {})
    try:
        job_id = start()
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for(endpoint, **extra))
    job = jobs._jobs.get(job_id)
    if job and job["ended"].wait(jobs.PAGE_WAIT):
        jobs.flash_said(job)
        return redirect(url_for(endpoint, **extra))
    return redirect(url_for(endpoint, here=job_id, **extra))


def following(job_id):
    """The job a page's ?here= names while it runs (the page follows it), or None: one that ended says what it did on
    the page, once (jobs.nothing_to_follow)."""
    if not job_id or jobs.nothing_to_follow(job_id):
        return None
    return job_id
