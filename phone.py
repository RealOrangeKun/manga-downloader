"""Send to your phone: a small web server on the home Wi-Fi that hands chosen files to a phone's browser.

The address carries a random token, only the files picked in the app are served, and the server
stops when the app says so. Each phone gets a cookie, so it sees only what it saved itself. No Qt
here; the GUI hears about visits and progress through `on_event`.
"""

from __future__ import annotations

import html
import json
import secrets
import socket
import threading
import time
import zipfile
from string import Template
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import paths

COOKIE = "nyanga_device"
PORT = 8765  # tried first so the address stays the same between shares; any free port otherwise
CHUNK = 256 * 1024
TYPES = {".cbz": "application/vnd.comicbook+zip", ".epub": "application/epub+zip", ".pdf": "application/pdf",
         ".zip": "application/zip"}
TIPS = {".cbz": "CBZ files open in a comic reader app ✿", ".epub": "EPUB files open in Books or any ebook app ✿",
        ".zip": "Folders come as zips of pictures, a comic reader app opens them ✿"}


def local_ip() -> str | None:
    """This computer's address on the local network, or None when it isn't on one."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.168.0.1", 9))  # picks the outgoing interface; nothing is sent
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") or ip.startswith("0.") else ip


def device_kind(agent: str) -> str:
    """A friendly name for a device from its browser's User-Agent."""
    if "iPad" in agent:
        return "iPad"
    if "iPhone" in agent or "iPod" in agent:
        return "iPhone"
    if "Android" in agent:
        return "Android phone" if "Mobile" in agent else "Android tablet"
    if "Macintosh" in agent:
        return "iPad or Mac"  # iPads ask for the desktop page and look just like a Mac
    if "Windows" in agent:
        return "Windows PC"
    return "Computer" if ("Linux" in agent or "CrOS" in agent) else "Phone"


def folder_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file())


def size_of(path: Path) -> int:
    if path.is_dir():
        return sum(p.stat().st_size for p in folder_files(path))
    return path.stat().st_size


def download_name(path: Path) -> str:
    """What the phone saves it as: an image folder becomes a zip."""
    return path.name + ".zip" if path.is_dir() else path.name


class _Writer:
    """A write-only stream for zipfile that counts what goes through (a socket can't seek).
    With no `out` it only counts, to measure a zip before sending it."""

    def __init__(self, out=None):
        self.out, self.pos = out, 0
        self.count: Callable[[int], None] = lambda n: None

    def write(self, data) -> int:
        if self.out:
            self.out.write(data)
        self.pos += len(data)
        self.count(len(data))
        return len(data)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        if self.out:
            self.out.flush()


_ZEROS = bytes(CHUNK)


def write_zip(out: _Writer, items: list[Path], dry: bool = False,
              starting: Callable[[int], None] = lambda k: None, finished: Callable[[int], None] = lambda k: None) -> None:
    """Zip `items` (files, or folders with what's in them) into `out`, stored as is: the pictures
    are already compressed. A dry run writes zeros instead of the files: same size, nothing read."""
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
        for k, item in enumerate(items):
            starting(k)
            for f in folder_files(item) if item.is_dir() else [item]:
                info = zipfile.ZipInfo(str(f.relative_to(item.parent)), time.localtime(f.stat().st_mtime)[:6])
                info.file_size = f.stat().st_size  # so zip64 (which old unzip apps trip over) is only used for huge files
                with zf.open(info, "w") as dst:
                    if dry:
                        left = f.stat().st_size
                        while left:
                            dst.write(memoryview(_ZEROS)[:min(left, CHUNK)])
                            left -= min(left, CHUNK)
                    else:
                        with f.open("rb") as src:
                            while chunk := src.read(CHUNK):
                                dst.write(chunk)
            finished(k)


def zip_size(items: list[Path]) -> int:
    """The exact size write_zip will send, so the phone can show progress and time left."""
    sink = _Writer()
    write_zip(sink, items, dry=True)
    return sink.pos


