#!/usr/bin/env python3
"""Minimal local server for presentations.

Each subdirectory of this folder is treated as one presentation. The root
page lists every presentation; clicking one opens its entry HTML file
(index.html if present, otherwise the first *.html file in the folder).

Includes live-reload: a tiny script is injected into served HTML pages and
the browser auto-refreshes when any file under the workspace changes.

Usage:
    python3 server.py                # serve on http://localhost:8000
    python3 server.py --port 9000
    python3 server.py --no-reload    # disable live-reload
"""

from __future__ import annotations

import argparse
import html
import os
import queue
import shutil
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent

LIVE_RELOAD_SCRIPT = b"""
<script>
(() => {
  if (window.__livereloadInstalled) return;
  window.__livereloadInstalled = true;
  let es;
  const connect = () => {
    es = new EventSource('/__reload');
    es.onmessage = (e) => { if (e.data === 'reload') location.reload(); };
    es.onerror = () => { try { es.close(); } catch (_) {} setTimeout(connect, 800); };
  };
  connect();
})();
</script>
"""

# Skip these when watching the tree.
_IGNORED_NAMES = {".DS_Store", "__pycache__", "server.py"}


def _is_ignored(path: Path) -> bool:
    for part in path.relative_to(ROOT).parts:
        if part.startswith(".") or part in _IGNORED_NAMES:
            return True
    return False


class FileWatcher(threading.Thread):
    """Polls mtimes under ROOT and notifies subscribers on change."""

    def __init__(self, interval: float = 0.3) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self._subscribers: list[queue.Queue[str]] = []
        self._lock = threading.Lock()
        self._snapshot = self._scan()

    def _scan(self) -> dict[str, float]:
        files: dict[str, float] = {}
        for p in ROOT.rglob("*"):
            if not p.is_file() or _is_ignored(p):
                continue
            try:
                files[str(p)] = p.stat().st_mtime
            except OSError:
                pass
        return files

    def subscribe(self) -> queue.Queue[str]:
        q: queue.Queue[str] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[str]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def run(self) -> None:
        while True:
            time.sleep(self.interval)
            current = self._scan()
            if current != self._snapshot:
                self._snapshot = current
                with self._lock:
                    subs = list(self._subscribers)
                for q in subs:
                    q.put("reload")


def find_entry(folder: Path) -> Path | None:
    """Return the HTML file to open for a presentation folder."""
    index = folder / "index.html"
    if index.is_file():
        return index
    htmls = sorted(p for p in folder.glob("*.html") if p.is_file())
    return htmls[0] if htmls else None


