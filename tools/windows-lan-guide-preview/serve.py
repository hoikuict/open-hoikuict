"""Serve only this disconnected prototype on loopback. No API or data access."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
FILES = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
         "/base.css": ("base.css", "text/css"), "/preview.css": ("preview.css", "text/css"),
         "/wizard.js": ("wizard.js", "text/javascript"),
         "/guide.js": ("guide.js", "text/javascript"), "/guide.css": ("guide.css", "text/css")}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Host") not in {"127.0.0.1:18850", "localhost:18850"}:
            self.send_error(403)
            return
        entry = FILES.get(urlsplit(self.path).path)
        if not entry:
            self.send_error(404)
            return
        name, mime = entry
        body = (ROOT / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'none'; form-action 'none'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("LAN guide preview: http://127.0.0.1:18850/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 18850), Handler).serve_forever()
