"""Serve existing QA site artifacts with loopback-only resource restrictions."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread

AXE = Path("/private/tmp/amw-qa-browser/node_modules/axe-core/axe.min.js")
QA_SCRIPTS = b"""<script src="/__qa_axe.js"></script><script>
window.addEventListener('load', async function () {
  const result = await axe.run(document, {runOnly: {type: 'tag', values:
    ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}});
  const report = document.createElement('script');
  report.type = 'application/json'; report.id = 'qa-axe-result';
  report.textContent = JSON.stringify(result); document.body.appendChild(report);
});</script>"""


class LocalOnlyHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/__qa_shutdown":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"QA server stopping")
            Thread(target=self.server.shutdown, daemon=True).start()
            return
        return super().do_GET()

    def send_head(self):
        file_path = Path(self.translate_path(self.path))
        if file_path.is_dir():
            file_path = file_path / "index.html"
        if self.path == "/__qa_axe.js":
            payload, kind = AXE.read_bytes(), "text/javascript"
        elif file_path.is_file() and file_path.suffix == ".html":
            payload = file_path.read_bytes().replace(b"</head>", QA_SCRIPTS + b"</head>")
            kind = "text/html"
        else:
            return super().send_head()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        return BytesIO(payload)

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self' data: blob:; connect-src 'self'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "object-src 'none'; frame-src 'none'; form-action 'self'; base-uri 'self'",
        )
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format, *args):
        pass


def main():
    root = Path(__file__).resolve().parents[3]
    site = ThreadingHTTPServer(
        ("127.0.0.1", 8769),
        partial(LocalOnlyHandler, directory="/private/tmp/amw-qa-site-dist"),
    )
    dashboard = ThreadingHTTPServer(
        ("127.0.0.1", 8770),
        partial(LocalOnlyHandler, directory=str(root / "static")),
    )
    Thread(target=dashboard.serve_forever, daemon=True).start()
    print("Local CSP+axe servers: 127.0.0.1:8769 and 127.0.0.1:8770", flush=True)
    site.serve_forever()


if __name__ == "__main__":
    main()