def list_presentations() -> list[tuple[str, str]]:
    """Return [(folder_name, entry_relative_url), ...] sorted by name."""
    items: list[tuple[str, str]] = []
    for entry in sorted(ROOT.iterdir(), key=lambda p: p.name.lower()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        target = find_entry(entry)
        if target is None:
            continue
        url = f"{entry.name}/" if target.name == "index.html" else f"{entry.name}/{target.name}"
        items.append((entry.name, url))
    return items


def render_index(presentations: list[tuple[str, str]]) -> bytes:
    cards = "\n".join(
        f'      <a class="card" href="{html.escape(url)}">'
        f'<span class="name">{html.escape(name)}</span>'
        f'<span class="arrow">→</span></a>'
        for name, url in presentations
    ) or '      <p class="empty">No presentations found. Add a folder with an HTML file.</p>'

    page = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Presentations</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect x='4' y='4' width='56' height='56' rx='12' fill='%23181b22' stroke='%23232732' stroke-width='2'/><rect x='14' y='18' width='36' height='22' rx='3' fill='none' stroke='%238a8f9c' stroke-width='2.5'/><rect x='20' y='28' width='36' height='22' rx='3' fill='%23181b22' stroke='%23e7e9ee' stroke-width='2.5'/></svg>" />
    <style>
      :root {{ color-scheme: light dark; }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
        background: #0f1115;
        color: #e7e9ee;
        display: flex;
        justify-content: center;
        padding: 8vh 24px;
      }}
      main {{ width: 100%; max-width: 720px; }}
      h1 {{
        font-size: 14px;
        font-weight: 500;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #8a8f9c;
        margin: 0 0 24px;
      }}
      .grid {{ display: grid; gap: 8px; }}
      .card {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 18px 20px;
        background: #181b22;
        border: 1px solid #232732;
        border-radius: 10px;
        text-decoration: none;
        color: inherit;
        transition: border-color .15s ease, transform .15s ease;
      }}
      .card:hover {{ border-color: #3a4150; transform: translateX(2px); }}
      .name {{ font-size: 17px; font-weight: 500; }}
      .arrow {{ color: #6b7280; font-size: 18px; }}
      .empty {{ color: #8a8f9c; }}
    </style>
  </head>
  <body>
    <main>
      <h1>Presentations</h1>
      <div class="grid">
{cards}
      </div>
    </main>
  </body>
</html>
"""
    return page.encode("utf-8")


def _inject_reload(body: bytes) -> bytes:
    """Insert the live-reload snippet just before </body>, or append it."""
    lower = body.lower()
    idx = lower.rfind(b"</body>")
    if idx == -1:
        return body + LIVE_RELOAD_SCRIPT
    return body[:idx] + LIVE_RELOAD_SCRIPT + body[idx:]


class PresentationHandler(SimpleHTTPRequestHandler):
    # Set by main() before serving.
    watcher: FileWatcher | None = None

    def do_GET(self) -> None:  # noqa: N802 (stdlib signature)
        if self.path == "/__reload":
            self._serve_sse()
            return

        if self.path in ("/", "/index.html"):
            body = render_index(list_presentations())
            if self.watcher is not None:
                body = _inject_reload(body)
            self._write_html(body)
            return

        if self.watcher is not None and self._is_html_path():
            self._serve_html_with_injection()
            return

        super().do_GET()

    def _is_html_path(self) -> bool:
        path = self.translate_path(self.path)
        p = Path(path)
        if p.is_dir():
            p = p / "index.html"
        return p.is_file() and p.suffix.lower() in {".html", ".htm"}

    def _serve_html_with_injection(self) -> None:
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            path = path / "index.html"
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404, "File not found")
            return
        body = _inject_reload(body)
        self._write_html(body)

    def _write_html(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self) -> None:
        if self.watcher is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q = self.watcher.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.watcher.unsubscribe(q)

    def end_headers(self) -> None:
        # Disable caching so edits show up on reload.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        if self.path == "/__reload":
            return
        super().log_message(format, *args)


def build_static(out_dir: Path) -> None:
    """Generate a static site for hosting (e.g. GitHub Pages)."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    presentations = list_presentations()
    ignore = shutil.ignore_patterns(*_IGNORED_NAMES, ".*")
    for name, _ in presentations:
        shutil.copytree(ROOT / name, out_dir / name, ignore=ignore)

    (out_dir / "index.html").write_bytes(render_index(presentations))
    # Tell GitHub Pages not to run Jekyll on our files.
    (out_dir / ".nojekyll").write_bytes(b"")

    print(f"Built {len(presentations)} presentation(s) to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve presentations locally.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable live-reload on file change.",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build a static site to --out and exit (no server).",
    )
    parser.add_argument(
        "--out",
        default="_site",
        help="Output directory for --build (default: _site).",
    )
    args = parser.parse_args()

    os.chdir(ROOT)

    if args.build:
        out = Path(args.out)
        if not out.is_absolute():
            out = ROOT / out
        build_static(out)
        return

    watcher: FileWatcher | None = None
    if not args.no_reload:
        watcher = FileWatcher()
        watcher.start()
    PresentationHandler.watcher = watcher

    handler = partial(PresentationHandler, directory=str(ROOT))
    with ThreadingHTTPServer((args.host, args.port), handler) as httpd:
        url = f"http://{args.host}:{args.port}/"
        print(f"Serving presentations from {ROOT}")
        print(f"Live-reload: {'on' if watcher else 'off'}")
        print(f"Open {url}  (Ctrl+C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nBye.")


if __name__ == "__main__":
    main()
