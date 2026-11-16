"""A stand-in for GitHub's releases of one repository, over plain HTTP, for tests/release/update.sh.

    python3 github_stub.py ROOT PORT LOG

ROOT holds one folder per release, named by its tag (v0.10.0, v0.11.0), with the release's files in it; the tags'
order by version is the order they were published in. It answers what the programs that read releases ask:

  GET  /api/v3/repos/<owner>/<repo>/releases           the releases' list as GitHub's API gives it (Velopack's GitHub
                                                        source asks GitHub Enterprise's /api/v3 for a host that is not
                                                        github.com: the same code as for github.com, past the address)
  GET  /<owner>/<repo>/releases/download/<tag>/<file>   a release's file
  HEAD /<owner>/<repo>/releases/latest                  a redirect to the latest tag's page (the servers' tools ask so)
  GET  /<owner>/<repo>/releases/tag/<tag>               that page
  GET  /feed/<file>                                     the latest release's files as one folder (Velopack's HTTP source)

Every request goes into LOG as "METHOD path", one a line, for the test to read which names were asked for.
"""
import http.server
import json
import os
import re
import sys
import urllib.parse

ROOT, PORT, LOG = sys.argv[1], int(sys.argv[2]), sys.argv[3]


def tags():
    """The releases' tags, the newest first: by the numbers in them (v0.11.0 after v0.9.0)."""
    found = [t for t in os.listdir(ROOT) if os.path.isdir(os.path.join(ROOT, t))]
    return sorted(found, key=lambda t: tuple(int(n) for n in re.findall(r"[0-9]+", t)), reverse=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_request(self, code="-", size="-"):
        # One line per request, in the file the test reads; nothing on the console.
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{self.command} {self.path}\n")

    def base(self):
        """This server's address as the client reached it."""
        return f"http://{self.headers.get('Host')}"

    def send(self, code, body=b"", kind="application/octet-stream", headers=()):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        # A HEAD request has the headers alone.
        if self.command != "HEAD":
            self.wfile.write(body)

    def file(self, path):
        """A release's file, or 404."""
        if not os.path.isfile(path):
            return self.send(404, b"not found", "text/plain")
        with open(path, "rb") as f:
            self.send(200, f.read())

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        newest = tags()
        m = re.fullmatch(r"/api/v3/repos/([^/]+)/([^/]+)/releases", path)
        if m:
            owner, repo = m.groups()
            releases = []
            # The newest published last: its time is the latest.
            for i, tag in enumerate(newest):
                files = sorted(os.listdir(os.path.join(ROOT, tag)))
                releases.append({
                    "name": tag, "tag_name": tag, "prerelease": False,
                    "published_at": f"2026-11-{17 - i:02d}T12:00:00Z",
                    "assets": [{"name": n, "url": f"{self.base()}/api/v3/repos/{owner}/{repo}/releases/assets/{tag}/{n}",
                                "browser_download_url": f"{self.base()}/{owner}/{repo}/releases/download/{tag}/{n}"}
                               for n in files]})
            return self.send(200, json.dumps(releases).encode(), "application/json")
        m = re.fullmatch(r"/[^/]+/[^/]+/releases/download/([^/]+)/([^/]+)", path)
        if m:
            return self.file(os.path.join(ROOT, *m.groups()))
        m = re.fullmatch(r"/([^/]+)/([^/]+)/releases/latest", path)
        if m:
            owner, repo = m.groups()
            return self.send(302, headers=[("Location", f"{self.base()}/{owner}/{repo}/releases/tag/{newest[0]}")])
        if re.fullmatch(r"/[^/]+/[^/]+/releases/tag/[^/]+", path):
            return self.send(200, b"<html>a release</html>", "text/html")
        m = re.fullmatch(r"/feed/([^/]+)", path)
        if m:
            return self.file(os.path.join(ROOT, newest[0], m.group(1)))
        self.send(404, b"not found", "text/plain")


http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
