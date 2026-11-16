"""The Server page: the server's own life in one place. Whether it runs, stopping and starting it again, the repair, the
server's data part by part (and deleting it), and removing the server from the PC. Each action is a function the page and
the API both call (api.py), as on the other pages.

What each install can do from here: a host install and the Windows bundle stop, start again and remove themselves (their
program reads a request in its run folder, as it does for the setup's restart); with Docker Compose and Kubernetes these
pages run inside the server and say the command that does it instead. The repair and the data work everywhere: they need
only the server's folders, which these pages have.
"""

import datetime
import json
import os
import socket
import time

from flask import abort, flash, redirect, render_template, request, url_for

from .. import repair as repairing, server_data
from . import apps, assets, auth, backups, core, jobs, setup, status
from .core import Refused, app, BASE, changed, t, tp

# The words a deletion and a removal must be confirmed with, typed: either language's word does it, whatever the page's.
CONFIRM_DELETE = ("delete", "삭제")
CONFIRM_REMOVE = ("uninstall", "제거")

# The page's words for each install, each part of the data (its name and what it holds), each thing a removal takes away,
# and each step of the repair in each state: the keys of strings.py, written out here.
KIND_WORDS = {"windows": "server.kind_windows", "host": "server.kind_host", "docker": "server.kind_docker",
              "kubernetes": "server.kind_kubernetes"}
REMOVE_LEADS = {"windows": "server.remove_lead_windows", "host": "server.remove_lead_host",
                "docker": "server.remove_lead_docker", "kubernetes": "server.remove_lead_kubernetes"}
COMMAND_LEADS = {"docker": "server.by_command_docker", "kubernetes": "server.by_command_kubernetes"}
PART_WORDS = {"database": ("data.database", "data.database_note"), "recordings": ("data.recordings", "data.recordings_note"),
              "songs": ("data.songs", "data.songs_note"), "apps": ("data.apps", "data.apps_note"),
              "backups": ("data.backups", "data.backups_note"), "logs": ("data.logs", "data.logs_note"),
              "game": ("data.game", "data.game_note")}
REMOVE_WORDS = {"folder": "server.removes_folder", "firewall": "server.removes_firewall", "startup": "server.removes_startup",
                "service": "server.removes_service", "link": "server.removes_link", "containers": "server.removes_containers",
                "images": "server.removes_images", "clone": "server.removes_clone", "release": "server.removes_release"}
REPAIR_WORDS = {
    ("folders", "ok"): "repair.folders_ok", ("folders", "fixed"): "repair.folders_fixed", ("folders", "bad"): "repair.folders_bad",
    ("database", "ok"): "repair.database_ok", ("database", "bad"): "repair.database_bad",
    ("database", "skip"): "repair.database_skip",
    ("owner", "ok"): "repair.owner_ok", ("owner", "fixed"): "repair.owner_fixed", ("owner", "bad"): "repair.owner_bad",
    ("songs", "fixed"): "repair.songs_fixed", ("songs", "bad"): "repair.songs_bad", ("songs", "skip"): "repair.songs_skip",
    ("app", "ok"): "repair.app_ok", ("app", "fixed"): "repair.app_fixed", ("app", "bad"): "repair.app_bad",
    ("app", "skip"): "repair.app_skip",
    ("files", "ok"): "repair.files_ok", ("files", "fixed"): "repair.files_fixed", ("files", "bad"): "repair.files_bad",
    ("files", "skip"): "repair.files_skip",
    ("copies", "fixed"): "repair.copies_fixed", ("copies", "bad"): "repair.copies_bad",
}


def install_kind():
    """What this server is, for what the page offers: "windows" (the bundle), "host" (Linux or macOS without
    containers), "kubernetes" or "docker"."""
    if setup.HOST_INSTALL:
        return "windows" if os.name == "nt" else "host"
    return "kubernetes" if setup.IN_KUBERNETES else "docker"


def can_run_itself():
    """True where these pages can stop, start again and remove the server: its own program reads the run folder."""
    return setup.HOST_INSTALL and bool(setup.RUN_DIR)


def kube_names():
    """The Helm release and its namespace, as the chart tells these pages (deploy/helm), for the commands they show."""
    return os.environ.get("OPENDMTQ_RELEASE") or "opendmtq", os.environ.get("POD_NAMESPACE") or "opendmtq"