class Share:
    """Serves `files` (any of them can be switched off with `allowed`) until stop()."""

    def __init__(self, title: str, files: list[Path], cover: Path | None,
                 on_event: Callable[[str, int, int, int, str], None], logo: str = ""):
        self.title = title
        self.logo = logo  # the app icon's SVG, shown on the page (theme.py has it; no Qt here)
        self.files = files
        self.cover = cover if cover and cover.exists() else None
        self.allowed: set[int] = set(range(len(files)))
        self.devices: dict[str, str] = {}  # cookie -> "iPhone", "Android phone 2"...
        self.sent: dict[str, set[int]] = {}  # per device: files sent in full, shown as saved on that phone
        self.lock = threading.Lock()
        # (kind, file index, bytes sent, file size, device name): kind is "visit", "progress", "done"
        # or "cancelled"; a visit has index -1
        self.on_event = on_event
        self.token = secrets.token_urlsafe(6)
        self.last_activity = time.monotonic()
        self.server: ThreadingHTTPServer | None = None
        self.clients: set[socket.socket] = set()  # open connections: phones keep theirs open between requests
        self.url = ""

    def start(self) -> str | None:
        """Start serving; returns the address for the phone, or None if there's no network."""
        ip = local_ip()
        if not ip:
            return None
        handler = type("Handler", (_Handler,), {"share": self})
        try:
            self.server = ThreadingHTTPServer(("0.0.0.0", PORT), handler)
        except OSError:
            self.server = ThreadingHTTPServer(("0.0.0.0", 0), handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://{ip}:{self.server.server_address[1]}/{self.token}/"
        return self.url

    def stop(self) -> None:
        """Stop for everyone: no new phones, and the connections phones already have are cut too
        (downloads under way included), or they'd carry on being answered."""
        if self.server:
            server, self.server = self.server, None
            with self.lock:
                clients, self.clients = list(self.clients), set()
            for sock in clients:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass  # already gone
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True).start()

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    # ---- the page

    def device(self, cookie: str, agent: str) -> str:
        """The cookie for this device, new if it hasn't been seen yet, with a name worked out once."""
        with self.lock:
            if cookie not in self.devices:
                cookie = secrets.token_urlsafe(9)
                kind = device_kind(agent)
                same = sum(1 for name in self.devices.values() if name.rsplit(" ", 1)[0] == kind or name == kind)
                self.devices[cookie] = f"{kind} {same + 1}" if same else kind
            return cookie

    def state(self, device: str) -> dict:
        return {"allowed": sorted(self.allowed), "sent": sorted(self.sent.get(device, ()))}

    def finished(self, i: int, device: str) -> None:
        with self.lock:
            self.sent.setdefault(device, set()).add(i)
        total = size_of(self.files[i])
        self.on_event("done", i, total, total, self.devices[device])

    def page(self, device: str) -> str:
        cards = []
        for i, f in enumerate(self.files):
            name = html.escape(download_name(f))
            cover = '<img src="cover" alt="">' if self.cover else '<div class="nocover">✦</div>'
            cards.append(f'<a class="file" data-i="{i}" href="f/{i}" download hidden>{cover}'
                         f'<span class="info"><b>{name}</b><small>{_fmt_size(size_of(f))}</small></span>'
                         f'<span class="save">Save</span></a>')
        kinds = {Path(download_name(f)).suffix.lower() for f in self.files}
        tips = "".join(f"<p class='tip'>{TIPS[k]}</p>" for k in sorted(kinds) if k in TIPS)
        return PAGE.replace("$cards", "\n".join(cards)).replace("$tips", tips) \
            .replace("$state", json.dumps(self.state(device))).replace("$title", html.escape(self.title))


