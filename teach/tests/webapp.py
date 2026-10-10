"""Minimal web app for browser E2E tests: login, then a form; submissions are kept in memory."""

import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOGIN = """<!doctype html><title>Login</title>
<form method=post action=/login>
<input id=user name=user placeholder=Login>
<input id=pass name=pass type=password>
<button type=submit>Sign in</button></form>"""

FORM = """<!doctype html><title>Order</title>
<form method=post action=/submit>
<input name=customer aria-label=Customer>
<select name=delivery><option>courier</option><option>pickup</option></select>
<label><input type=checkbox name=express id=express> Express</label>
<label><input type=checkbox name=gift id=gift> Gift wrap</label>
<button type=submit>Place order</button></form>"""


def serve():
    submissions = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, code=200, headers=None):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            if self.path.startswith("/form"):
                if "session=ok" not in self.headers.get("Cookie", ""):
                    return self._send("", 302, {"Location": "/"})
                return self._send(FORM)
            return self._send(LOGIN)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            data = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(n).decode()).items()}
            if self.path == "/login":
                if data.get("user") and data.get("pass") == "pw-" + data["user"]:
                    return self._send("", 302, {"Location": "/form", "Set-Cookie": "session=ok"})
                return self._send("bad login", 403)
            submissions.append(data)
            return self._send("<title>Saved</title><p>Order saved</p>")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", submissions
