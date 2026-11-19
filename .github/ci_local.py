#!/usr/bin/env python3
"""CI's jobs (.github/workflows/ci.yml) on this computer, as GitHub runs them. Run it before every push to main.

Each job runs in a container standing in for GitHub's runner (.github/ci-runner.Dockerfile: Ubuntu 24.04, as a user
who is not root: uid 1001 as on GitHub when this runs as root, else whoever runs it), on a fresh clone of the commit
checked out (its history and tags only where the job's checkout asks for them), with its steps' run blocks as the
workflow has them (bash -e) and the actions it uses done the same way here: the checkout, the images' builds (into this
computer's Docker), Helm, the cache (a folder here) and the artifacts one job hands another. Jobs run side by side as
their needs allow, each with names, an image tag and ports of its own (NAME_PREFIX, TAG and the ports the test scripts
read), so that two cannot meet. The changes job decides, as on GitHub, whether the heavy jobs run: for what this commit
changes since origin/main (--base names another commit; --all runs everything). The jobs that need a Windows runner are
named and not run: CI runs them on GitHub.

    python3 .github/ci_local.py [JOB ...] [--jobs N] [--base REV | --all] [--prefix NAME] [--ports FIRST-LAST] [--keep]

JOB: only these jobs and the jobs they need. --jobs: how many jobs at once (default 4). --prefix: the start of every
container's, network's and image tag's name (default odqci). --ports: the ports the jobs' servers take on this computer,
three for each job at a time (default 18901-18960). --keep: the jobs' folders stay. Each job's log, step by step, and the
artifacts are in _work/ci/<commit>/. Needs Docker, git and Python 3 with PyYAML.
"""

import argparse
import glob
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER_IMAGE = "opendmtq-ci-runner:local"
# GitHub's runner's user, when this runs as root (a job must not be root, or what only root may do would pass here).
RUNNER_UID = 1001
# The variables the test scripts take their names, image tag and ports from: each job's own, over what the workflow says.
PORTS_PER_JOB = 3


# ------------------------------------------------------------------------------------------------- the expressions

TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+(?:\.\d+)?)|(?P<op>==|!=|&&|\|\||<=|>=|[!<>(),\[\]])"
                   r"|(?P<name>[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_*][A-Za-z0-9_-]*)*))")