class _Handler(BaseHTTPRequestHandler):
    share: Share
    protocol_version = "HTTP/1.1"
    sending: int | None = None  # the file going out right now, to tell the app if the phone stops it
    device = ""  # this request's device cookie, and its name
    name = ""

    def log_message(self, *args) -> None:
        pass

    def setup(self) -> None:
        super().setup()
        with self.share.lock:
            self.share.clients.add(self.connection)

    def finish(self) -> None:
        with self.share.lock:
            self.share.clients.discard(self.connection)
        try:
            super().finish()
        except OSError:
            pass  # cut by stop()

    def do_GET(self) -> None:
        share = self.share
        if share.server is None:  # stopped: hang up without an answer, so the page says sharing stopped
            self.close_connection = True
            return
        prefix = f"/{share.token}/"
        if not self.path.startswith(prefix):
            return self._send(404, b"Not here", "text/plain")
        share.touch()
        route = self.path[len(prefix):].split("?")[0]
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        known = cookie[COOKIE].value if COOKIE in cookie else ""
        self.device = share.device(known, self.headers.get("User-Agent", ""))
        self.name = share.devices[self.device]
        try:
            if route == "":
                share.on_event("visit", -1, 0, 0, self.name)
                self._send(200, share.page(self.device).encode(), "text/html; charset=utf-8",
                           cookie=None if known == self.device else self.device)
            elif route == "state":
                self._send(200, json.dumps(share.state(self.device)).encode(), "application/json")
            elif route == "logo.svg" and share.logo:
                self._send(200, share.logo.encode(), "image/svg+xml", cache=True)
            elif route == "cover" and share.cover:
                data = share.cover.read_bytes()
                self._send(200, data, _image_type(data), cache=True)
            elif route.startswith("font/") and route[5:] in ("400", "600"):
                font = paths.BUNDLE / "assets" / "fonts" / f"Fredoka-{route[5:]}.ttf"
                self._send(200, font.read_bytes(), "font/ttf", cache=True)
            elif route.startswith("f/") and route[2:].isdigit() and int(route[2:]) in share.allowed \
                    and int(route[2:]) < len(share.files):
                self._file(int(route[2:]))
            elif route == "all.zip" and share.allowed:
                self._all()
            else:
                self._send(404, PAGE_GONE.encode(), "text/html; charset=utf-8")
        except OSError:  # the phone cancelled or lost the Wi-Fi (reset, broken pipe, aborted on Windows)
            self.close_connection = True
            if self.sending is not None:
                share.on_event("cancelled", self.sending, 0, 0, self.name)

    def _send(self, code: int, data: bytes, kind: str, cache: bool = False, cookie: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", kind)
        if cookie:  # kept a month: the same phone keeps its name if it comes back while sharing
            self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age=2592000; SameSite=Lax")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _attachment(self, name: str, kind: str, length: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", kind)
        plain = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in name)  # for old browsers
        self.send_header("Content-Disposition", f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}")
        self.send_header("Content-Length", str(length))
        self.end_headers()

    def _counter(self, i: int, total: int) -> Callable[[int], None]:
        """Tells the app how far file i has got, every megabyte or so."""
        share, sent = self.share, [0, 0]  # bytes, bytes when last reported

        def count(n: int) -> None:
            sent[0] += n
            share.touch()
            if sent[0] - sent[1] >= 1024 * 1024:
                sent[1] = sent[0]
                share.on_event("progress", i, min(sent[0], total), total, self.name)
        return count

    def _file(self, i: int) -> None:
        share, path = self.share, self.share.files[i]
        total = size_of(path)
        self.sending = i
        if path.is_dir():
            self._attachment(download_name(path), TYPES[".zip"], zip_size([path]))
            out = _Writer(self.wfile)
            out.count = self._counter(i, total)
            write_zip(out, [path])
        else:
            self._attachment(path.name, TYPES.get(path.suffix.lower(), "application/octet-stream"), total)
            count = self._counter(i, total)
            with path.open("rb") as fh:
                while chunk := fh.read(CHUNK):
                    self.wfile.write(chunk)
                    count(len(chunk))
        self.wfile.flush()
        self.sending = None
        share.finished(i, self.device)

    def _all(self) -> None:
        share = self.share
        chosen = [i for i in sorted(share.allowed) if i < len(share.files)]
        items = [share.files[i] for i in chosen]
        self._attachment(f"{share.title}.zip", TYPES[".zip"], zip_size(items))
        out = _Writer(self.wfile)

        def starting(k: int) -> None:
            self.sending = chosen[k]
            out.count = self._counter(chosen[k], size_of(items[k]))

        def finished(k: int) -> None:
            self.sending = None
            share.finished(chosen[k], self.device)

        write_zip(out, items, starting=starting, finished=finished)
        self.wfile.flush()


