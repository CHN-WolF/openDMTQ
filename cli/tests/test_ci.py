"""CI's own pieces: which changes skip the heavy jobs (.github/changes.py), the workflow's jobs and parts (ci.yml) against
the suites they split, and the runner of CI's jobs on a computer of one's own (.github/ci_local.py). The standard
library only: the workflow is read as text, as the runner of CI's jobs is the one that needs PyYAML."""

import importlib.util
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def load(name):
    """A module of .github by its file's name."""
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, ".github", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def jobs_of(workflow):
    """{job: its text} of a workflow, by its two-space indented keys under jobs:."""
    body = workflow.split("\njobs:\n", 1)[1]
    found = re.split(r"^  ([a-z0-9-]+):\n", body, flags=re.M)
    return dict(zip(found[1::2], found[2::2]))


class ChangesTest(unittest.TestCase):
    """DEP-87: a change to the guides alone skips the heavy jobs; anything else, or nothing to go by, runs them."""

    def setUp(self):
        self.changes = load("changes")

    def test_the_guides_alone_are_no_code(self):
        self.assertFalse(self.changes.code(["README.md", "docs/testing.md", "docs/images/fig-testing-gates.svg",
                                            "CONTRIBUTING.md", ".github/ISSUE_TEMPLATE/bug.yml"]))

    def test_anything_else_is_code(self):
        for paths in (["tools/opendmtq_tools/songs.py"], ["docs/testing.md", "tests/qa.sh"], ["CHANGELOG.md"],
                      # A guide a heavy job's test reads: the PC client's unit tests hold the launcher to its table.
                      ["docs/windows-player.md"],
                      # Read into the installer, though they are words.
                      ["client/opendmtq_client/assets/fonts/README.md"], ["LICENSE"], []):
            self.assertTrue(self.changes.code(paths), paths)

    def test_a_base_that_cannot_be_told_runs_everything(self):
        # A branch's first push (GitHub's zeros), a release's tag (no base), a history written again (a base not there).
        for base in ("0" * 40, "", "f" * 40):
            self.assertIsNone(self.changes.changed(base, "HEAD"), base)
        out = subprocess.run([sys.executable, os.path.join(ROOT, ".github", "changes.py"), "0" * 40, "HEAD"],
                             capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(out.stdout.strip(), "code=true")

    def test_every_pattern_names_files_there_are(self):
        # A pattern that names nothing would be a guide moved away, and whatever came in its place would be skipped.
        try:
            files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, cwd=ROOT).stdout.split("\n")
        except OSError:
            files = []
        if not any(files):
            self.skipTest("no git checkout here (the oldest Python's image has no git)")
        for pattern in self.changes.GUIDES:
            self.assertTrue(any(self.changes.fnmatch.fnmatchcase(f, pattern) for f in files), pattern)

    def test_the_heavy_jobs_wait_for_the_changes_job(self):
        jobs = jobs_of(read(".github", "workflows", "ci.yml"))
        for name, text in jobs.items():
            if name in ("changes", "test"):
                continue
            needs = re.search(r"^    needs: (\S+)", text, re.M)
            self.assertIsNotNone(needs, f"{name} runs on a change to the guides alone")
            if needs.group(1) == "changes":
                self.assertIn("if: needs.changes.outputs.code == 'true'", text, name)
            else:
                # After a job that is itself skipped on the guides alone.
                self.assertIn(needs.group(1), jobs, name)


class WorkflowTest(unittest.TestCase):
    """DEP-87: the workflow's parts cover what they split, each part once."""

    def setUp(self):
        self.jobs = jobs_of(read(".github", "workflows", "ci.yml"))

    def test_the_pages_parts_take_every_stage_once(self):
        # Every stage tests/ui/run.sh has, in one part of the ui job and only one: a stage left out would never run in CI.
        script = read("tests", "ui", "run.sh")
        stages = set(re.findall(r"^\s*stage ([a-z]+)$", script, re.M)) | set(re.findall(r"^if wanted ([a-z]+);", script, re.M))
        stages -= {"self"}
        parts = re.findall(r"^          - ([a-z ]+)$", self.jobs["ui"], re.M)
        taken = [s for part in parts for s in part.split()]
        self.assertEqual(sorted(taken), sorted(set(taken)), "a stage in two parts")
        self.assertEqual(set(taken), stages)
        # In each part, the stages in the order the script takes them.
        order = [m for m in re.findall(r"^\s*(?:stage|if wanted) ([a-z]+)", script, re.M) if m != "self"]
        for part in parts:
            names = part.split()
            self.assertEqual(names, sorted(names, key=order.index), part)

    def test_the_launcher_parts_take_both_languages(self):
        self.assertIn("lang: [en, ko]", self.jobs["client"])
        self.assertIn('client/tests/ui/run.sh "$PWD/_work/client-ui" ${{ matrix.lang }}', self.jobs["client"])

    def test_every_action_is_one_the_local_runner_does(self):
        # A new action in the workflow is one ci_local.py cannot do yet: it says so in a run, and this says so first.
        known = ("actions/checkout", "docker/setup-buildx-action", "docker/setup-qemu-action", "actions/setup-python",
                 "azure/setup-helm", "docker/build-push-action", "actions/upload-artifact", "actions/download-artifact",
                 "actions/cache")
        for name, text in self.jobs.items():
            for uses in re.findall(r"uses: ([\w./-]+)@", text):
                self.assertIn(uses, known, name)


class LocalRunnerTest(unittest.TestCase):
    """DEP-87: GitHub's expressions as ci_local.py reads them, and the jobs' instances it makes."""

    def setUp(self):
        self.ci = load("ci_local")
        self.context = {"github": {"event_name": "push", "event": {"before": "abc123"}, "ref": "refs/heads/main"},
                        "needs": {"changes": {"result": "success", "outputs": {"code": "true"}}},
                        "matrix": {"lang": "en"}, "env": {"TAG": "uitest"}, "strategy": {"job-index": 2}}
        self.functions = {"startsWith": lambda a, b: str(a).lower().startswith(str(b).lower()), "always": lambda: True}

    def value(self, text):
        return self.ci.Expression(text, self.context, self.functions).value()

    def test_the_workflows_expressions(self):
        self.assertTrue(self.value("needs.changes.outputs.code == 'true'"))
        self.assertEqual(self.value("github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event.before"),
                         "abc123")
        self.assertTrue(self.value("!startsWith(github.ref, 'refs/tags/')"))
        self.assertTrue(self.value("matrix.lang == 'en'"))
        self.assertEqual(self.ci.substitute("opendmtq-server:${{ env.TAG }}", self.context, self.functions), "opendmtq-server:uitest")
        self.assertEqual(self.ci.substitute("ui-report-${{ strategy.job-index }}", self.context, self.functions), "ui-report-2")
        self.context["needs"]["changes"]["outputs"]["code"] = "false"
        self.assertFalse(self.ci.condition("needs.changes.outputs.code == 'true'", self.context, self.functions))
        self.assertTrue(self.ci.condition("${{ always() }}", self.context, self.functions))

    def test_a_matrix_makes_one_instance_each(self):
        jobs = {"client": {"strategy": {"matrix": {"lang": ["en", "ko"]}}},
                "ui": {"strategy": {"matrix": {"stages": ["empty full", "flows mine"]}}}, "test": {}}
        names = [i.name for i in self.ci.expand(jobs)]
        self.assertEqual(names, ["client (en)", "client (ko)", "ui (empty full)", "ui (flows mine)", "test"])


if __name__ == "__main__":
    unittest.main()