class Expression:
    """GitHub's expression language as the workflow uses it: literals, contexts, == != && || ! < >, and the functions
    always, success, failure, cancelled, startsWith, endsWith, contains, format and hashFiles."""

    def __init__(self, text, context, functions):
        self.tokens, at = [], 0
        while at < len(text):
            if text[at:].strip() == "":
                break
            m = TOKEN.match(text, at)
            if not m or m.end() == at:
                raise ValueError(f"cannot read the expression at {text[at:]!r}")
            kind = m.lastgroup
            self.tokens.append((kind, m.group(kind)))
            at = m.end()
        self.at, self.context, self.functions = 0, context, functions

    def value(self):
        result = self.either()
        if self.at != len(self.tokens):
            raise ValueError(f"left over in the expression: {self.tokens[self.at:]}")
        return result

    def peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else (None, None)

    def take(self, op=None):
        token = self.peek()
        if op is not None and token != ("op", op):
            raise ValueError(f"expected {op}, found {token}")
        self.at += 1
        return token

    # || and && give back one of their sides, as in GitHub's expressions.
    def either(self):
        left = self.both()
        while self.peek() == ("op", "||"):
            self.take()
            right = self.both()
            left = left if truthy(left) else right
        return left

    def both(self):
        left = self.compare()
        while self.peek() == ("op", "&&"):
            self.take()
            right = self.compare()
            left = right if truthy(left) else left
        return left

    def compare(self):
        left = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("==", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            right = self.unary()
            left = compared(left, op, right)
        return left

    def unary(self):
        if self.peek() == ("op", "!"):
            self.take()
            return not truthy(self.unary())
        return self.primary()

    def primary(self):
        kind, text = self.take()
        if kind == "str":
            return text[1:-1].replace("''", "'")
        if kind == "num":
            return float(text) if "." in text else int(text)
        if (kind, text) == ("op", "("):
            inner = self.either()
            self.take(")")
            return inner
        if kind == "name":
            if text in ("true", "false"):
                return text == "true"
            if text == "null":
                return None
            if self.peek() == ("op", "("):
                self.take()
                args = []
                while self.peek() != ("op", ")"):
                    args.append(self.either())
                    if self.peek() == ("op", ","):
                        self.take()
                self.take(")")
                if text not in self.functions:
                    raise ValueError(f"no function {text} here")
                return self.functions[text](*args)
            return lookup(self.context, text)
        raise ValueError(f"cannot read {text!r} in the expression")


def truthy(value):
    return value not in (None, False, 0, "", 0.0)


def compared(left, op, right):
    """GitHub compares strings without case, and a string with a number or a boolean as that."""
    def plain(v):
        return v.casefold() if isinstance(v, str) else ("true" if v is True else "false" if v is False else v)
    a, b = plain(left), plain(right)
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    try:
        return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
    except TypeError:
        return False


def lookup(context, path):
    """A context's value by its dotted path (strategy.job-index, needs.changes.outputs.code); None when it is not there."""
    value = context
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def shown(value):
    """A value as GitHub writes it into a string."""
    if value is None:
        return ""
    if value is True or value is False:
        return "true" if value else "false"
    return str(value)


def substitute(text, context, functions):
    """Every ${{ ... }} in a string replaced by its value."""
    if not isinstance(text, str):
        return text
    return re.sub(r"\$\{\{(.*?)\}\}", lambda m: shown(Expression(m.group(1), context, functions).value()), text, flags=re.S)


def condition(text, context, functions):
    """An if: as GitHub reads it: with or without ${{ }}."""
    text = str(text).strip()
    match = re.fullmatch(r"\$\{\{(.*)\}\}", text, flags=re.S)
    return truthy(Expression(match.group(1) if match else text, context, functions).value())


# ------------------------------------------------------------------------------------------------------- the jobs

class Instance:
    """One run of a job: the job itself, or one of its matrix's combinations."""

    def __init__(self, job, spec, matrix, index, total):
        self.job, self.spec, self.matrix, self.index, self.total = job, spec, matrix, index, total
        values = ", ".join(shown(v) for v in matrix.values())
        self.name = f"{job} ({values})" if matrix else job
        self.result, self.outputs, self.number = None, {}, 0

    def windows(self):
        return str(self.spec.get("runs-on", "")).startswith("windows")


def combinations(matrix):
    """The matrix's combinations, in GitHub's order (the first key's values outermost)."""
    keys = [k for k in matrix if k not in ("include", "exclude")]
    found = [{}]
    for key in keys:
        found = [dict(c, **{key: v}) for c in found for v in matrix[key]]
    for drop in matrix.get("exclude", []) or []:
        found = [c for c in found if any(c.get(k) != v for k, v in drop.items())]
    found += list(matrix.get("include", []) or [])
    return found


def expand(jobs):
    """Every job's instances, in the workflow's order."""
    out = []
    for job, spec in jobs.items():
        matrix = (spec.get("strategy") or {}).get("matrix")
        combos = combinations(matrix) if matrix else [{}]
        for i, combo in enumerate(combos):
            out.append(Instance(job, spec, combo, i, len(combos)))
    return out


def needs_of(spec):
    needs = spec.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


class Run:
    def __init__(self, args):
        self.args = args
        self.sha = git("rev-parse", "HEAD")
        self.short = self.sha[:7]
        self.folder = os.path.join(ROOT, "_work", "ci", self.short)
        self.artifacts = os.path.join(self.folder, "artifacts")
        self.cache = os.path.join(ROOT, "_work", "ci", "cache")
        self.lock = threading.Lock()
        self.uid, self.gid = (RUNNER_UID, RUNNER_UID) if os.geteuid() == 0 else (os.getuid(), os.getgid())
        first, last = (int(p) for p in args.ports.split("-"))
        self.blocks = [first + i * PORTS_PER_JOB for i in range((last - first + 1) // PORTS_PER_JOB)]
        if not self.blocks:
            sys.exit("--ports: fewer than three ports")
        self.free = list(self.blocks)
        self.counter = 0
        # What the commit changes, for the changes job: since where main is on GitHub, unless told otherwise.
        self.before = "" if args.all else (git("merge-base", "HEAD", args.base, check=False) or "")
        branch = git("symbolic-ref", "--short", "-q", "HEAD", check=False) or "main"
        origin = git("remote", "get-url", "origin", check=False) or ""
        match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", origin)
        self.repository = f"{match.group(1)}/{match.group(2)}" if match else "local/openDMTQ"
        self.github = {
            "workflow": "ci", "ref": f"refs/heads/{branch}", "ref_name": branch, "ref_type": "branch", "sha": self.sha,
            "event_name": "push", "event": {"before": self.before}, "repository": self.repository,
            "repository_owner": self.repository.split("/")[0], "server_url": "https://github.com", "actor": "local",
            "run_id": str(int(time.time())), "token": "",
        }

    def say(self, text):
        with self.lock:
            print(text, flush=True)

    def take_ports(self):
        """A block of three ports nobody else of this run holds, or None while all are held."""
        with self.lock:
            return self.free.pop(0) if self.free else None

    def give_ports(self, block):
        with self.lock:
            self.free.append(block)
            self.free.sort()

    def number(self):
        with self.lock:
            self.counter += 1
            return self.counter


def git(*args, check=True, cwd=ROOT):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode:
        sys.exit(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip() if result.returncode == 0 else None


def docker(*args, check=True, **kw):
    result = subprocess.run(["docker", *args], capture_output=True, text=True, **kw)
    if check and result.returncode:
        raise RuntimeError(f"docker {' '.join(args[:3])}...: {result.stderr.strip()[-400:]}")
    return result


class Job:
    """One instance run in its runner container, step by step."""

    def __init__(self, run, inst):
        self.run, self.inst, self.block = run, inst, None
        self.steps, self.env_added, self.saves, self.failed = {}, {}, [], False
        self.prefix, self.dir, self.work, self.temp = run.args.prefix, "", ROOT, ""

    def place(self, block):
        """The job's number, names, folders and ports, once it is to run."""
        self.block = block
        self.inst.number = self.run.number()
        self.prefix = f"{self.run.args.prefix}{self.inst.number}"
        safe = re.sub(r"[^A-Za-z0-9]+", "-", self.inst.name).strip("-")
        self.dir = os.path.join(self.run.folder, f"{self.inst.number:02d}-{safe}")
        self.work = os.path.join(self.dir, "work")
        self.temp = os.path.join(self.dir, "temp")
        self.home = os.path.join(self.dir, "home")
        self.log = os.path.join(self.run.folder, f"{self.inst.number:02d}-{safe}.log")
        self.container = f"{self.prefix}-runner"

    # -------------------------------------------------------------- contexts
    def own(self):
        """This job's own names, image tag and ports, over what the workflow says: two jobs side by side never meet."""
        if self.block is None:
            return {}
        b = self.block
        return {"NAME_PREFIX": self.prefix, "TAG": self.prefix, "SITE_PORT": str(b), "ADMIN_PORT": str(b + 1),
                "CHAT_PORT": str(b + 2), "PORT": str(b), "SMOKE_PORT": str(b), "TMPDIR": self.temp}

    def context(self, step_env=None):
        env = {}
        env.update({k: shown(v) for k, v in (self.run.workflow.get("env") or {}).items()})
        env.update({k: shown(v) for k, v in (self.inst.spec.get("env") or {}).items()})
        env.update(self.env_added)
        env.update(step_env or {})
        env.update(self.own())
        needs = {j.job: {"result": j.result, "outputs": j.outputs} for j in self.run.instances
                 if j.job in needs_of(self.inst.spec) and j.result is not None}
        return {"github": self.run.github, "env": env, "matrix": self.inst.matrix, "needs": needs,
                "strategy": {"job-index": self.inst.index, "job-total": self.inst.total},
                "steps": self.steps, "runner": {"os": "Linux", "arch": "X64", "temp": self.temp}, "secrets": {},
                "inputs": {}, "vars": {}}

    def functions(self):
        failed = self.failed
        return {
            "always": lambda: True, "success": lambda: not failed, "failure": lambda: failed,
            "cancelled": lambda: False,
            "startsWith": lambda a, b: shown(a).casefold().startswith(shown(b).casefold()),
            "endsWith": lambda a, b: shown(a).casefold().endswith(shown(b).casefold()),
            "contains": lambda a, b: (b in a) if isinstance(a, list) else shown(b).casefold() in shown(a).casefold(),
            "format": lambda f, *a: re.sub(r"\{(\d+)\}", lambda m: shown(a[int(m.group(1))]), f),
            "hashFiles": self.hash_files,
        }

    def hash_files(self, *patterns):
        """A hash of the files the patterns name in the workspace (what a cache's key changes with)."""
        digest = hashlib.sha256()
        for pattern in patterns:
            for path in sorted(glob.glob(os.path.join(self.work, pattern), recursive=True)):
                if os.path.isfile(path):
                    with open(path, "rb") as f:
                        digest.update(hashlib.sha256(f.read()).digest())
        return digest.hexdigest()

    def value(self, text, step_env=None):
        return substitute(text, self.context(step_env), self.functions())

    # -------------------------------------------------------------- the machine
    def write(self, text):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(text)

    def prepare(self):
        """The job's folders, a fresh clone of the commit as its checkout would make it, and its runner."""
        os.makedirs(self.dir)
        for folder in (self.work, self.temp, self.home):
            os.makedirs(folder)
        checkout = next((s for s in self.inst.spec.get("steps", []) if str(s.get("uses", "")).startswith("actions/checkout")), {})
        depth = int((checkout.get("with") or {}).get("fetch-depth", 1))
        git("init", "-q", cwd=self.work)
        source = "file://" + ROOT
        if depth == 0:
            # The whole history and the release tags, as fetch-depth: 0 has them (no tag that is this computer's alone).
            git("fetch", "-q", source, self.run.sha, "refs/tags/v*:refs/tags/v*", cwd=self.work)
        else:
            git("fetch", "-q", "--no-tags", f"--depth={depth}", source, self.run.sha, cwd=self.work)
        git("checkout", "-q", "--detach", self.run.sha, cwd=self.work)
        if os.geteuid() == 0:
            subprocess.run(["chown", "-R", f"{self.run.uid}:{self.run.gid}", self.dir], check=True)
        socket_group = str(os.stat("/var/run/docker.sock").st_gid)
        # The runner: this computer's network and Docker, the job's folder at the same path as here (a container it
        # starts mounts its files by this computer's paths), its own user.
        docker("run", "-d", "--name", self.container, "--network", "host", "--group-add", socket_group,
               "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{self.dir}:{self.dir}",
               "-w", self.work, RUNNER_IMAGE, "sleep", "infinity")

    def shell(self, script, env, timeout):
        """A script in the runner as the job's user, with bash -e as GitHub runs a step: (exit status, output)."""
        path = os.path.join(self.temp, f"step-{len(self.steps)}-{time.time_ns()}.sh")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        os.chmod(path, 0o755)
        if os.geteuid() == 0:
            os.chown(path, self.run.uid, self.run.gid)
        cmd = ["docker", "exec", "-u", f"{self.run.uid}:{self.run.gid}", "-w", self.work]
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += [self.container, "bash", "-e", path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return 124, out + f"\n(the job's {self.inst.spec.get('timeout-minutes')} minutes ran out)\n"

    def defaults(self, files):
        """The variables GitHub gives every step."""
        return {"CI": "true", "GITHUB_ACTIONS": "true", "GITHUB_WORKSPACE": self.work, "GITHUB_SHA": self.run.sha,
                "GITHUB_REF": self.run.github["ref"], "GITHUB_REF_NAME": self.run.github["ref_name"],
                "GITHUB_REF_TYPE": "branch", "GITHUB_REPOSITORY": self.run.repository,
                "GITHUB_REPOSITORY_OWNER": self.run.github["repository_owner"], "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_EVENT_NAME": "push", "GITHUB_RUN_ID": self.run.github["run_id"], "GITHUB_JOB": self.inst.job,
                "RUNNER_TEMP": self.temp, "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "HOME": self.home, **files}

    # -------------------------------------------------------------- steps
    def step(self, n, step, deadline):
        """One step: (outcome, seconds); its outputs into self.steps when it has an id."""
        name = self.value(step.get("name") or step.get("uses") or f"step {n}")
        step_env = {k: self.value(shown(v)) for k, v in (step.get("env") or {}).items()}
        if not condition(step.get("if", "success()"), self.context(step_env), self.functions()):
            return name, "skipped", 0.0, ""
        began = time.time()
        left = max(1, deadline - time.time())
        files = {"GITHUB_OUTPUT": os.path.join(self.temp, f"output-{n}"), "GITHUB_ENV": os.path.join(self.temp, f"env-{n}"),
                 "GITHUB_STEP_SUMMARY": os.path.join(self.temp, f"summary-{n}"), "GITHUB_PATH": os.path.join(self.temp, f"path-{n}")}
        for f in files.values():
            open(f, "w").close()
            if os.geteuid() == 0:
                os.chown(f, self.run.uid, self.run.gid)
        env = dict(self.context(step_env)["env"], **self.defaults(files))
        if "run" in step:
            if step.get("shell") not in (None, "bash"):
                return name, "skipped", 0.0, f"(shell {step.get('shell')}: not on Linux)\n"
            code, out = self.shell(self.value(step["run"], step_env), env, left)
        else:
            code, out = self.action(step, step_env, env, left)
        outputs = {}
        with open(files["GITHUB_OUTPUT"], encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, _, val = line.rstrip("\n").partition("=")
                    outputs[key] = val
        with open(files["GITHUB_ENV"], encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    key, _, val = line.rstrip("\n").partition("=")
                    self.env_added[key] = val
        outcome = "success" if code == 0 else "failure"
        if step.get("id"):
            self.steps[step["id"]] = {"outputs": outputs, "outcome": outcome, "conclusion": outcome}
        return name, outcome, time.time() - began, out

    def action(self, step, step_env, env, left):
        """The actions the workflow uses, done as they do it on GitHub, in this job's runner."""
        uses = str(step["uses"])
        given = {k: self.value(shown(v), step_env) for k, v in (step.get("with") or {}).items()}
        action = uses.split("@")[0]
        if action in ("actions/checkout", "docker/setup-buildx-action", "docker/setup-qemu-action", "actions/setup-python"):
            # The clone is there; buildx and Python are in the runner.
            return 0, f"({action}: as prepared)\n"
        if action == "azure/setup-helm":
            want = given.get("version", "")
            code, out = self.shell("helm version --short", env, left)
            return (0 if want and want in out else 1), out + (f"(the runner's Helm is not {want})\n" if want not in out else "")
        if action == "docker/build-push-action":
            if given.get("push") == "true":
                return 1, "a push from CI's jobs: not here\n"
            cmd = ["docker", "build", "-q"]
            for tag in re.split(r"[\s,]+", given.get("tags", "").strip()):
                if tag:
                    cmd += ["-t", tag]
            if given.get("file"):
                cmd += ["-f", given["file"]]
            for arg in (given.get("build-args") or "").splitlines():
                if arg.strip():
                    cmd += ["--build-arg", arg.strip()]
            cmd.append(given.get("context", "."))
            return self.shell(" ".join(shell_quote(c) for c in cmd), env, left)
        if action == "actions/upload-artifact":
            return self.upload(given)
        if action == "actions/download-artifact":
            return self.download(given)
        if action == "actions/cache":
            return self.restore(given)
        return 1, f"{uses}: not one this runner knows\n"

    def upload(self, given):
        """The files under the artifact's name, as upload-artifact lays them out: relative to the folder all the paths
        found have in common (a folder given alone: its contents)."""
        found = []
        for pattern in given.get("path", "").splitlines():
            pattern = pattern.strip()
            if pattern:
                found += glob.glob(os.path.join(self.work, pattern.rstrip("/")), recursive=True)
        if not found:
            return 1, f"no files for the artifact {given.get('name')}\n"
        base = os.path.commonpath([p if os.path.isdir(p) else os.path.dirname(p) for p in found])
        into = os.path.join(self.run.artifacts, given.get("name", "artifact"))
        for path in found:
            target = os.path.join(into, os.path.relpath(path, base))
            if os.path.isdir(path):
                shutil.copytree(path, target, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(path, target)
        return 0, f"artifact {given.get('name')}: {len(found)} path(s)\n"

    def download(self, given):
        source = os.path.join(self.run.artifacts, given.get("name", ""))
        if not os.path.isdir(source):
            return 1, f"no artifact {given.get('name')} from an earlier job\n"
        into = os.path.join(self.work, given.get("path", ""))
        shutil.copytree(source, into, dirs_exist_ok=True)
        if os.geteuid() == 0:
            subprocess.run(["chown", "-R", f"{self.run.uid}:{self.run.gid}", into], check=True)
        return 0, f"artifact {given.get('name')} into {given.get('path', '.')}\n"

    def restore(self, given):
        """actions/cache: the folder kept under its key, back in place; saved at the job's end when there was none."""
        key = hashlib.sha256(given.get("key", "").encode()).hexdigest()[:24]
        kept = os.path.join(self.run.cache, key)
        paths = [p.strip() for p in given.get("path", "").splitlines() if p.strip()]
        self.saves.append((kept, paths))
        if os.path.isdir(kept):
            for p in paths:
                if os.path.exists(os.path.join(kept, p)):
                    shutil.copytree(os.path.join(kept, p), os.path.join(self.work, p), dirs_exist_ok=True)
            if os.geteuid() == 0:
                subprocess.run(["chown", "-R", f"{self.run.uid}:{self.run.gid}", self.work], check=True)
            return 0, f"cache {given.get('key')}: restored\n"
        return 0, f"cache {given.get('key')}: none yet\n"

    def save_caches(self):
        for kept, paths in self.saves:
            if os.path.isdir(kept):
                continue
            for p in paths:
                if os.path.isdir(os.path.join(self.work, p)):
                    shutil.copytree(os.path.join(self.work, p), os.path.join(kept, p), dirs_exist_ok=True)

    # -------------------------------------------------------------- the whole job
    def go(self):
        inst = self.inst
        minutes = int(inst.spec.get("timeout-minutes", 360))
        deadline = time.time() + minutes * 60
        began = time.time()
        self.write(f"== {inst.name} at {self.run.short}: names {self.prefix}-*, ports {self.block}-{self.block + PORTS_PER_JOB - 1}\n")
        try:
            self.prepare()
            for n, step in enumerate(inst.spec.get("steps", [])):
                name, outcome, took, out = self.step(n, step, deadline)
                self.write(f"\n---- {name}: {outcome} ({took:.0f} s)\n{out}")
                if outcome == "failure":
                    self.failed = True
                    self.run.say(f"FAIL {inst.name}: {name} ({took:.0f} s) -> {self.log}")
                if time.time() > deadline:
                    self.failed = True
                    self.run.say(f"FAIL {inst.name}: past its {minutes} minutes")
                    break
            if not self.failed:
                self.save_caches()
            outputs = {k: self.value(shown(v)) for k, v in (inst.spec.get("outputs") or {}).items()}
            inst.outputs = outputs
        except Exception:
            self.failed = True
            self.write(traceback.format_exc())
            self.run.say(f"FAIL {inst.name}: could not run ({traceback.format_exc().strip().splitlines()[-1]}) -> {self.log}")
        finally:
            self.clean()
        inst.result = "failure" if self.failed else "success"
        self.run.say(f"{'PASS' if not self.failed else 'FAIL'} {inst.name} ({time.time() - began:.0f} s)")

    def clean(self):
        """The runner, what the job's steps left running (by its names), and the job's images by its tag."""
        docker("rm", "-f", self.container, check=False)
        left = docker("ps", "-aq", "--filter", f"name=^{self.prefix}-", check=False).stdout.split()
        if left:
            docker("rm", "-f", *left, check=False)
        nets = docker("network", "ls", "-q", "--filter", f"name=^{self.prefix}-", check=False).stdout.split()
        if nets:
            docker("network", "rm", *nets, check=False)
        images = docker("images", "--format", "{{.Repository}}:{{.Tag}}", check=False).stdout.split()
        mine = [i for i in images if i.endswith(f":{self.prefix}")]
        if mine:
            docker("image", "rm", *mine, check=False)
        if not self.run.args.keep and os.path.isdir(self.dir):
            # As root here, or through a container for what the job's containers wrote as their own users.
            shutil.rmtree(self.dir, ignore_errors=True)
            if os.path.isdir(self.dir):
                docker("run", "--rm", "-v", f"{os.path.dirname(self.dir)}:/p", "--entrypoint", "rm", RUNNER_IMAGE,
                       "-rf", f"/p/{os.path.basename(self.dir)}", check=False)


def shell_quote(text):
    return "'" + text.replace("'", "'\"'\"'") + "'" if re.search(r"[^\w@%+=:,./-]", text) else text


def wanted_jobs(jobs, names):
    """The jobs asked for and every job they need, in the workflow's order."""
    if not names:
        return list(jobs)
    unknown = [n for n in names if n not in jobs]
    if unknown:
        sys.exit(f"no such job in ci.yml: {', '.join(unknown)} (there are {', '.join(jobs)})")
    found, todo = set(), list(names)
    while todo:
        name = todo.pop()
        if name not in found:
            found.add(name)
            todo += needs_of(jobs[name])
    return [j for j in jobs if j in found]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("jobs", nargs="*")
    parser.add_argument("--jobs", dest="parallel", type=int, default=4)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--prefix", default="odqci")
    parser.add_argument("--ports", default="18901-18960")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    if git("status", "--porcelain"):
        print("ci_local: the tree has changes that are not committed; CI runs the commit, and so does this", file=sys.stderr)
    # PyYAML here only, so that the rest (the expressions, the jobs' instances) imports without it (cli/tests/test_ci.py).
    try:
        import yaml
    except ImportError:
        sys.exit("ci_local.py needs PyYAML: apt install python3-yaml, or pip install pyyaml")
    run = Run(args)
    # The workflow as the commit has it, as GitHub reads it: not the working tree's.
    run.workflow = yaml.safe_load(git("show", f"{run.sha}:.github/workflows/ci.yml"))
    jobs = run.workflow["jobs"]
    names = wanted_jobs(jobs, args.jobs)
    run.instances = expand({j: jobs[j] for j in names})
    os.makedirs(run.artifacts, exist_ok=True)
    os.makedirs(run.cache, exist_ok=True)
    # The runner's image, made again only when its file changed (Docker's cache).
    built = subprocess.run(["docker", "build", "-q", "-t", RUNNER_IMAGE, "-f", os.path.join(ROOT, ".github", "ci-runner.Dockerfile"),
                            os.path.join(ROOT, ".github")], capture_output=True, text=True)
    if built.returncode:
        sys.exit("the runner's image did not build:\n" + built.stderr[-2000:])
    run.say(f"ci_local: {len(run.instances)} jobs of ci.yml at {run.short}, changes since {run.before[:7] or '(everything runs)'}; "
            f"logs in {run.folder}")
    began = time.time()
    pending = list(run.instances)
    running = {}
    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        while pending or running:
            for inst in list(pending):
                needs = [j for j in run.instances if j.job in needs_of(inst.spec)]
                if any(j.result is None for j in needs):
                    continue
                pending.remove(inst)
                if inst.windows():
                    inst.result = "skipped"
                    run.say(f"SKIP {inst.name}: it needs a Windows runner (CI runs it on GitHub)")
                    continue
                spec_if = inst.spec.get("if")
                # As on GitHub: a job whose needs did not all pass is skipped, unless its condition asks for always().
                if any(j.result != "success" for j in needs) and not re.search(r"\b(always|failure)\(\)", str(spec_if or "")):
                    inst.result = "skipped"
                    run.say(f"SKIP {inst.name}: a job it needs did not pass")
                    continue
                job = Job(run, inst)
                if spec_if and not condition(spec_if, job.context(), job.functions()):
                    inst.result = "skipped"
                    run.say(f"SKIP {inst.name}: {spec_if}")
                    continue
                block = run.take_ports()
                if block is None:
                    pending.insert(0, inst)
                    break
                job.place(block)
                running[inst] = (pool.submit(job.go), block)
                if len(running) >= args.parallel:
                    break
            for inst, (future, block) in list(running.items()):
                if future.done():
                    del running[inst]
                    run.give_ports(block)
            time.sleep(0.5)
    failed = [i.name for i in run.instances if i.result == "failure"]
    run.say(f"ci_local: {len(run.instances) - len(failed)} of {len(run.instances)} jobs passed or were skipped in "
            f"{time.time() - began:.0f} s{': failed ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