def _image_type(data: bytes) -> str:
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return ""


# The phone page is written for old devices too (Safari on iOS 9, old Android): plain colors rather
# than CSS variables, margins rather than flex gap, and ES5 JavaScript with XMLHttpRequest.
_COLORS = {
    "light": {"text": "#5a2a41", "muted": "#a86b88", "accent": "#e0457f", "bg": "#fff0f6", "card": "#ffffff",
              "border": "#ffd6e7", "button": "#ffe3ef"},
    "dark": {"text": "#f6dbe8", "muted": "#c08aa5", "accent": "#ff8fbf", "bg": "#1d1420", "card": "#291d2b",
             "border": "#3d2a3e", "button": "#3a2338"},
}
_COLORED = Template("""
body { background: $bg; color: $text; }
h1 { color: $accent; }
.sub, .info small, .tip, .count, .pager span { color: $muted; }
.file { background: $card; border-color: $border; }
.nocover, .file img { background: $button; color: $accent; }
.file.saved .save, .pager button { background: $button; color: $accent; }
""")

_STYLE = """
@font-face { font-family: Fredoka; font-weight: 400; src: url(font/400); }
@font-face { font-family: Fredoka; font-weight: 600; src: url(font/600); }
* { box-sizing: border-box; -webkit-box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; padding: 28px 16px 40px;
       font-family: Fredoka, -apple-system, "Helvetica Neue", Helvetica, Roboto, Arial, sans-serif;
       -webkit-tap-highlight-color: transparent; }
main { display: block; max-width: 480px; margin: 0 auto; }
[hidden] { display: none !important; }
header { display: block; text-align: center; margin-bottom: 22px; }
.cat { width: 76px; height: 76px; }
h1 { font-size: 26px; font-weight: 600; margin: 4px 0 2px; }
.sub { margin: 0; font-size: 17px; }
.file { display: -webkit-box; display: -webkit-flex; display: flex;
        -webkit-box-align: center; -webkit-align-items: center; align-items: center;
        padding: 12px; margin-bottom: 12px; border: 1px solid; border-radius: 18px;
        color: inherit; text-decoration: none; }
.file img, .nocover { width: 52px; height: 74px; border-radius: 10px; object-fit: cover;
        -webkit-flex: none; flex: none; text-align: center; line-height: 74px; font-size: 22px; }
.info { -webkit-box-flex: 1; -webkit-flex: 1; flex: 1; min-width: 0; margin: 0 14px; }
.info b { display: block; font-weight: 600; word-wrap: break-word; overflow-wrap: break-word; }
.info small { font-size: 14px; }
.save, .all { background-color: #ff6fa6; background-image: -webkit-linear-gradient(left, #ff7eb3, #ff5c9a);
        background-image: linear-gradient(90deg, #ff7eb3, #ff5c9a); color: #fff; font-weight: 600;
        border-radius: 14px; padding: 10px 18px; -webkit-flex: none; flex: none; text-decoration: none; }
.all { display: block; text-align: center; margin: 0 0 8px; padding: 14px; font-size: 17px; }
.count { text-align: center; font-size: 15px; margin: 0 0 16px; min-height: 1em; }
.pager { text-align: center; margin: 6px 0 4px; }
.pager button { font-family: inherit; font-size: 22px; font-weight: 600; width: 46px; height: 46px; border: 0;
        border-radius: 14px; vertical-align: middle; -webkit-appearance: none; }
.pager button[disabled] { opacity: .35; }
.pager span { display: inline-block; min-width: 96px; margin: 0 12px; vertical-align: middle; }
.tip { text-align: center; font-size: 14px; margin: 14px 0 0; }
.gone { display: none; text-align: center; margin-top: 30vh; }
body.stopped main { display: none; }
body.stopped .gone { display: block; }
""" + _COLORED.substitute(_COLORS["light"]) + \
    "@media (prefers-color-scheme: dark) {" + _COLORED.substitute(_COLORS["dark"]) + "}\n"