def commands():
    """The command for each action on an install where these pages cannot do it: Docker Compose's ./opendmtq, or
    Kubernetes' kubectl and helm. {} on a host install, which does each from here."""
    kind = install_kind()
    if kind == "docker":
        return {"stop": "./opendmtq down", "restart": "./opendmtq restart", "repair": "./opendmtq repair",
                "delete_data": "./opendmtq delete-data", "uninstall": "./opendmtq uninstall", "port": "./opendmtq port <port>"}
    if kind == "kubernetes":
        release, ns = kube_names()
        host, _ = setup.address_parts(core.PUBLIC_HOST)
        return {"stop": f"kubectl -n {ns} scale deploy -l app.kubernetes.io/instance={release} --replicas=0",
                "restart": f"kubectl -n {ns} rollout restart deploy -l app.kubernetes.io/instance={release}",
                "uninstall": f"helm uninstall {release} -n {ns}",
                "delete_data": f"kubectl -n {ns} delete pvc -l app.kubernetes.io/instance={release}",
                "port": f"helm upgrade {release} <chart> -n {ns} --reuse-values --set publicHost={host}:<port>"}
    return {}


def removes():
    """What a removal takes away on this install, as keys of the page's words (server.removes_<key>)."""
    kind = install_kind()
    if kind == "windows":
        return ["folder", "firewall", "startup"]
    if kind == "host":
        return ["folder", "service", "link"]
    if kind == "docker":
        return ["containers", "images", "clone"]
    return ["release"]


