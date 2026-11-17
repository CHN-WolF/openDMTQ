"""A stand-in chat for the pages' tests (run.sh starts it in a container beside the admin service): it takes the admin
service's webhook messages as Discord and Slack would, and the browser asks it what came. No message leaves the test's own
network.

    python3 chat.py [port]

POST anywhere: the message is kept and the answer is 204, as a chat that took it; a path with /gone in it answers 404, as
Discord does for a webhook deleted there. GET /got: every message kept, as JSON [{"path", "body"}]."""

import http.server
import json
import sys
import threading

# What came, in order, for GET /got.
GOT = []
LOCK = threading.Lock()


class Chat(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        # The body as the admin service sent it: JSON.
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {"unreadable": raw.decode("utf-8", "replace")}
        with LOCK:
            GOT.append({"path": self.path, "body": body})
        # A webhook deleted in the chat: Discord's answer to it.
        if "/gone" in self.path:
            self.answer(404, {"message": "Unknown Webhook", "code": 10015})
        else:
            self.answer(204, None)

    def do_GET(self):
        if self.path.split("?")[0] != "/got":
            self.answer(404, {"message": "nothing here"})
            return
        with LOCK:
            self.answer(200, list(GOT))

    def answer(self, status, body):
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        # Quiet: the suite's own output says what matters.
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    http.server.ThreadingHTTPServer(("0.0.0.0", port), Chat).serve_forever()