_CAT = '<img class="cat" src="logo.svg" alt="">'

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title · Nyanga</title><link rel="icon" href="logo.svg"><style>""" + _STYLE + """</style></head>
<body><main>
<header>""" + _CAT + """<h1>Nyanga ✦</h1><p class="sub">$title</p></header>
<a class="all" id="all" href="all.zip" download hidden>Save all as one zip</a>
<p class="count" id="count"></p>
<div id="list">
$cards
</div>
<div class="pager" id="pager" hidden><button id="prev" aria-label="Previous page">‹</button><span
id="where"></span><button id="next" aria-label="Next page">›</button></div>
<p class="tip" id="old" hidden>Your device will ask which app to open each file with ✿</p>
$tips
</main>
<div class="gone">""" + _CAT + """<h1>Sharing stopped ✿</h1>
<p class="sub">Open Send to your phone on your computer again</p></div>
<script>
var PER = 10;  // files per page
var state = $state, page = 0, misses = 0;
var cards = Array.prototype.slice.call(document.querySelectorAll(".file"));

function el(id) { return document.getElementById(id); }
function num(a) { return parseInt(a.getAttribute("data-i"), 10); }
function has(list, n) { return list.indexOf(n) !== -1; }

function show() {
  var shown = cards.filter(function (a) { return has(state.allowed, num(a)); });
  var pages = Math.max(1, Math.ceil(shown.length / PER));
  var saved = 0, i;
  page = Math.min(page, pages - 1);
  for (i = 0; i < cards.length; i++) {
    var done = has(state.sent, num(cards[i]));
    cards[i].className = done ? "file saved" : "file";
    cards[i].querySelector(".save").textContent = done ? "Saved ✦" : "Save";
    cards[i].hidden = true;
  }
  for (i = 0; i < shown.length; i++) {
    if (has(state.sent, num(shown[i]))) saved++;
    if (i >= page * PER && i < (page + 1) * PER) shown[i].hidden = false;
  }
  el("pager").hidden = pages < 2;
  el("where").textContent = "Page " + (page + 1) + " of " + pages;
  el("prev").disabled = page === 0;
  el("next").disabled = page >= pages - 1;
  el("all").hidden = shown.length < 2;
  el("all").textContent = "Save all " + shown.length + " as one zip";
  el("count").textContent = !saved ? "" : saved === shown.length ? "All saved ♥" : saved + " of " + shown.length + " saved ✦";
}

function turn(by) {
  page += by;
  show();
  var list = el("list");
  if ("scrollBehavior" in document.documentElement.style) list.scrollIntoView({behavior: "smooth", block: "start"});
  else list.scrollIntoView(true);  // older browsers: jump instead of gliding
}
el("prev").onclick = function () { turn(-1); };
el("next").onclick = function () { turn(1); };

function check() {
  var r = new XMLHttpRequest();
  r.onreadystatechange = function () {
    if (r.readyState !== 4) return;
    try {
      if (r.status !== 200) throw r.status;
      state = JSON.parse(r.responseText);
      misses = 0;
      document.body.className = "";
      show();
    } catch (e) {
      if (++misses >= 2) document.body.className = "stopped";
    }
  };
  r.open("GET", "state?t=" + new Date().getTime(), true);  // the time stops old browsers reusing an answer
  r.send();
}

// Before iOS 13, Safari can't save files: it opens them and offers apps to open them with.
el("old").hidden = "download" in document.createElement("a");
show();
setInterval(check, 2500);
</script>
</body></html>"""

PAGE_GONE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>""" + _STYLE + """</style></head>
<body class="stopped"><div class="gone">""" + _CAT + """<h1>Not shared right now ✿</h1>
<p class="sub">Tick it in Send to your phone on your computer, then tap it again</p></div></body></html>"""