def request_file(name, body):
    """A request for the server's own program, in its run folder (it looks every two seconds): stop, restart or
    uninstall. Refused where there is no such program to read it."""
    if not can_run_itself():
        raise Refused(404, "host_only", message=setup.HOST_ONLY)
    try:
        # Whole before it is there: the program never reads half of one.
        path = os.path.join(setup.RUN_DIR, name)
        with open(path + ".new", "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(path + ".new", path)
    except OSError as e:
        raise Refused(500, f"{name.split('.')[0]}_failed", t("server.ask_failed", why=e.strerror or str(e)))


def restart_server():
    """Asks the server's program to stop every part and start it again with the settings as they are now (restart.request,
    as the setup's change of address does). These pages restart with it."""
    request_file("restart.request", str(int(time.time())))
    changed("server:restart", auth.client_ip())


def uninstall_server(keep_data, confirm):
    """Asks the server's program to stop and remove itself from this PC (uninstall.request), keeping data/ and .env when
    keep_data. confirm: the word typed to say yes (CONFIRM_REMOVE)."""
    if (confirm or "").strip().lower() not in CONFIRM_REMOVE:
        raise Refused(400, "not_confirmed", t("server.type_to_confirm", word=tp("server.remove_word")))
    request_file("uninstall.request", json.dumps({"keep_data": bool(keep_data)}))
    changed("server:uninstall", "keep data" if keep_data else "everything")


def port_now():
    """The port the server serves now: the one in the address it started with."""
    return setup.address_parts(core.PUBLIC_HOST)[1]


def next_address():
    """The address the server moves to at its next start, when .env says another than the one it serves (a port moved
    on this page, or by the command line); None otherwise, and where these pages cannot read .env."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        return None
    try:
        with open(setup.ENV_FILE, encoding="utf-8-sig") as f:
            for line in f.read().splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip().removeprefix("export ").strip() == "PUBLIC_HOST":
                    value = value.strip().strip("'\"")
                    return value if value and value != core.PUBLIC_HOST else None
    except OSError:
        pass
    return None


def port_free(port):
    """True when no other program holds the port on this computer (on Windows, as only the program holding it may use
    it then)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", 0), 1)
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def move_port(raw):
    """Moves the server to another port (a host install, the Windows bundle): LISTEN_PORT and the port in PUBLIC_HOST in
    .env, from its next start, when the app is built again for the new address and the site's download page tells players
    to install it. Refused: no such port, the one it is on, one another program holds, or an install where the command
    line does it (Docker Compose, Kubernetes: the command to use). Returns {port, address, from_next_start}."""
    if not (setup.HOST_INSTALL and setup.ENV_FILE):
        raise Refused(409, "by_command", t("port.by_command", command=commands().get("port", "")))
    text = str(raw if raw is not None else "").strip()
    if not text.isdigit() or not 1 <= int(text) <= 65535:
        raise Refused(400, "bad_port", t("port.bad"))
    port = int(text)
    if port == port_now() and next_address() is None:
        raise Refused(409, "same_port", t("port.same", port=port), tone="ok")
    if port != port_now() and not port_free(port):
        raise Refused(409, "port_taken", t("port.taken", port=port))
    host, _ = setup.address_parts(core.PUBLIC_HOST)
    new = host if port == 80 else f"{host}:{port}"
    setup.save_env({"PUBLIC_HOST": new, "LISTEN_PORT": str(port)})
    changed("server:port", f"{core.PUBLIC_HOST} > {new}")
    return {"port": port, "address": f"http://{new}/", "from_next_start": True}


def layout():
    """Where the server's data is, as these pages see it."""
    return server_data.Layout()


def data_parts():
    """Each part of the server's data, in the page's order: {"part", "bytes", "can_delete"}."""
    sizes = server_data.sizes(layout())
    return [{"part": part, "bytes": sizes[part]["bytes"], "can_delete": sizes[part]["can_delete"]} for part in server_data.PARTS]


def start_delete(parts, make_backup, confirm):
    """Starts deleting these parts of the server's data as a job (a backup first when make_backup, kept whatever else
    goes). confirm: the word typed to say yes (CONFIRM_DELETE). Returns the job's id."""
    parts = [p for p in server_data.PARTS if p in set(parts or ())]
    if not parts:
        raise Refused(400, "no_parts", t("data.none_chosen"))
    if (confirm or "").strip().lower() not in CONFIRM_DELETE:
        raise Refused(400, "not_confirmed", t("server.type_to_confirm", word=tp("data.delete_word")))
    # Not while an import or a build works with the same folders.
    why = setup.busy()
    if why:
        raise Refused(409, "busy", why)

    def work(say):
        said, kept = [], []
        if make_backup:
            try:
                kept.append(backups.make_backup("before-delete"))
                said.append(("ok", t("data.backed_up", name=kept[0])))
            except Exception as e:  # noqa: BLE001 - nothing is deleted without the backup that was asked for
                return [("bad", t("data.not_backed_up", why=core.why(e)))], False
        done = server_data.delete(layout(), parts, keep=kept, say=say)
        # The status page's disk and the site copies count again.
        status._disk_cache.clear()
        gone = [p for p in parts if done.get(p)]
        left = [p for p in parts if not done.get(p)]
        if gone:
            said.append(("ok", t("data.deleted", what=", ".join(tp(PART_WORDS[p][0]) for p in gone))))
        if left:
            said.append(("bad", t("data.not_deleted", what=", ".join(tp(PART_WORDS[p][0]) for p in left))))
        changed("server:delete-data", ", ".join(gone))
        return said, not left

    return jobs.start_page_task("delete-data", work, parts=parts)


def start_repair():
    """Starts the repair as a job: the steps of repair.py, the site copies these pages keep, and the app's build when the
    one on offer is missing or for another address. Returns the job's id."""
    why = setup.busy()
    if why:
        raise Refused(409, "busy", why)

    def work(say):
        root = repairing.install_root()
        results = repairing.run(layout(), root=root, version=repairing.install_version(root), user=core.ADMIN_USER,
                                password=core.PASSWORD, public_host=core.PUBLIC_HOST, say=say)
        # The owner's sign-in for the site as these pages keep it (with their own way of keeping a password).
        results["owner"] = {"kept": ("ok", ""), "written": ("fixed", ""), "removed": ("fixed", "")}.get(
            auth.owner_file_write(), results["owner"])
        # The copies of the site's look these pages keep for when the game server is down: taken afresh.
        try:
            for name in os.listdir(assets.SITE_COPIES) if os.path.isdir(assets.SITE_COPIES) else []:
                os.remove(os.path.join(assets.SITE_COPIES, name))
            assets._css.clear()
            results["copies"] = ("fixed", "")
        except OSError as e:
            results["copies"] = ("bad", core.why(e))
        # The app: built again when the one on offer is missing or for another address, as the App page builds it.
        state, detail = results["app"]
        if state == "bad":
            try:
                job, _ = apps.start_build("")
                results["app"] = ("fixed", job)
            except Refused as e:
                results["app"] = ("bad", core.plain(e.words) or detail)
        said = []
        for step in repairing.STEPS + ("copies",):
            state, detail = results[step]
            # The program's files on an install with no list of them: said where it matters (a host install's own), and
            # only the steps that have words for the state they ended in (the owner's sign-in skipped has none).
            if step == "files" and state == "skip" and install_kind() not in ("windows", "host"):
                continue
            key = REPAIR_WORDS.get((step, state))
            if key:
                said.append(("bad" if state == "bad" else "ok", t(key, detail=detail)))
        changed("server:repair", ", ".join(f"{s} {results[s][0]}" for s in results if results[s][0] in ("fixed", "bad")))
        return said, not any(state == "bad" for state, _ in results.values())

    return jobs.start_page_task("repair", work)


# ------------------------------------------------------------------------------ the page

@app.route(BASE + "/server", methods=["GET"])
def server_page():
    """The Server page: its state and what can be done with it here."""
    wanted = request.args.get("job", "")
    if wanted and jobs.nothing_to_follow(wanted):
        return redirect(url_for("server_page"))
    job = jobs._jobs.get(wanted) if wanted else None
    parts = data_parts()
    # Since when this service has run: the server's own start, as these pages start with it.
    started = int(setup.STARTED.rsplit("-", 1)[1]) if "-" in setup.STARTED else 0
    return render_template("server.html", kind=install_kind(), can_run=can_run_itself(), commands=commands(),
                           removes=removes(), parts=parts, total=sum(p["bytes"] for p in parts),
                           since=datetime.datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M") if started else "",
                           version=os.environ.get("OPENDMTQ_VERSION") or "", root=repairing.install_root(),
                           port=port_now(), next_address=next_address(),
                           can_move_port=bool(setup.HOST_INSTALL and setup.ENV_FILE),
                           kind_words=KIND_WORDS, command_leads=COMMAND_LEADS, part_words=PART_WORDS,
                           remove_leads=REMOVE_LEADS, remove_words=REMOVE_WORDS,
                           job=wanted or None, job_kind=job["kind"] if job else None)


@app.route(BASE + "/server/restart", methods=["POST"])
def server_restart():
    """Restart the server (a host install): the page then waits for these pages to answer again, and comes back here."""
    try:
        restart_server()
    except Refused as e:
        if e.code == "host_only":
            abort(404)
        flash(e.words, e.tone)
        return redirect(url_for("server_page"))
    return render_template("server_restart.html", instance=setup.STARTED, ping=url_for("setup_ping"),
                           back=url_for("server_page"))


@app.route(BASE + "/server/port", methods=["POST"])
def server_port():
    """Move the server to another port from its next start (a host install): said on this page, and from then on above
    the Restart that makes it now."""
    try:
        moved = move_port(request.form.get("port"))
        flash(t("port.saved", address=moved["address"]), "ok")
    except Refused as e:
        flash(e.words, e.tone)
    return redirect(url_for("server_page") + "#port")


@app.route(BASE + "/server/repair", methods=["POST"])
def server_repair():
    try:
        return jobs.answer(start_repair(), "server_page")
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("server_page"))


@app.route(BASE + "/server/data", methods=["POST"])
def server_delete():
    """Delete the parts ticked, a backup first when that is ticked (it is, as the page comes)."""
    try:
        job = start_delete(request.form.getlist("part"), request.form.get("backup") == "yes", request.form.get("confirm"))
        return jobs.answer(job, "server_page")
    except Refused as e:
        flash(e.words, e.tone)
        return redirect(url_for("server_page") + "#data")


@app.route(BASE + "/server/uninstall", methods=["POST"])
def server_uninstall():
    """Remove the server from this PC (a host install, the Windows bundle): the page says what happens, as it stops."""
    keep = request.form.get("keep") == "yes"
    try:
        uninstall_server(keep, request.form.get("confirm"))
    except Refused as e:
        if e.code == "host_only":
            abort(404)
        flash(e.words, e.tone)
        return redirect(url_for("server_page") + "#remove")
    return render_template("server_removing.html", kind=install_kind(), keep=keep, ping=url_for("setup_ping"),
                           instance=setup.STARTED)
