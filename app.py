#!/usr/bin/env python3
"""Tiltboard - a tiny web app where posted text shows up as tilted shapes.

Run:  python app.py     (host/port read from config.json, defaults 0.0.0.0:8000)
Texts persist to chat.txt (one line per tilt, newest last) and are restored on
restart with fresh random tilts/colors; the file grows without bound while the
board pages through it in rows x columns chunks sized by config.json. A tilted
shape may carry an attachment - its path is
stored in the same chat.txt line as a trailing "file:///<path>" token, hidden
from view (images render inline, other files become download links served via
/files/). The look defaults to "style" from config.json; visitors can switch
themes client-side via the settings box (browser cookie) without restarting.
"""
import html
import json
import logging
import mimetypes
import os
import random
import re
import socket
import subprocess  # v2.4.x: WMF rasterization via Windows System.Drawing
import sys
import hashlib
import hmac  # v2.1.0: signed tb_auth cookie (no session table)
import threading  # v2.0.0: shared lock for every chat.txt write + the sync worker thread
import email.policy
from email.parser import BytesParser  # cgi module is gone on Python >= 3.13
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, quote, unquote, urlparse
import time  # v2.0.0: sync worker pacing and retry backoff
import urllib.request
import queue  # v2.0.0: local commit actions awaiting forwarding to the passive board

# Frozen (PyInstaller/Nuitka .exe): __file__ points into a temp unpack dir,
# so anchor on the executable itself; plain `python app.py` keeps old behavior.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
CHAT_PATH = os.path.join(BASE_DIR, "chat.txt")
LOG_PATH = os.path.join(BASE_DIR, "tiltboard.log")
# Styles ship inside the .exe (built with --add-data) so a standalone
# executable works on its own; a styles/ folder dropped next to the program
# always wins, which is how custom themes get installed.
STYLES_DIR = os.path.join(BASE_DIR, "styles")
if not os.path.isdir(STYLES_DIR):
    _bundled = getattr(sys, "_MEIPASS", None)
    if _bundled and os.path.isdir(os.path.join(_bundled, "styles")):
        STYLES_DIR = os.path.join(_bundled, "styles")
# v1.27.0: browser-tab / taskbar icon - the same file is embedded in the .exe itself,
# and a copy next to the program (or exe) wins over the built-in one.
FAVICON_PATH = os.path.join(BASE_DIR, "app.ico")
if not os.path.isfile(FAVICON_PATH):
    _bundled_fav = getattr(sys, "_MEIPASS", None)
    if _bundled_fav and os.path.isfile(os.path.join(_bundled_fav, "app.ico")):
        FAVICON_PATH = os.path.join(_bundled_fav, "app.ico")


class _DebugRotatingHandler(RotatingFileHandler):
    """Rotation with custom backup names (v1.26.0): the live file stays tiltboard.log,
    but its rotations are named <stem>.debug.log.N - .0 is the newest rotation and each
    rollover shifts older backups up, dropping whatever falls past max_debug_backups.
    Standard mode never writes these names (and never deletes existing ones)."""

    def __init__(self, filename: str, max_bytes: int,
                 max_debug_backups: int = 10, encoding: str | None = "utf-8") -> None:
        super().__init__(filename, mode="a", maxBytes=max_bytes,
                         backupCount=max_debug_backups, encoding=encoding)
        self._debug_stem, _ext = os.path.splitext(filename)   # .../tiltboard.log

    def doRollover(self) -> None:
        stem = self._debug_stem
        last = self.backupCount - 1
        oldest = f"{stem}.debug.log.{last}"
        if os.path.exists(oldest):                       # make room: drop the oldest copy
            try:
                os.remove(oldest)
            except OSError:
                pass
        for i in range(last - 1, -1, -1):
            src = f"{stem}.debug.log.{i}"
            if os.path.exists(src):                      # shift .N -> .N+1, newest becomes .0
                try:
                    os.rename(src, f"{stem}.debug.log.{i + 1}")
                except OSError:
                    break
        if self.stream:
            self.stream.close()
            self.stream = None
        os.rename(self.baseFilename, f"{stem}.debug.log.0")  # current log becomes the newest backup
        try:
            if not self.delay:
                self.stream = self._open()
        except OSError:
            pass


def _init_logging() -> logging.Logger:
    """Persistent app log: tiltboard.log next to the app plus stdout so terminal/nohup
    captures keep working. Routine traffic stays quiet; errors and notable events are
    always recorded. Rotation depends on "debug" from config.json (v1.26.0):
      0 - standard mode, rotates at 1 MB with backups .1-.3
      1 - DEBUG level, rotates at 10 MB and keeps 10 backups named tiltboard.debug.log.0-.9 (.0 = newest)
    Switching back to 0 never deletes those debug backups; if the live log is already
    above 1 MB it is saved as tiltboard.log.bak once and a fresh empty log starts.
    A missing log file on first startup works in both modes."""
    debug = False  # v1.24.0: "debug": 1 in config.json switches the log to DEBUG level
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:   # CONFIG_PATH is defined above, before this runs
            raw = json.load(f)
        flag = str(raw.get("debug", 0)).strip()
        debug = flag == "1" or flag.lower() in ("true", "yes")
    except (OSError, ValueError):  # missing/broken config -> quiet INFO default
        pass
    logger = logging.getLogger("tiltboard")
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    MB = 1_048_576
    if debug:  # v1.26.0: bigger log and more history while extended logging is on
        try:
            file_handler = _DebugRotatingHandler(LOG_PATH, max_bytes=10 * MB,
                                                 max_debug_backups=10)
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:  # a non-writable log must never kill the board
            pass
    else:
        try:
            if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MB:
                # v1.26.0: leaving debug mode with an oversized log - save it as .bak once
                # (the exists() guard keeps a fresh install without any log from hitting the OSError path)
                bak_path = LOG_PATH + ".bak"
                i, keep = 1, False
                while not keep:
                    try:
                        os.rename(LOG_PATH, bak_path)
                        keep = True
                    except FileExistsError:      # a .bak from an earlier switch already exists
                        bak_path = f"{LOG_PATH}.bak.{i}"
                        i += 1
                logger.info("log over %d MB after debug mode - moved to %s, starting fresh",
                         MB, os.path.basename(bak_path))
            file_handler = RotatingFileHandler(LOG_PATH, maxBytes=MB, backupCount=3,
                                               encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:  # a non-writable log must never kill the board
            pass
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return logger


log = _init_logging()
VERSION = "2.4.0"  # v2.1.6: no pass_read_only + full password set -> visitors without a cookie
#                  browse in read-only mode instead of the login dialog; the settings Login
#                  button upgrades them to a full session with pass_full_access;
# v2.1.5: tabs with an invalidated cookie stop polling after the first 401, and their /posts poll's
#         401s are only shown with "debug": 1 (no more WARNING spam);
# v2.1.4: hide unstyled board flash during page reload (FOUC guard);
# v2.1.3: constant black font color for all emoji-component cells in every style;
# v2.1.2: header.html stays visible on the login screen (locked page keeps .wrap open);
# v2.1.x: optional password login (pass_full_access/pass_read_only) - signed tb_auth cookie,
# themed login dialog in every style, settings-bar Login button for role switching
DEFAULT_ROWS, DEFAULT_COLUMNS = 35, 1  # board grid when config.json lacks rows/columns
MAX_ROWS, MAX_COLUMNS = 1000, 100      # hard validation bounds for the same keys
NUM_COLORS = 10  # each stylesheet defines its own palette for data-c="0..9"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
# v2.3.0: in-card preview types for non-image attachments; anything not listed
# here (old .xls binary format has no client-side renderer) keeps the download link only.
PREVIEW_TYPES = {
    ".pdf": "pdf",
    ".docx": "office", ".odt": "office",
    ".xlsx": "excel",
    ".md": "markdown", ".markdown": "markdown",
    ".rtf": "rtf",
    ".wmf": "wmf",   # v2.4.x: bare metafile / native icon / exe's first icon - GDI+ raster on server
    ".ico": "ico",
    ".exe": "exe",
    ".txt": "text", ".log": "text", ".csv": "text", ".json": "text",
    ".ini": "text", ".conf": "text", ".xml": "text", ".yaml": "text", ".yml": "text",
    ".html": "html", ".htm": "html",
    ".mp4": "media", ".webm": "media",
    ".ogg": "media", ".oga": "media", ".mp3": "media", ".wav": "media",
    ".flac": "media", ".m4a": "media", ".opus": "media", ".aac": "media",
}


def load_config() -> dict:
    """Read host/port/data_folder/rows/columns/style/slow_upload + sync keys (v2.0.0) from config.json.

    data_folder: empty/missing -> <app>/data; relative values resolve against
    the app folder; absolute paths (incl. UNC \\server\\share) pass through.
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):  # unreadable or malformed config -> defaults
        log.warning("could not read config.json; using built-in defaults")
        raw = {}
    host = str(raw.get("host", "")).strip() or "0.0.0.0"
    try:
        port = int(raw.get("port", 8000))
    except (TypeError, ValueError):
        log.warning("invalid 'port' in config.json; using 8000")
        port = 8000
    folder = str(raw.get("data_folder", "")).strip()
    if not folder:
        data_folder = os.path.join(BASE_DIR, "data")
    elif os.path.isabs(folder):  # absolute incl. network/UNC paths pass through
        data_folder = folder
    else:                        # relative -> resolve against the app folder
        data_folder = os.path.normpath(os.path.join(BASE_DIR, folder))
    def grid_value(key: str, legacy_key: str | None, default: int, bound: int) -> int:
        if key in raw:                       # "rows"/"columns" win when present
            candidate = raw[key]
        elif legacy_key and legacy_key in raw:   # pre-1.7.0 configs still work
            candidate = raw[legacy_key]
        else:
            return default
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            log.warning("invalid '%s' in config.json; using %d", key, default)
            return default
        if not 0 < value <= bound:           # 1..bound inclusive
            log.warning("'%s' out of range in config.json; using %d", key, default)
            return default
        return value

    rows = grid_value("rows", "max_tilts", DEFAULT_ROWS, MAX_ROWS)      # legacy max_tilts -> rows
    columns = grid_value("columns", None, DEFAULT_COLUMNS, MAX_COLUMNS)
    style = str(raw.get("style", "classic")).strip() or "classic"
    low = raw.get("slow_upload", 0)                # v1.22.0: slow-network switch - absent/0 keeps the current upload path,
    if isinstance(low, str):                       # 1 makes paperclip uploads slice small and retry patiently (client side only)
        try: low = int(low.strip())                # tolerate "1"/"0" written as strings in config.json
        except ValueError: low = None
    if low not in (0, 1):                          # anything else is invalid -> normal mode, loudly so
        log.warning("invalid 'slow_upload' in config.json; using 0")
        low = 0
    def sync_url(key: str) -> str:                 # v2.0.0: optional repo-sync peer - "" keeps single-server mode
        value = str(raw.get(key, "") or "").strip()
        if not value:
            return ""
        if not re.match(r"^https?://", value):     # a URL without scheme would hang the worker silently
            log.warning("invalid '%s' in config.json (needs http:// or https://); sync off for that slot",
                        key)
            return ""
        return value.rstrip("/")

    server_1, server_2 = sync_url("server_1_sync"), sync_url("server_2_sync")  # v2: peer mirrored; slot 2 reserved
    token = str(raw.get("sync_token", "") or "").strip()
    if token and not re.search(r"[!-~]{16,}", token):   # a weak token fails closed - flag it at boot once
        log.warning("short/weak 'sync_token' in config.json - use a long random string on both servers")
    pass_full = str(raw.get("pass_full_access", "") or "").strip()  # v2.1.0: optional password auth - empty pair stays fully open
    pass_ro = str(raw.get("pass_read_only", "") or "").strip()
    if pass_ro and not pass_full:
        log.warning("'pass_read_only' without 'pass_full_access' is ignored - the board stays open")  # user rule: RO alone does nothing
    return {"host": host, "port": port, "data_folder": data_folder,
            "rows": rows, "columns": columns, "style": style, "slow_upload": low,
            "server_1_sync": server_1, "server_2_sync": server_2, "sync_token": token,
            "pass_full_access": pass_full, "pass_read_only": pass_ro}


def _bundled_config() -> str | None:
    """Frozen builds carry a copy of the config.json used at build time -
    tiltboard.spec ships it under bundled/ so a bare .exe on a fresh machine
    starts from exactly those settings instead of plain defaults."""
    bundled = getattr(sys, "_MEIPASS", None)
    if not bundled:
        return None
    try:
        with open(os.path.join(bundled, "bundled", "config.json"), encoding="utf-8") as f:
            text = f.read()
    except OSError:  # bundle missing (e.g. hand-built exe) -> plain defaults
        return None
    try:
        json.loads(text)
    except ValueError:  # corrupt bundle would brick first run -> refuse it loudly
        log.warning("bundled config.json is unreadable; using built-in defaults")
        return None
    return text


def ensure_default_config() -> None:
    """A missing config.json is written out so the first run leaves an editable
    file behind next to the program. Frozen builds start from the config bundled
    at build time, plain runs from every default. An existing one - even a broken
    one - is never touched."""
    if os.path.isfile(CONFIG_PATH):
        return
    text = _bundled_config()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            if text is None:  # unfrozen, or no usable bundle -> every default
                payload = {"host": "0.0.0.0", "port": 8000, "data_folder": "",
                           "rows": DEFAULT_ROWS, "columns": DEFAULT_COLUMNS,
                           "style": "classic", "slow_upload": 0,
                           "debug": 0,
                           # v2.1.0: optional password auth - empty values keep the board fully open
                           "pass_full_access": "", "pass_read_only": ""}
                json.dump(payload, f, indent=2)
            else:
                f.write(text)
        log.info("no config.json found; wrote %r with defaults", CONFIG_PATH)
    except OSError as e:  # read-only install dir -> run on pure defaults anyway
        log.warning("could not create config.json (%s); using built-in defaults", e)


ensure_default_config()
if not os.path.isfile(CHAT_PATH):  # v1.16.x: first run leaves an empty board file behind
    try:
        with open(CHAT_PATH, "w", encoding="utf-8"):
            pass
        log.info("no chat.txt found; created empty %r", CHAT_PATH)
    except OSError as e:  # read-only install dir -> restore_chat swallows it at startup anyway
        log.warning("could not create chat.txt (%s); board starts empty in memory", e)
CONFIG = load_config()
HOST, PORT, DATA_FOLDER, ROWS, COLUMNS, SLOW_UPLOAD = (CONFIG["host"], CONFIG["port"],
                                            CONFIG["data_folder"], CONFIG["rows"],
                                            CONFIG["columns"], CONFIG["slow_upload"])
PAGE_SIZE = ROWS * COLUMNS  # default page size; visitors may override via cookie

# v2.0.0: every chat.txt read-modify-write (post/delete/rate) and the sync
# worker take this one lock, so two threads can never interleave a rewrite.
_chat_lock = threading.Lock()
SYNC_REMOTE = CONFIG["server_1_sync"]   # "" -> pure single-server mode, zero overhead
SYNC_TOKEN = CONFIG["sync_token"]       # both servers must hold the same string
AUTH_FULL = CONFIG["pass_full_access"]  # v2.1.0: password granting full access (post/delete/rate/download/read)
AUTH_RO = CONFIG["pass_read_only"]      # different non-empty value -> read-only role; identical to AUTH_FULL -> grants full
AUTH_ENABLED = bool(AUTH_FULL)          # empty full-password means no auth at all, whatever pass_read_only holds
# v2.1.6: full password set but no read-only one -> cookie-less visitors browse in read-only mode
# (board, downloads and ratings stay open; composer/delete hidden); the settings Login button is
# the way to enter pass_full_access and upgrade to a full session
AUTH_GUEST_RO = bool(AUTH_FULL) and not AUTH_RO
# Secret is derived from the two password strings themselves - no third key to manage, no DB.
# Changing either configured password invalidates every cookie issued before (by design).
_AUTH_SECRET = hashlib.sha256((AUTH_FULL + "|" + AUTH_RO).encode("utf-8")).digest() if AUTH_ENABLED else b""
_LOGIN_FAILS: dict[str, list[float]] = {}   # v2.1.0: per-IP failed-login timestamps (cheap brute-force cooldown)


def _auth_sign(role: str) -> str:
    """HMAC-SHA256 of the role string - the value stored in the HttpOnly tb_auth cookie."""
    return hmac.new(_AUTH_SECRET, role.encode("utf-8"), hashlib.sha256).hexdigest()


def _auth_role(cookie_header: str) -> str | None:
    """'full'/'ro' when a verifying tb_auth cookie is present, else None. Open board = always full."""
    if not AUTH_ENABLED:
        return "full"
    for part in (cookie_header or "").split(";"):
        key, sep, value = part.strip().partition("=")
        if key == "tb_auth":
            role, dot, sig = value.partition(".")
            if dot and role in ("full", "ro") and hmac.compare_digest(sig, _auth_sign(role)):
                return role
    # v2.1.6: no valid tb_auth cookie - a board configured without its own read-only key lets the
    # visitor straight in as 'ro' instead of the login dialog (guest mode; upgrade via Login button).
    # A distinct pass_read_only keeps today's behaviour: anonymous visitors still get the overlay.
    return "ro" if AUTH_GUEST_RO else None


def _login_ok(password: str) -> str | None:
    """Role for a candidate password. An identical pass_read_only grants full too (user rule).
    Constant-time compares only - no early exit on mismatch."""
    if not AUTH_ENABLED or not password:
        return "full" if not AUTH_ENABLED else None
    if hmac.compare_digest(password, AUTH_FULL):
        return "full"
    if AUTH_RO and hmac.compare_digest(password, AUTH_RO):
        return "ro"
    return None
# v2.0.0: every local chat.txt commit (post/rate/delete) wakes the sync worker via
# _sync_dirty() so a change is mirrored within one tick instead of waiting out ~3 s.
_sync_wake = threading.Event()
_pending_actions = queue.Queue()  # (action, payload) tuples the worker forwards before each poll


def _sync_dirty() -> None:  # callable from any request thread; no-op without server_1_sync
    if SYNC_REMOTE:
        _sync_wake.set()

try:  # a configured folder that cannot be created should be loud, not hidden
    os.makedirs(DATA_FOLDER, exist_ok=True)
except OSError as e:
    log.error("data folder %r is not usable: %s", DATA_FOLDER, e)
    sys.exit(1)

# Unbounded store, oldest first: keeps EVERY line of chat.txt so pagination
# and the /posts poller can serve any page (v1.5.2). Page slicing happens at
# render time; newest entries are rendered at the top of each page.
POSTS = []  # items: {"text","tilt","color","attach"?}


def available_styles() -> list[str]:
    """Sorted stems of every .css file in styles/ (the selectable themes)."""
    try:
        return sorted(
            name[:-4] for name in os.listdir(STYLES_DIR) if name.endswith(".css")
        )
    except OSError:  # missing styles dir -> no choices, only the classic fallback
        return []


def load_style():
    """Validate the configured style against styles/ and read its CSS. Returns
    (style_name, css_text); an unknown name falls back to 'classic'."""
    candidate = CONFIG["style"]
    if not os.path.isfile(os.path.join(STYLES_DIR, f"{candidate}.css")):
        log.warning("style %r not found in styles/; using 'classic'", candidate)
        candidate = "classic"
    with open(os.path.join(STYLES_DIR, f"{candidate}.css"), encoding="utf-8") as f:
        return candidate, f.read()


STYLE_NAME, STYLE_CSS = load_style()
STYLES_JSON = json.dumps(available_styles()).encode("utf-8")

# A chat.txt line may end with a trailing "file:///<path>" token naming the
# attachment stored in the data folder (kept on one line to preserve the
# one-line-one-tilt contract). The regex only matches a final token.
ATTACH_RE = re.compile(r"\s+(file://\S+)$")

# v1.23.0: a tilt line may end "Name: text::a:b:c:d file://..." - the rating
# suffix sits between the display text and any attachment tail. Position 1 is
# the thumbs-up count, then thumbs-down, heart, smiley.
RATING_RE = re.compile(r"::(\d+):(\d+):(\d+):(\d+)$")


# v2.0.0 sync: every chat.txt line carries one stable identity at the very end -
# "<8 hex of sha256(display text)>_<monotonic seq>" as a single whitespace-separated
# token after any rating tail and attachment token. The ID never changes once assigned
# (ratings keep it), so remote diffs can match lines by identity instead of position.
# Pre-sync history is backfilled with IDs on the first sync-enabled start.
LINE_ID_RE = re.compile(r" [0-9a-f]{8}_[1-9][0-9]*$")
_id_seq = 0      # caller must hold _chat_lock (persist_text / backfill both do)
_LAST_LINE_ID = ""  # v2.2.0: persist_text() fills it under _chat_lock; add_post() tags the in-memory post

def _strip_line_id(line: str) -> tuple[str, int]:
    """v2.0.0 sync: (line without ID token, seq-or-0). Call before ATTACH_RE/RATING_RE."""
    m = LINE_ID_RE.search(line.rstrip("\n"))
    if not m:
        return line.rstrip("\n"), 0
    base = line[:m.start()]
    return (base or "").rstrip(), int(m.group(0)[1:].rsplit("_", 1)[1])

def _new_line_id(display_text: str) -> str:
    """v2.0.0 sync: fresh ID token for display text without rating tail; caller holds _chat_lock."""
    global _id_seq
    digest = hashlib.sha256(display_text.encode("utf-8")).hexdigest()[:8]
    _id_seq += 1  # v2.2.x fix A: seq must never repeat - sync diff keys lines by this token (was read-only)
    return f"{digest}_{_id_seq}"

def split_line(line: str) -> tuple[str, str | None]:
    """Split a chat.txt line into (display text, attachment path or None)."""
    m = LINE_ID_RE.search(line.rstrip("\n"))  # v2.0.0: strip the stable ID before ATTACH_RE
    if m:
        line = line[:m.start()]
    m = ATTACH_RE.search(line)
    if not m:
        return line.rstrip("\n"), None
    try:  # file://E:/a b.png -> E:/a b.png ; UNC //server/share keeps both slashes
        parsed = urlparse(m.group(1))
        path = unquote(parsed.path)
        if len(parsed.netloc) == 2 and parsed.netloc[1] == ":":
            p = parsed.netloc + path          # file://E:/x -> drive letter in netloc
        elif path.startswith("//"):
            p = path                          # UNC //server/share keeps both slashes
        else:
            p = path.lstrip("/")              # file:///E:/x style
        return line[:m.start()].rstrip(), (p or None)
    except ValueError:
        return line.rstrip("\n"), None


def _new_post(text: str, attach: dict | None = None) -> dict:
    post = {
        "text": text,
        "tilt": round(random.uniform(-7, 7), 2),
        "color": random.randrange(NUM_COLORS),
    }
    if attach:
        post["attach"] = attach  # {"url","name","is_image"} - see describe_attach()
    return post


def restore_posts() -> None:
    """Load every persisted tilt from chat.txt so the board survives a restart.

    v1.5.2: ALL non-empty lines are kept - page slicing happens at render
    time, so history older than one page is still reachable after restart.
    Tilt and color are re-rolled randomly. A trailing file:// token is
    re-linked if its file still exists in the data folder, otherwise the raw
    line degrades to plain text.
    """
    try:
        with open(CHAT_PATH, encoding="utf-8") as f:
            lines = [line.rstrip("\n") for line in f if line.strip()]
    except OSError:  # no chat.txt yet - first run
        return
    POSTS.clear()  # v2.3.x sync fix A: rebuild, never append over stale entries (_sync_apply_lines re-runs this)
    log.info("restored %d tilt%s from chat.txt", len(lines), "" if len(lines) == 1 else "s")
    for line in lines:
        im = LINE_ID_RE.search(line)  # v2.2.0: read the sync ID from the raw line - split_line strips it internally
        text, path = split_line(line)
        attach = describe_attach(path) if path else None
        post = _new_post(text, attach)
        if im:
            post["id"] = im.group(0).strip()  # v2.2.0: stable /swap identity (absent pre-sync -> text fallback)
        m = RATING_RE.search(text)  # v1.23.0: peel the rating tail off the display text
        if m:
            post["text"] = text[:m.start()].rstrip()
            post["rating"] = [int(g) for g in m.groups()]
        POSTS.append(post)


def persist_text(text: str, stored_name: str | None = None) -> None:
    """Append a tilt to chat.txt - append-only since v1.5.2.

    The file grows without bound; rows x columns only size each rendered
    page, so history older than one page is never destroyed. With an attachment
    the line becomes "<text> file:///<absolute path>", forward-slashed and
    %20-escaped so split_line() can read it back.
    """
    display = text  # v2.2.x fix B: the attachment path must NOT feed the digest - identical tilts on
    # boards with different data_folder paths mint ONE shared ID (remote diff + local dedupe rely on it)
    if stored_name:
        local = os.path.normpath(os.path.join(DATA_FOLDER, stored_name)) \
            .replace("\\", "/")  # E:\data\x.jpg -> E:/data/x.jpg ; UNC keeps //server
        text += f" file://{local.replace(' ', '%20')}"
    global _LAST_LINE_ID  # v2.2.0: add_post() reads it right after this call (same thread)
    with _chat_lock:  # v2.0.0: appends share one lock with delete/rate rewrites
        token = _new_line_id(display)  # v2.0.0: new posts carry their stable ID at write time
        text += " " + token
        _LAST_LINE_ID = token  # v2.2.0: swap identity for the post being appended right now
        with open(CHAT_PATH, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def backfill_line_ids() -> None:
    """v2.0.0 sync: stable-ID assignment for pre-sync chat.txt history + seq seed.

    Runs unconditionally - in main() and before every /sync/state answer we serve. Idempotent:
    when every line already ends with an ID this is one read pass that only raises the
    in-memory sequence counter above the file's highest seq, so a restart can never let
    _new_line_id() reuse a number an existing line already carries (the passive /sync/state
    map keys lines by ID and would silently collapse such a collision). New posts always get
    their IDs at write time instead (persist_text).
    """
    global _id_seq
    with _chat_lock:
        try:
            lines = open(CHAT_PATH, encoding="utf-8").read().splitlines()
        except OSError:
            return  # unreadable file - the next successful run will retry
        need, max_seq = False, 0
        for ln in lines:
            if not ln.strip():
                continue
            _, seq = _strip_line_id(ln)
            max_seq = max(max_seq, seq)
            if seq == 0:  # no ID yet - this is the pre-sync history
                need = True
        if not need:
            _id_seq = max(_id_seq, max_seq)  # restart seed: continue above every existing seq
            return  # every line already carries an identity - nothing to write
        new_lines, n, changed = [], max_seq, 0
        for ln in lines:
            if not ln.strip():
                new_lines.append(ln)
                continue
            base, seq = _strip_line_id(ln)
            if seq > 0:
                new_lines.append(ln)  # keep byte-for-byte, ID already assigned
                continue
            am = ATTACH_RE.search(base.rstrip("\n"))      # rating tail may sit between text and attach
            base2 = (base[:am.start()] if am else base).rstrip("\n")
            rm = RATING_RE.search(base2)
            if rm:
                base2 = base2[:rm.start()].rstrip()
            n += 1
            new_lines.append(f"{ln} {hashlib.sha256(base2.encode('utf-8')).hexdigest()[:8]}_{n}")
            changed += 1
        tmp = CHAT_PATH + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                for ln in new_lines:
                    if ln.strip():
                        f.write(ln + "\n")
            os.replace(tmp, CHAT_PATH)
            _id_seq = n
        except OSError as e:
            log.warning("ID backfill failed: %s - will retry on next start", e)
    log.info("backfilled stable line IDs for %d pre-sync lines (max seq now %d)", changed, n)

def add_post(text: str, stored_name: str | None = None) -> None:
    persist_text(text, stored_name)
    attach_path = os.path.join(DATA_FOLDER, stored_name) if stored_name else None
    post = _new_post(text, describe_attach(attach_path))
    if _LAST_LINE_ID:  # v2.2.0: same stable ID the line just got on disk -> /swap identity travels in memory too
        post["id"] = _LAST_LINE_ID
    POSTS.append(post)
    snippet = text.replace("\n", " ")[:60]  # one-line digest; escapes stay readable
    log.info("tilt posted: %s%s", snippet,
             f" (attachment {stored_name})" if stored_name else "")
    if log.isEnabledFor(logging.DEBUG):  # v1.24.0: extended logging - which chat.txt line this post became
        try:
            with open(CHAT_PATH, encoding="utf-8") as f:
                total = sum(1 for _ in f)
        except OSError:
            total = -1
        log.debug("action=post text=%r attach=%s -> appended as chat.txt line %d of %d",
                  snippet, stored_name or "-", total, max(total, 1))


def describe_attach(local_path: str | None) -> dict | None:
    """Web-facing attachment metadata for a file inside the data folder.

    Returns {"url", "name", "is_image"} or None when unusable; callers degrade
    to plain text so a moved/removed data folder never breaks rendering.
    """
    if not local_path:
        return None
    try:
        real = os.path.realpath(local_path)
        root = os.path.realpath(DATA_FOLDER)
        if os.path.commonpath([real, root]) != root or not os.path.isfile(real):
            return None  # outside the data folder (or gone) - treat as plain text
    except ValueError:
        return None
    name = os.path.basename(real)
    ext = os.path.splitext(name)[1].lower()
    return {"url": "/files/" + quote(name), "name": name,
            "is_image": ext in IMAGE_EXTS, "preview": PREVIEW_TYPES.get(ext)}


# v1.16.2 - paperclip attachments ALWAYS upload chunk-by-chunk (see /upload/init,
# /upload/chunk), so neither the server nor the browser ever buffers a whole
# multi-GB file in RAM; drops/pastes stay on the direct path up to 256 MB.
CHUNK_UPLOAD_LIMIT = 32 * 1024 * 1024
STREAM_BUF = 1024 * 1024  # read/write block size for streaming uploads and downloads


def reserve_upload(filename: str) -> str | None:
    """Reserve a stored file name for a chunked upload (v1.16.0).

    Same sanitisation and collision numbering as save_upload, but the file is
    created empty first - exclusive creation ("xb") makes concurrent uploads
    race-safe. The client then streams chunks into it; /post commits the name.
    """
    base = os.path.basename((filename or "").replace("\\", "/"))
    # v2.4.x: the old [:60] cut the WHOLE name including its extension - a long Czech .docx title lost both its tail and ending. Windows MAX_PATH leaves ~180 chars inside data/, so cap only the sanitized STEM at 170; the extension always survives.
    safe = re.sub(r"[^\w.\-]+", "_", base).strip("._") or "file"
    stem, ext = os.path.splitext(safe)
    if len(stem) > 170:   # very long title: keep the ending readable, never drop its type
        safe = f"{stem[:170]}{ext}"
        stem = stem[:170]
    n = 0
    while True:
        stored_name = f"{stem}_{n}{ext}" if n else safe
        try:
            open(os.path.join(DATA_FOLDER, stored_name), "xb").close()
            return stored_name
        except FileExistsError:
            n += 1
        except OSError as e:
            log.warning("could not reserve attachment %r: %s", stored_name, e)
            return None


def _stored_path(name) -> str | None:
    """Realpath of a client-supplied stored name, or None when it escapes the data folder."""
    if not isinstance(name, str) or not name or os.path.basename(name) != name:
        return None
    real = os.path.realpath(os.path.join(DATA_FOLDER, name))
    try:
        inside = os.path.commonpath([real, os.path.realpath(DATA_FOLDER)]) == os.path.realpath(DATA_FOLDER)
    except ValueError:  # cross-drive / UNC-vs-local mismatch -> outside
        inside = False
    return real if inside and os.path.isfile(real) else None


def save_upload(filename: str, data: bytes) -> str | None:
    """Store an upload inside the data folder under its own name when free.

    The sanitized original basename is used as-is; a collision numbers the file
    before its extension (report.pdf, report_1.pdf, report_2.pdf ...). Exclusive
    creation ("xb") makes concurrent uploads race-safe without any randomness;
    returns the stored file name or None when nothing could be written.
    """
    base = os.path.basename((filename or "").replace("\\", "/"))
    # v2.4.x: the old [:60] cut the WHOLE name including its extension - a long Czech .docx title lost both its tail and ending. Windows MAX_PATH leaves ~180 chars inside data/, so cap only the sanitized STEM at 170; the extension always survives.
    safe = re.sub(r"[^\w.\-]+", "_", base).strip("._") or "file"
    stem, ext = os.path.splitext(safe)
    if len(stem) > 170:   # very long title: keep the ending readable, never drop its type
        safe = f"{stem[:170]}{ext}"
        stem = stem[:170]
    n = 0
    while True:
        stored_name = f"{stem}_{n}{ext}" if n else safe
        try:
            with open(os.path.join(DATA_FOLDER, stored_name), "xb") as f:
                f.write(data)
            return stored_name
        except FileExistsError:
            n += 1
        except OSError as e:
            log.warning("could not store attachment %r: %s", stored_name, e)
            return None


def parse_multipart(body: bytes, content_type: str):
    """Minimal multipart/form-data parser (the cgi module vanished in 3.13).

    v2.4.0: raw-bytes boundary split instead of BytesParser - the email header
    grammar mangled non-latin-1 filename bytes (Czech etc.) and dropped such
    parts from `files` entirely, so a drop produced a post without attachment.
    Browsers always send unescaped UTF-8 inside filename="..."; spaces are fine.

    Returns (fields dict, list of (field_name, filename, payload_bytes)).
    """
    fields: dict[str, str] = {}
    files: list[tuple[str, str | None, bytes]] = []
    m = re.search(r'boundary="?([^";]+)"?', content_type or "")
    if not m:
        return fields, files
    delim = b"--" + m.group(1).encode("latin-1", "replace")
    for chunk in body.split(delim):
        if not chunk or chunk.startswith(b"--"):  # piece before first boundary / final terminator
            continue
        part = chunk.lstrip(b"\r\n")  # the CRLF after each boundary line
        if part.endswith(b"\r\n"):    # framing CRLF before the next delimiter - never payload (RFC 2046)
            part = part[:-2]
        raw_head, _, payload = part.partition(b"\r\n\r\n")
        name_m = re.search(rb'name="([^"]*)"', raw_head)
        file_m = re.search(rb'filename="([^"]*)"', raw_head)
        if not name_m:
            continue
        fname = file_m.group(1).decode("utf-8", "replace") if file_m else None
        (files.append((name_m.group(1).decode("latin-1"), fname, payload))
         if fname is not None else fields.__setitem__(name_m.group(1).decode("latin-1"), payload.decode("utf-8", "replace")))
    return fields, files


# v2.1.x - no separate login document any more: unauthenticated visitors get this very page
# (PAGE below) with __POSTS__/pagers baked empty, plus an inline script that reveals the themed
# #loginOverlay and hides composer/search/pager. The gear icon keeps working pre-login, header.html
# renders, and /style.css themes everything like a normal card. /login sets the signed cookie;
# location.replace('/') then re-enters do_GET with that role and fills the board.
PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tiltboard</title>
<style>/* v2.1.6: hide the page from the very first byte - the rules in <style id="settingsStyles">
   arrive only after all card markup (line ~805), so a full reload could still paint one unstyled
   frame before they apply; this inline head rule closes that window, revealed by html.tb-loaded.
   The timeout below guarantees reveal even if the theme sheet never applies. */
body { visibility: hidden; }
html.tb-loaded body { visibility: visible !important; }</style>
<link id="theme" rel="stylesheet" href="/style.css">
<script>  /* v2.0.1 hotfix: apply the cookie theme synchronously, before first paint - kills the
   flash of the config-default style that used to show for a moment after every refresh */
(function () {
  try {
    for (const part of document.cookie.split(";")) {
      const idx = part.indexOf("=");
      if (idx > -1 && part.slice(0, idx).trim() === "tiltboard") {
        const s = new URLSearchParams(decodeURIComponent(part.slice(idx + 1))).get("style");
        if (s) document.getElementById("theme").href = "/style.css?name=" + encodeURIComponent(s);
      }
    }
  } catch (e) {}
})();
</script>
<script>/* v2.1.6: raise html.tb-loaded only once /style.css has really applied - the shared CSS below keeps
   body invisible until then, so a reload (post/delete/style/rows-cols) never flashes plain text +
   raw pictures for one frame. A sheet entry appears in document.styleSheets as soon as <link> is
   parsed, even while still downloading - on every cold load (cleared cache / new visitor; /style.css
   is served no-store) the old href-only check revealed too early and flashed. The poll now verifies
   cssRules are actually readable before revealing; 'error' reveals too, and a 1500 ms safety timeout
   guarantees the page can never stay hidden (missing/blocked theme). */
(function () {
  var done = false;
  function ready() { if (!done) { done = true; document.documentElement.classList.add("tb-loaded"); } }
  var l = document.getElementById("theme");
  if (l) { l.addEventListener("load", ready); l.addEventListener("error", ready); }
  (function check() {
    for (var s of document.styleSheets) if ((s.href || "").indexOf("/style.css") > -1) return ready();
    setTimeout(check, 5);
  })();
  setTimeout(ready, 2000);  // bounded reveal: a missing/blocked theme must not hide the page forever
})();
</script>
<script>/* v2.1.x: pre-login visitors still get this document (themed, gear icon live) but the server
   bakes the card area empty and sets TB_AUTH_MODE; the script at <body> start then reveals the
   themed login dialog and hides composer/search/pager until /login issues a signed cookie. */
window.TB_AUTH_MODE = __AUTH_MODE__;
</script>
<link rel="icon" type="image/x-icon" href="/favicon.ico">  <!-- v1.27.0 -->
</head>
<body>
<button id="searchIcon" title="Search tilts &nbsp;(n:name · f:file · c:text)" aria-pressed="false">&#128269;</button>
<input id="searchInput" class="hidden" type="text" maxlength="200" autocomplete="off"
       placeholder="Search…  n:name · f:file · c:text" aria-label="Search tilts">
<button id="settingsIcon" title="Page settings">&#9881;</button>

<div id="settingsBox" class="hidden" aria-hidden="true">
  <div class="row"><label for="nameInput">Name</label><input id="nameInput" type="text" maxlength="30"></div>
  <div class="row"><label for="styleSelect">Style</label><select id="styleSelect"></select></div>
  <div class="row"><label for="colsInput" title="How many cards sit side by side in one row">Columns</label><input id="colsInput" type="number" min="1" max="100"></div>
  <div class="row"><label for="rowsInput" title="How many rows of cards fill one page">Rows</label><input id="rowsInput" type="number" min="1" max="1000"></div>
  <div class="row"><label></label><button id="reloginBtn" type="button" hidden>Login</button></div>
  <p class="hint">Changes are saved to your browser (cookie) and applied on reload.</p>
</div>

<div id="confirmOverlay" class="hidden" aria-hidden="true">
  <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="delMsg">
    <p id="delMsg"></p>
    <div class="btns"><button id="delYes">Delete</button><button id="delNo">Cancel</button></div>
  </div>
</div>

<!-- v2.1.x: pre-login shell - same .dialog anatomy as the delete dialog, so every theme styles it -->
<div id="loginOverlay" class="hidden" aria-hidden="true">
  <form id="loginForm" class="dialog">
    <!-- Chromium a11y asks password forms to carry an (optionally hidden) username field;
         .sr-only keeps it in the DOM but visually absent. See styles note v2.1.x -->
    <input id="loginUser" class="sr-only" type="text" autocomplete="username"
           aria-hidden="true" tabindex="-1">
    <p><b>Tiltboard</b> &mdash; access required</p>
    <input id="loginPass" type="password" maxlength="128" autocomplete="current-password"
           placeholder="Access password" aria-label="Access password">
    <p class="hint" id="loginMsg"></p>
    <div class="btns"><button id="loginGo" type="submit">Unlock</button></div>
  </form>
</div>

<div class="wrap">
__HEADER__
__ARROWS_TOP__
    <form class="composer" method="post" action="/post" enctype="multipart/form-data">
    <div class="msg-wrap">
      <textarea id="message" name="message" rows="1" placeholder="Say something... (paste or drop files)" autofocus></textarea>
      <div id="uploadProg" class="hidden"><div id="uploadFill"></div><span id="uploadLabel"></span></div>
      <div id="pendingChips"></div>  <!-- v1.19.x: chips live INSIDE the box, top-right corner -->
    </div>
    <div id="emojiPicker" class="hidden"></div>
    <button id="emojiBtn" type="button" title="Add an emoji">&#128578;</button>
    <button id="attachBtn" type="button" title="Attach a file">&#128206;</button>
      <input id="filePick" type="file" multiple hidden>
      <button id="post" type="submit">Post</button>
    </form>

  <div class="board" id="board">
__POSTS__
  </div>
__ARROWS_BOTTOM__
</div>

<script>/* v2.1.x: runs after all board markup is parsed - an unlocked visitor sees only the
   (themed) login dialog and the settings gear; composer/search/pager stay hidden until the
   signed cookie from /login arrives on location.replace('/'). */
window.TB_AUTH_ENABLED = __AUTH_ENABLED__;  // auth configured at all - Login button in settings even when logged in
  var relock = function (keepHeader) {  // v2.1.x: shared by the locked-page reveal AND the Login button (re-lock while logged in);
    // v2.1.2: keepHeader keeps .wrap visible so header.html still renders on the login screen
    // (a locked page bakes empty posts and pagers, nothing sensitive can leak from it)
    var w = document.querySelector(".wrap"); if (w && !keepHeader) w.style.display = "none";
    ["searchIcon", "searchInput"].forEach(function (id) { var el = document.getElementById(id); if (el) el.style.display = "none"; });
    var sbx = document.getElementById("settingsBox");
    if (sbx) {
      if (!sbx.classList.contains("hidden")) sbx.setAttribute("data-relocked", "1");  // remember we closed it, so dismiss can reopen
      sbx.classList.add("hidden"); sbx.setAttribute("aria-hidden", "true");
    }
    var lo = document.getElementById("loginOverlay");
    lo.classList.remove("hidden");
    lo.setAttribute("aria-hidden", "false");
    document.getElementById("loginPass").focus();
  };
  var rb = document.getElementById("reloginBtn");   // v2.1.x: Login button in settings - also for logged-in users
  if (rb) { rb.hidden = !window.TB_AUTH_ENABLED; if (window.TB_AUTH_ENABLED) rb.onclick = relock; }
  if (window.TB_AUTH_MODE) {
    document.querySelectorAll(".composer, .pager, #searchIcon, #searchInput, .arrow, #board")
      .forEach(function (el) { el.style.display = "none"; });  // v2.1.2: #board stays hidden too
    relock(true);  // v2.1.2: header.html remains visible on the login screen
  }
  // v2.1.x: a logged-in user who re-locked via the Login button can walk away again -
  // Escape or a click on the backdrop restores exactly what relock() hid (the board,
  // search icons, settings box). Locked visitors just get their locked screen back.
  var loEl = document.getElementById("loginOverlay"), lfEl = document.getElementById("loginForm");
  function dismissLogin() {
    if (!loEl || loEl.classList.contains("hidden")) return;
    loEl.classList.add("hidden"); loEl.setAttribute("aria-hidden", "true");
    var w = document.querySelector(".wrap"); if (w) w.style.display = "";  // v2.1.2: wrap was never hidden on a locked page
    ["searchIcon", "searchInput"].forEach(function (id) {
      var el = document.getElementById(id); if (el) el.style.display = window.TB_AUTH_MODE ? "none" : ""; });
    var sbx = document.getElementById("settingsBox");
    if (sbx && sbx.getAttribute("data-relocked") === "1") {
      sbx.classList.remove("hidden"); sbx.setAttribute("aria-hidden", "false");
      sbx.removeAttribute("data-relocked");
    }
  }
  if (loEl) {
    loEl.addEventListener("click", function (e) { if (e.target === loEl) dismissLogin(); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !loEl.classList.contains("hidden") && lfEl && !lfEl.classList.contains("busy")) {
        e.preventDefault(); dismissLogin();
      }
    });
  }
</script>
<script>window.DEFAULT_STYLE = "__DEFAULT_STYLE__";
window.DEFAULT_ROWS = __DEFAULT_ROWS__;
window.DEFAULT_COLUMNS = __DEFAULT_COLUMNS__;
window.SLOW_UPLOAD = __SLOW_UPLOAD__;
window.TB_RO = __RO_ROLE__;  // v2.1.0: read-only visitor - composer and delete crosses vanish
if (window.TB_RO) { document.querySelectorAll(".composer, .del").forEach(function (el) { el.style.display = "none"; }); };</script>
<script>
// Settings live in a browser cookie - the server never sees them.
(function () {
  const COOKIE = "tiltboard", DEFAULT_NAME = "User";
  const icon = document.getElementById("settingsIcon");
  const box = document.getElementById("settingsBox");
  const nameInput = document.getElementById("nameInput");
  const styleSelect = document.getElementById("styleSelect");

  const colsInput = document.getElementById("colsInput");   // v1.7.0: board grid
  const rowsInput = document.getElementById("rowsInput");

  function readCookie() {
    for (const part of document.cookie.split(";")) {
      const idx = part.indexOf("=");
      if (idx > -1 && part.slice(0, idx).trim() === COOKIE)
        return new URLSearchParams(decodeURIComponent(part.slice(idx + 1)));
    }
    return null;
  }

  // A cookie grid value is only trusted inside its bound - anything else
  // (missing, garbage, out of range) silently falls back to the default.
  function cleanGrid(v, def, max) {
    const n = parseInt(v, 10);
    return Number.isFinite(n) && n >= 1 && n <= max ? n : def;
  }

  function writeCookie(name, style, colsRaw, rowsRaw) {
    const params = new URLSearchParams();
    // Inputs hand over strings - normalize before the default comparison,
    // otherwise "35" !== 35 and every reload writes a pointless cookie.
    const cols = parseInt(colsRaw, 10), rows = parseInt(rowsRaw, 10);
    if (name !== DEFAULT_NAME) params.set("name", name);
    if (style && style !== window.DEFAULT_STYLE) params.set("style", style);
    if (cols !== window.DEFAULT_COLUMNS) params.set("cols", cols);  // defaults stay cookie-free
    if (rows !== window.DEFAULT_ROWS) params.set("rows", rows);
    document.cookie = params.toString()
      ? COOKIE + "=" + encodeURIComponent(params.toString()) + ";path=/"
      : COOKIE + "=;path=/;max-age=0";  // back to defaults -> forget the cookie
  }

  // First visit: pre-fill from cookie or defaults, then reveal the settings box below.
  const saved = readCookie();
  const name = (saved && saved.get("name")) || DEFAULT_NAME;
  const style = (saved && saved.get("style")) || window.DEFAULT_STYLE;
  let cols = cleanGrid(saved && saved.get("cols"), window.DEFAULT_COLUMNS, 100); // v1.17.0: mobile first-visit default may lower this
  const rows = cleanGrid(saved && saved.get("rows"), window.DEFAULT_ROWS, 1000);

  if (saved) {  // remember this visitor's theme - no server round-trip needed
    document.getElementById("theme").href = "/style.css?name=" + encodeURIComponent(style);
  }

  function closeAndReload() {  // persist the current box values, then apply them
    writeCookie(nameInput.value.trim() || DEFAULT_NAME, styleSelect.value,
                colsInput.value, rowsInput.value);
    location.reload();
  }

  icon.addEventListener("click", () => {
    if (box.classList.contains("hidden")) {  // opening: prefill from cookie/defaults
      nameInput.value = name;
      styleSelect.value = style;             // an empty select would show its first option
      colsInput.value = cols;                // grid prefills the same way (v1.7.0)
      rowsInput.value = rows;
      box.classList.remove("hidden");
      box.setAttribute("aria-hidden", "false");
    } else closeAndReload();               // closing = save + reload with new style
  });

  nameInput.addEventListener("keydown", (e) => { if (e.key === "Enter") closeAndReload(); });
  colsInput.addEventListener("keydown", (e) => { if (e.key === "Enter") closeAndReload(); });
  rowsInput.addEventListener("keydown", (e) => { if (e.key === "Enter") closeAndReload(); });
  styleSelect.addEventListener("change", closeAndReload);
  // cols/rows deliberately have NO change listener: typing or using the number
  // spinner must not fire a save+reload mid-edit - Enter or the gear closes them.

  fetch("/styles").then((r) => r.json()).then((list) => {  // fill the dropdown
    for (const s of list) {
      const opt = document.createElement("option");
      opt.value = opt.textContent = s;
      styleSelect.appendChild(opt);
    }
    // Preselect the visitor's theme (cookie or server default): a freshly
    // populated <select> shows its FIRST option until .value is set, so without
    // this line the dropdown always opened on 'classic'.
    if (![...styleSelect.options].some(o => o.value === style)) styleSelect.value = window.DEFAULT_STYLE;
    else styleSelect.value = style;
  });

  // Requirement: a non-default name prefixes every new post as "Mark: Hello!".
  // Picture-only posts get the bare prefix too ("leo:"), so an attachment
  // without text is never anonymous. The prefixed value is what gets posted,
  // so this listener must never fire twice on one attempt (the file path
  // below clears the input right away).
  document.querySelector("form").addEventListener("submit", () => {
    const msg = document.getElementById("message");
    const t = msg.value.trim();
    // v1.18.0: prefixing moved into the submit loop below - one attempt posts N files, so it must happen once per file, not once per submit event
  });

  if (!saved) {  // first visit: show the settings box so choices can be made
    // v1.17.0: a phone gets one column by default - full-width cards stacked
    // vertically, because several columns per line would be too small to read on a
    // narrow screen. Existing visitors are untouched (saved != null), and this
    // prefills the open box only; nothing is written until the user closes it or presses Enter.
    if (window.matchMedia("(max-width: 700px)").matches) cols = 1;
    nameInput.value = name;       // prefill like the icon-open path does - the box is
    colsInput.value = cols;       // shown without a click, so its inputs would stay empty
    rowsInput.value = rows;       // (the style dropdown prefills itself once /styles lands)
    box.classList.remove("hidden");
    box.setAttribute("aria-hidden", "false");
  }

  // Attachments (v1.18.0): any number of files wait as chips in the composer
  // row, each remembered with the source it came from - a batch may mix
  // dropped pictures, pasted ones and paperclip picks freely.
  const form = document.querySelector(".composer");
  const message = document.getElementById("message");
  const chipsRow = document.getElementById("pendingChips");
  const pick = document.getElementById("filePick");
  let pendingFiles = [];                  // v1.18.0: { file, source } - posting order is array order
  const DROP_MAX = 256 * 1024 * 1024;     // drops/pastes stay on the direct path up to this, then suggest the clip icon
  const CHUNK_SIZE = 8 * 1024 * 1024;     // slice size for chunked uploads (paperclip always chunks)
  const SLOW_CHUNK = window.SLOW_UPLOAD ? 256 * 1024 : CHUNK_SIZE; // v1.22.0: small slices when config.json says slow_upload
  const CLIP_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>';

  // v1.16.x: progress overlay over the text box - fill grows with uploaded bytes,
  // label on the left edge shows "filename - x / y MB" (same rounding as alerts)
  const upProg = document.getElementById("uploadProg");
  const upFill = document.getElementById("uploadFill");
  const upLabel = document.getElementById("uploadLabel");
  function syncOverlay() {   // the .msg-wrap wrapper stretches to match the taller Post button,
    if (upProg.classList.contains("hidden")) return;       // so pin the overlay to the textarea's real box
      upProg.style.height = message.offsetHeight + "px";     // instead of covering the whole wrapper
  }                                                           // (the fill would otherwise spill past its border)
  function showUpload(name, done, total) {
    syncOverlay();
    upLabel.textContent = name + " - " + (done / 1048576).toFixed(1) + " MB of " + (total / 1048576).toFixed(1) + " MB";
    upFill.style.width = Math.min(100, done * 100 / total) + "%";
    upProg.classList.remove("hidden");
  }
  function hideUpload() { upProg.classList.add("hidden"); }

  function renderChips() {   // v1.19.x: first attachment sits in the box's top-right corner, later ones to its left
    chipsRow.replaceChildren(...pendingFiles.map((p, idx) => {
      const span = document.createElement("span");
      span.className = "chip";                  // v1.10.2 look kept: clip inherits the theme color via currentColor
      span.title = p.file.name;                 // name appears on hover only
      span.innerHTML = CLIP_SVG;
      const x = document.createElement("button");  // tiny ✕ fades in beside its own chip (CSS sibling rule)
      x.className = "chip-x"; x.type = "button";
      x.title = "Remove this attachment"; x.textContent = "\u2715";
      x.addEventListener("click", (e) => {
        e.preventDefault();
        pendingFiles.splice(idx, 1);            // v1.18.0: each chip removes exactly its own file
        pick.value = "";
        renderChips(); message.focus();
      });
      span.appendChild(x);
      return span;
    }));
    fitChips();
  }

  const fitChips = () => {  // v1.19.x: wrapped chip rows live INSIDE the box - grow it until every chip + one text line show
    message.style.height = "auto";                  // (offsetHeight is zero while empty, so the guard falls back to the typed-text height)
    message.style.height = Math.max(message.scrollHeight,
                                    chipsRow.children.length ? chipsRow.offsetHeight + 24 : 0) + "px";
  };

  function addPending(list, source) {   // a batch of files from one gesture (drop / paste / clip)
    for (const f of list) {
      if (!f || !f.name) continue;      // empty clipboard slots have no name - skip them quietly
      pendingFiles.push({ file: f, source });
    }
    renderChips();
  }

  document.getElementById("attachBtn").addEventListener("click", () => pick.click());
  pick.addEventListener("change", () => { addPending([...pick.files], "clip"); pick.value = ""; });
  message.addEventListener("paste", (e) => {  // pasted pictures/files -> attachments (all of them, v1.18.0)
    const files = [...(e.clipboardData && e.clipboardData.items || [])]
      .filter((it) => it.kind === "file").map((it) => it.getAsFile()).filter(Boolean);
    if (files.length) { addPending(files, "paste"); e.preventDefault(); }
  });

  // Pasted text arrives exactly as copied: multi-line content keeps its real line
  // breaks (the /post safety net folds them to \\n escapes for chat.txt) and literal
  // <b>/<i>/<u> tag pairs become stacked per-word prefixes, visible before posting.
  const fitBox = () => {  // v1.5.10: one line by default, grows with every new line
    message.style.height = "auto";
    message.style.height = message.scrollHeight + "px";
  };
  const insertAtCursor = (text) => {
    if (!document.execCommand || !document.execCommand("insertText", false, text)) {
      message.setRangeText(text, message.selectionStart, message.selectionEnd, "end");
      fitBox();
      message.focus();
    } else { message.focus(); fitBox(); }  // execCommand keeps native undo
  };
  const escapeWord = (word) => {  // a backslash in pasted text cannot start an escape
    return word.includes("\\") ? "\\\\" + word : word;  // doubled -> renders as one literal backslash
  };
  const normalizeTags = (s) => {  // <b>/<i>/<u> pairs -> stacked per-word prefixes, written order; v1.19.x: <s>/<strike>/<del> -> ~~span~~
    let out = "", stack = [], m;
    while ((m = s.match(/^(.*?)(?:<\/(b|i|u|s|strike|del)>|<(b|i|u|s|strike|del)>)/is))) {
      const plainPart = processPlain(m[1]);  // segment before the tag
      const name = (m[2] || m[3]).toLowerCase();   // strike/del normalise to s
      if (m[2]) {                              // closing: prefixes shrink with it
        const removed = stack.pop();
        out += plainPart + ((/^(s|strike|del)$/.test(removed || "")) ? "~~" : "");  // v1.19.x: close the strikethrough span only if we opened one
      } else {                                 // opening, duplicates ignored like format_text()
        if (!stack.includes(name)) {
          stack.push(name);
          out += plainPart + ((/^(s|strike|del)$/.test(name)) ? "~~" : "");  // v1.19.x: open the strikethrough span
        } else out += plainPart;
      }
      s = s.slice(m[0].length);
    }
    return out + processPlain(s);
    function processPlain(text) {  // every word gets the current prefix stack
      let res = "";
      const wordRe = /^(\s+|[^\s<]+)(.*)$/s;
      while (text.length) {
        const w = text.match(wordRe);
        if (!w) { res += escapeWord(text); break; }  // stray '<' is not a tag - stays literal
        // v1.5.8 fix: only prefix words inside an open <b>/<i>/<u> tag; plain pasted text passes through untouched
        // v1.19.x: while a strikethrough span is open, words stay bare (they live inside ~~...~~, which renders literal)
        res += /^\s/.test(w[1]) || !stack.length ? w[1]
             : stack.some((t) => /^(s|strike|del)$/.test(t)) ? w[1]   // v1.19.x: inside an open ~~ span words stay bare (renders literal)
             : "\\" + stack.join("") + escapeWord(w[1]);
        text = w[2];
      }
      return res;
    }
  };
  message.addEventListener("paste", (e) => {
    const plain = e.clipboardData.getData("text/plain");
    if (!plain || [...(e.clipboardData.items || [])].some((it) => it.kind === "file")) return;  // files handled above
    e.preventDefault();  // text paste -> normalize tags only, newlines stay real
    insertAtCursor(normalizeTags(plain));
  });
  message.addEventListener("keydown", (e) => {  // textarea: Enter posts, Shift+Enter inserts a line break
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  message.addEventListener("input", fitBox);  // v1.5.10: typing/pasting/Shift+Enter grows the box

  // Drag & drop: dropping a file onto the box attaches it exactly like pasting.
  form.addEventListener("dragover", (e) => {
    if (!(e.dataTransfer && [...e.dataTransfer.types].includes("Files"))) return;
    e.preventDefault();                       // allow the drop
    form.classList.add("drop-target");       // themed "release me" hint
  });
  form.addEventListener("dragleave", (e) => {  // ignore moves between child elements
    if (!form.contains(e.relatedTarget)) form.classList.remove("drop-target");
  });
  form.addEventListener("drop", (e) => {
    e.preventDefault();
    form.classList.remove("drop-target");
    addPending([...(e.dataTransfer ? e.dataTransfer.files : [])], "drop");   // v1.18.0: every dropped file becomes its own chip
  });

  form.addEventListener("submit", (e) => {
    const msg = document.getElementById("message");
    if (!msg.value.trim() && !pendingFiles.length) { e.preventDefault(); return; }
    e.preventDefault();                     // v1.16.2: drops/pastes stay direct up to DROP_MAX, the paperclip always chunks
    const files = pendingFiles.slice();     // v1.18.0: posting order - file 0 carries the text, each later one gets its own tilt
    const text = msg.value.trim();
    if (!files.length) {                    // v1.16.x: a plain text post never touches the upload paths
      const fd = new FormData(form);
      // Regression fix (v1.20.0): since v1.18.0 the name prefix lives in lineFor(), but that only runs on the file path -
      // this early return bypassed it, so a cookie name never reached chat.txt for plain-text posts again.
      // Same rule as lineFor(0); called directly here because lineFor() is TDZ-unreachable from inside its own callback scope.
      fd.set("message", name === DEFAULT_NAME ? text : name + ": " + text);
      // v1.25.0: go to page 1 after posting - the new tilt is always on top, and reloading
      // a stale URL (e.g. /?page=2 left over from earlier browsing) would hide it.
      fetch("/post", { method: "POST", body: fd }).then((r) => location.href = "/").catch(fail);
      return;
    }
    // v1.18.0 pre-flight: one oversized drop/paste aborts the whole batch BEFORE anything is posted -
    // nothing half-done, every chip stays untouched while the user re-attaches via the paperclip.
    const tooBig = files.filter((p) => p.source !== "clip" && p.file.size > DROP_MAX);
    if (tooBig.length) {
      alert(tooBig.map((p) => p.file.name).join("\n") +
            " - over 256 MB, too big for a direct drop.\nPlease attach it with the paperclip icon instead (it uploads in pieces).\nNothing was posted.");
      return;
    }
    function fail(detail, idx) { hideUpload(); pendingFiles.splice(0, idx); renderChips(); pick.value = ""; msg.value = text; alert("Upload failed - your post was restored." + (detail ? "\n(" + detail + ")" : "") + (idx > 1 ? "\nThe first " + (idx - 1) + " file(s) were already posted." : "")); }
    const label = () => files.length > 1 ? " (file " + postIdx + " of " + files.length + ")" : "";
    let postIdx = 0;
    // v1.18.0: the name prefix is applied here, per file - once at attempt start, so a second submit event on
    // this same batch can never re-prefix (the old listener now only guards plain-text posts).
    const lineFor = (i) => {  // chat.txt keeps the "user: text" shape; extra files get the bare prefix when one exists
      if (name === DEFAULT_NAME) return i === 0 ? text : "";
      return i === 0 ? name + ": " + text : name + ":";
    };
    // The batch is posted sequentially, one file at a time - each post reuses the
    // battle-tested single-file paths verbatim (direct multipart or chunked), so
    // nothing upload-side had to be re-invented. Input + chips are cleared right away.
    pendingFiles = []; renderChips(); pick.value = "";
    msg.value = "";
    const postJson = (path, payload) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }).then((r) => r.json());
    // v1.16.1: one flaky request no longer kills the whole transfer - every step
    // is retried (3 tries, 2 s / 4 s apart); chunk data never changes on retry.
    const withRetry = async (lbl, task) => {
      for (let attempt = 1; ; attempt++) {
        try { return await task(); }
        catch (err) { if (attempt > 3) throw new Error(lbl + " failed after 4 tries: " + err.message); await new Promise((w) => setTimeout(w, 2000 * attempt)); }
      }
    };
    // v1.22.0: slow_upload mode - a chunk that fails is simply retried at the SAME offset every ~30 s
    // (the server seeks to X-Chunk-Offset and overwrites, so repeating it can never duplicate bytes),
    // until it lands or the visitor closes the tab; no give-up count. Normal mode keeps withRetry.
    const slowStep = async (lbl, task) => {
      for (; ; ) { try { return await task(); } catch { await new Promise((w) => setTimeout(w, 30000)); } }
    };
    const step = window.SLOW_UPLOAD ? slowStep : withRetry;  // v1.22.0: only the chunk loop swaps to this
    const sendFile = (i, file, source, line) => {
      if (source === "clip") {              // v1.16.2: paperclip always chunks - retry-safe for any size
        let stored = null;                  // kept in outer scope so the catch below can abort it by name
        return withRetry("upload/init", () => postJson("/upload/init", { name: file.name || "pasted" }))
          .then(async (res) => {
            if (!res.ok || !res.stored) throw new Error(res.error || "could not reserve a file name");
            stored = res.stored;
            showUpload(file.name + label(), 0, file.size);   // v1.16.x: overlay appears as soon as the transfer starts
            for (let off = 0; off < file.size; off += SLOW_CHUNK) {   // ~8 MB slices normally, ~256 kB in slow_upload mode; server streams to disk in 1 MB reads
              await step("chunk " + Math.round(off / SLOW_CHUNK + 1), () =>    // v1.22.0: slowStep (30 s cadence) when SLOW_UPLOAD, withRetry otherwise
                fetch("/upload/chunk", { method: "POST", headers: { "X-Stored-Name": encodeURIComponent(stored), "X-Chunk-Offset": String(off) }, body: file.slice(off, Math.min(off + SLOW_CHUNK, file.size)) })  // v2.4.x: header must stay ISO-8859-1 - national chars percent-encoded here, unquoted on the server
                  .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); }));
              showUpload(file.name + label(), off + SLOW_CHUNK, file.size);   // v1.16.x: advance the bar after each successful slice
            }
            return withRetry("commit", () => postJson("/post", { message: line, attach_stored: stored }));  // commit = same line format as a normal attachment post
          })
          .catch((err) => {
            if (stored) fetch("/upload/abort", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stored: stored }) }).catch(function () {});  // best-effort cleanup of the partial file
            throw err;
          });
      }
      const fd = new FormData();             // v1.16.x direct path - one attachment per post, exactly as before
      fd.set("message", line);
      fd.append("attachment", file, file.name || "pasted");
      return fetch("/post", { method: "POST", body: fd });
    };
    const runBatch = (i) => {
      postIdx = i + 1;                        // v1.18.0: the overlay counter knows which file of the batch is uploading
      // v1.25.0: same as the plain-text post - land on page 1, never re-fetch a stale ?page=N
      if (i >= files.length) { location.href = "/"; return; }
      sendFile(i, files[i].file, files[i].source, lineFor(i))
        .then(() => runBatch(i + 1))          // v1.18.0: each extra file is its own tilt - posted one after another
        .catch((err) => fail(err && err.message, i));
    };
    runBatch(0);
  });
})();
</script>
<script>/* v2.1.x: submit -> /login -> fresh '/' carrying the signed tb_auth cookie */
(function () {
  const form = document.getElementById("loginForm");
  // v2.1.x: guard on TB_AUTH_ENABLED, not TB_AUTH_MODE - the latter is only baked into the
  // pre-login document, so a logged-in user re-locking via the settings Login button had no
  // working submit and could not dismiss the dialog ("can't be closed" bug). With this guard,
  // Enter/backdrop/Esc all work on both paths.
  if (!form || !window.TB_AUTH_ENABLED) return;
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    const msg = document.getElementById("loginMsg");
    const pass = document.getElementById("loginPass").value;
    fetch("/login", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: pass }) }
    ).then(function (r) { return r.text().then(function (t) {
        let j = null; try { j = JSON.parse(t); } catch (_) {}
        if (!j || !j.ok) throw new Error(j && j.error ? j.error : "login failed");
        location.replace("/");
      }); }).catch(function (err) {
      msg.textContent = String(err.message || err);
      document.getElementById("loginPass").focus();
    });
  });
})();
</script>
<script>
// Live update: poll /posts every 3 seconds and refresh only the board,
// so other people's posts appear without a manual page reload.
(function () {
  const board = document.getElementById("board");
  let lastSig = "";

  // v1.19.1: shared escape walk - lockstep with _fmt_loop()/format_text() on the server.
  // DOM-safe by construction (element + text nodes only, no innerHTML). depth limits ~~
  // nesting to one level; any further paired ~~ stays literal. `stop` bounds a span's
  // content walk to its own closing pair - v1.19.1 fix: without it the recursive call ran
  // past the closer and rendered it as an unmatched literal ~~.
  function fmtWalk(text, i, parent, depth, stop) {
    const n = (stop === undefined ? text.length : Math.min(stop, text.length));
    while (i < n) {
      const ch = text[i];
      if (ch === "\\" && "nubi".includes(text[i + 1] || "")) {
        const esc = text[++i];
        if (esc === "n") { parent.appendChild(document.createElement("br")); i++; continue; }
        // v1.5.8: stacked escapes - every chained \b/\u/\i prefix applies to the same word;
        // opens in written order, closes in reverse.
        const fmts = [esc];
        let j = i + 1;
        while (j < text.length && text[j] === "\\"
               && "bui".includes(text[j + 1] || "")) {
          if (!fmts.includes(text[j + 1])) fmts.push(text[j + 1]);
          j += 2;
        }
        let k = j;  // v1.7.1: a token ends where any recognized escape starts or at ~ - lockstep
        while (k < text.length && !/\s/.test(text[k]) && text[k] !== "~"
               && !(text[k] === "\\" && "nubi".includes(text[k + 1] || ""))) k++;
        if (k > j) {
          // v1.5.8 fix: nest the tags around the word - lockstep with format_text()
          let cur = parent;
          for (const t of fmts) { const el = document.createElement(t); cur.appendChild(el); cur = el; }
          cur.appendChild(document.createTextNode(text.slice(j, k)));  // text nodes only: no injection
          i = k;
        } else if (text.startsWith("~~", j)) {
          // v1.19.1: no word after the escapes, but a ~~span~~ follows - stacked prefixes wrap
          // its whole content; recurse into the span (depth-limited).
          const end = text.indexOf("~~", j + 2);
          if (end !== -1 && depth < 2) {
            let cur = parent;
            for (const t of fmts) { const el = document.createElement(t); cur.appendChild(el); cur = el; }
            const sEl = document.createElement("s");
            cur.appendChild(sEl);
            fmtWalk(text, j + 2, sEl, depth + 1, end);   // v1.19.1: bounded by the closing pair
            i = end + 2;
          } else { parent.appendChild(document.createTextNode(text.slice(i - 1, j))); i = j; }
        } else {
          // no word after the escapes (and no ~~span right behind) - keep them literal
          parent.appendChild(document.createTextNode(text.slice(i - 1, j)));
          i = j;
        }
      } else if (ch === "`") {
        const end = text.indexOf("`", i + 1);
        if (end !== -1) {
          const el = document.createElement("code");
          // v1.5.9: \n still breaks lines inside code spans; all else literal.
          let buf = "";
          for (let t = i + 1; t < end;) {
            if (text[t] === "\\" && text[t + 1] === "n") {
              if (buf) { el.appendChild(document.createTextNode(buf)); buf = ""; }
              el.appendChild(document.createElement("br"));
              t += 2;
            } else { buf += text[t]; t++; }
          }
          if (buf) el.appendChild(document.createTextNode(buf));
          parent.appendChild(el);
          i = end + 1;
        } else { parent.appendChild(document.createTextNode(ch)); i++; }
      } else if (text.startsWith("~~", i)) {
        // v1.19.0: ~~text~~ strikethrough - lockstep with format_text();
        // v1.19.1: escapes work inside the span too, nested pairs stay literal.
        const end = text.indexOf("~~", i + 2);
        if (end !== -1 && depth < 2) {
          const el = document.createElement("s");
          parent.appendChild(el);
          fmtWalk(text, i + 2, el, depth + 1, end);   // v1.19.1: bounded by the closing pair
          i = end + 2;
        } else { parent.appendChild(document.createTextNode("~~")); i += 2; }  // unmatched ~~ stays literal
      } else if (ch === "\n") { parent.appendChild(document.createElement("br")); i++; }
      else {
        // v1.21.0: auto-link URLs - lockstep with _fmt_loop(): find a known protocol
        // marker at this position, then copy everything up to the next space or backslash
        // (v1.21.1: so an escape like \n right after it is honoured) or the stop-bounded
        // end of the line - whichever comes first.
        let url = null;
        for (const p of ["http://", "https://", "ftp://"]) {
          if (text.startsWith(p, i)) {
            let endU = text.indexOf(" ", i);                    // v1.21.1: space or backslash
            const bsU = text.indexOf("\\", i);                  // terminates the href so a glued \n escape still works
            if (bsU !== -1 && (endU === -1 || bsU < endU)) endU = bsU;
            url = (endU === -1 || endU > n) ? text.slice(i, n) : text.slice(i, endU);
            break;
          }
        }
        if (url !== null && url.length > 0) {
          const a = document.createElement("a");
          a.className = "lnk";
          a.href = url;                              // DOM property: no escaping needed
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = url;
          parent.appendChild(a);
          i += url.length;
        } else { parent.appendChild(document.createTextNode(ch)); i++; }  // text nodes only: no injection
      }
    }
  }

  function render(posts) {  // newest first, as returned by /posts
    if (!posts.length) {
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = "Nothing posted yet - your tilted shapes will appear here.";
      board.replaceChildren(p);
      return;
    }
    const frag = document.createDocumentFragment();
    for (const post of posts) {
      const div = document.createElement("div");
      div.className = "tilt";
      div.style.setProperty("--tilt", post.tilt + "deg");
      div.dataset.c = post.color;
      if ([...post.text].some((ch) => ch.codePointAt(0) > 0xFFFF)) div.classList.add("has-emoji");
      const span = document.createElement("span");
      span.className = "text";
      const nm = /^([^:/\\\n`]{1,24}):(?: |$)/.exec(post.text);  // v1.6.0: name badge
      let i = nm ? nm[0].length : 0;  // same escape set as format_text(), DOM-safe by construction
      if (nm) { const u = document.createElement("span"); u.className = "user";
                u.textContent = nm[1]; span.appendChild(u); }
      fmtWalk(post.text, i, span, 0);  // v1.19.1: shared escape walk - lockstep with format_text()
      if (post.attach) {
        if (post.attach.is_image) {
          const wrap = document.createElement("span");  // v1.5.3: hover-download icon
          wrap.className = "attach-img";
          const img = document.createElement("img");   // inline preview inside the tilt
          img.className = "preview";
          img.src = post.attach.url;
          img.alt = post.attach.name;
          const dl = document.createElement("a");      // bottom-right download icon on hover
          dl.href = post.attach.url;
          dl.download = post.attach.name;              // saves with the original name
          dl.className = "dl";
          dl.title = "Download";
          dl.textContent = "\u2B07";
          wrap.appendChild(img);
          wrap.appendChild(dl);
          div.appendChild(span);
          div.appendChild(wrap);
        } else if (post.attach.preview) {              // v2.3.0: in-card preview + download link
          const slot = document.createElement("span");
          slot.className = "preview-slot";
          slot.dataset.type = post.attach.preview;
          slot.dataset.url = post.attach.url;           // same URL the server HTML uses
          div.appendChild(span);
          div.appendChild(slot);
        } else {                                       // data file -> download link only
          const a = document.createElement("a");
          a.href = post.attach.url;
          a.className = "download";
          a.textContent = "\u{1F4C4} " + post.attach.name;
          div.appendChild(span);
          div.appendChild(a);
        }
        if (post.attach && post.attach.preview) {      // download link kept on every card
          const dl2 = document.createElement("a");
          dl2.href = post.attach.url;                  // downloads with the original name
          dl2.download = post.attach.name;
          dl2.className = "download";
          dl2.textContent = "\u{1F4C4} " + post.attach.name;
          div.appendChild(dl2);
        }
      } else div.appendChild(span);
      // v1.5.4: same delete cross + identity as the server-rendered cards
      const del = document.createElement("button");
      del.className = "del";
      del.title = "Delete this tilt";
      del.textContent = "\u2715";  // U+2715, same glyph as &#10005; in the server HTML
      div.dataset.text = post.text;
      div.dataset.attach = post.attach ? post.attach.name : "";
      div.dataset.id = post.id || "";  // v2.2.0: identity token for drag & drop swap
      // v1.23.0: rating row - same structure the server HTML emits
      const rate = document.createElement("span");
      rate.className = "rate";
      const counts = Array.isArray(post.rating) ? post.rating : [0, 0, 0, 0];
      [["up", "\u{1F44D}", "Rate up"], ["down", "\u{1F44E}", "Rate down"],
       ["heart", "\u2764\uFE0F", "Love it"], ["smile", "\u{1F600}", "Funny"]]
        .forEach(([name, glyph, title], k) => {
          const b = document.createElement("button");
          b.className = "rate-btn";
          b.dataset.icon = name;
          b.title = title;
          b.textContent = glyph;
          if (counts[k] > 0) {  // zero counts render no badge, same as the server HTML
            const c = document.createElement("b");
            c.textContent = String(counts[k]);
            b.appendChild(c);
          }
          rate.appendChild(b);
        });
      div.appendChild(rate);
      div.appendChild(del);
      frag.appendChild(div);
    }
    board.replaceChildren(frag);
    markRated();  // v1.23.0 fix: re-apply vote marks AFTER the swap - marking the
                  // old DOM before replaceChildren was a no-op (re-rate bug)
    if (window.tbRebootPreviews) window.tbRebootPreviews();  // v2.4.x: fresh slots need rendering
  }

  // v1.7.0: per-visitor board grid - this user's own rows x columns decides
  // how many cards fill a page, so paging is owned here. The URL's ?page= still
  // seeds the starting page; arrows step within the visitor's own pages without
  // any full reload. (readCookie is re-declared locally: separate IIFE scope.)
  const params = new URLSearchParams(location.search);
  function readCookie() {
    for (const part of document.cookie.split(";")) {
      const idx = part.indexOf("=");
      if (idx > -1 && part.slice(0, idx).trim() === "tiltboard")
        return new URLSearchParams(decodeURIComponent(part.slice(idx + 1)));
    }
    return null;
  }
  const savedGrid = readCookie();
  function gridVal(v) { return parseInt(v, 10); }
  let rows = gridVal(savedGrid && savedGrid.get("rows"));
  if (!(rows >= 1 && rows <= 1000)) rows = window.DEFAULT_ROWS;
  let cols = gridVal(savedGrid && savedGrid.get("cols"));
  if (!(cols >= 1 && cols <= 100)) cols = window.DEFAULT_COLUMNS;

  // The board is a CSS grid: --cols drives the column count, and the wrap's
  // max-width grows with it so multi-column layouts get real room (a single
  // column keeps the classic 640px frame exactly).
  const rootStyle = document.documentElement.style;
  function applyGrid() {
    rootStyle.setProperty("--cols", cols);
    document.querySelector(".wrap").style.maxWidth = (cols <= 1 ? 640 : Math.min(cols * 452 - 18 + 32, 1700)) + "px";
  }
  applyGrid();

  let page = Math.max(parseInt(params.get("page"), 10) || 1, 1);  // ?page= seeds it
  const postsUrl = () => "/posts?page=" + page + "&rows=" + rows + "&cols=" + cols;

  function renderPager(totalPages) {
    // Rebuild BOTH server-rendered pagers (top and bottom of the board) with
    // arrows matching THIS visitor's page size - the injected ones only seed
    // the first paint at the config grid.
    const mk = (href, label, disabled, cls) => {
      const el = document.createElement(disabled ? "span" : "a");
      el.className = "arrow" + (disabled ? " disabled" : "") + (cls ? " " + cls : "");
      el.innerHTML = label;  // v1.9.x: Unicode media glyphs; jump-5 arrows are a tight
                             // pair of full-height, half-width triangles (see .arrow .half)
      if (!disabled) el.href = href;
      return el;
    };
    for (const p of document.querySelectorAll(".pager")) {
      const info = document.createElement("span");
      info.className = "pager-info";  // same class the server renders - themes style this
      info.textContent = "Page " + page + " of " + totalPages;
      // v1.9.x: full navigation set as two tight triplets - ⏮ ◀◀ ◀ left of the
      // info span and ▶ ▶▶ ⏭ mirrored on its right (same rules as render_pager,
      // this visitor's pages).
      const leftGroup = document.createElement("span");
      leftGroup.className = "pager-group";
      leftGroup.append(
        mk(page > 1 ? "/?page=1" : null, '<span class="g">\u23EE</span>', page <= 1, "pg-end"),
        mk(page > 5 ? "/?page=" + (page - 5) : null, '<span class="half"><span>\u25C0</span></span><span class="half"><span>\u25C0</span></span>', !(page > 5)),
        mk(page > 1 ? "/?page=" + (page - 1) : null, '<span class="gs">\u25C0</span>', page <= 1));
      const rightGroup = document.createElement("span");
      rightGroup.className = "pager-group";
      rightGroup.append(
        mk(page < totalPages ? "/?page=" + (page + 1) : null, '<span class="gs">\u25B6</span>', page >= totalPages),
        mk(page + 5 <= totalPages ? "/?page=" + (page + 5) : null, '<span class="half"><span>\u25B6</span></span><span class="half"><span>\u25B6</span></span>', !(page + 5 <= totalPages)),
        mk(page < totalPages ? "/?page=" + totalPages : null, '<span class="g">\u23ED</span>', page >= totalPages, "pg-end"));
      p.replaceChildren(leftGroup, info, rightGroup)
    }
  }

  async function poll() {
    if (window.TB_AUTH_MODE) return;  // v2.1.x: locked visitor - /posts would only ever 401
    if (window.tiltSearchActive && window.tiltSearchActive()) return;  // v1.14.0: filter owns the board
    try {
      const res = await fetch(postsUrl(), { cache: "no-store" });
      // v2.1.5: our cookie is gone (password changed, cookies cleared elsewhere) - any further poll would
      // 401 every tick; park in auth mode so the guard above stops poll() until this tab reloads or logs in
      if (res.status === 401) { window.TB_AUTH_MODE = true; return; }
      if (!res.ok) return;
      const data = await res.json();  // v1.7.0: {total, posts} - total drives the pager
      const posts = data.posts || [];
      renderPager(Math.max(1, Math.ceil(data.total / (rows * cols))));
      const sig = JSON.stringify(posts);  // re-render only when something changed
      if (sig !== lastSig) { lastSig = sig; render(posts); }
    } catch (_) { /* server briefly unreachable - try again next tick */ }
  }

  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest(".pager .arrow");
    if (!a || !a.href) return;             // disabled arrow -> nothing happens
    e.preventDefault();                    // step pages without a full reload
    page = Math.max(1, parseInt(a.href.split("page=")[1], 10));
    lastSig = "";                          // new page: force the re-render below
    poll();
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { lastSig = ""; poll(); }  // throttled background tab caught up on focus
  });
  poll();
  setInterval(poll, 3000);
  window.tiltRender = render;                       // v1.14.0: shared by the search filter
  window.tiltRefresh = () => { lastSig = ""; poll(); };  // v1.14.0: re-arm after a search closes
})();
</script>

<script>
// v1.14.0: search bar - a live filter over the whole chat.txt, toggled by the
// magnifier left of the settings gear. Three characters or more activate it;
// space-separated tokens are AND-ed with prefix shortcuts (n:/u: poster name,
// f: attachment file name, c: message body only). Results reuse render(), so a
// match looks exactly like a normal tilt - and both pagers hide while active.
(function () {
  const icon = document.getElementById("searchIcon");
  const input = document.getElementById("searchInput");
  let searching = false, seq = 0;

  window.tiltSearchActive = () => searching;  // the poller skips rendering while this is on

  const wrap = document.querySelector(".wrap");
  function place() {  // left = composer text box, right = Post button's edge;
                      // push the whole page down so it keeps an 8px gap under the bar
    const c = document.querySelector("form.composer");
    if (!c) return;
    const r = c.getBoundingClientRect();
    let width = Math.max(200, r.width);
    // v1.20.0: the magnifier is fixed to the browser's right border - in multi-column layouts the composer's rect
    // can run past it and the bar overlaps the icon; trim the width instead (both rects are viewport-relative).
    const ir = icon.getBoundingClientRect();
    if (r.left + width > ir.left - 8) width = Math.max(160, ir.left - 8 - r.left);   // keep an 8px gap before the icon
    input.style.left = r.left + "px";
    input.style.width = width + "px";
    if (wrap && !input.classList.contains("hidden")) {
      wrap.style.paddingTop = (8 + input.offsetHeight + 8) + "px";   // themes give an 8px top gap already
    }
  }
  window.addEventListener("resize", () => { if (!input.classList.contains("hidden")) place(); });

  function showResults(posts, q) {
    for (const p of document.querySelectorAll(".pager")) p.classList.add("hidden");
    if (!posts.length) {  // render()'s own empty note talks about posting, not searching
      const e = document.createElement("p");
      e.className = "empty";
      e.textContent = 'No tilts match \u201C' + q + '\u201D.';
      board.replaceChildren(e);
      return;
    }
    window.tiltRender(posts);  // the poller's own renderer - badges, pictures and delete cross included
  }

  function close() {
    searching = false;
    input.value = "";
    if (wrap) wrap.style.paddingTop = "";   // back to the stylesheet's 8px gap
    input.classList.add("hidden");
    icon.setAttribute("aria-pressed", "false");
    for (const p of document.querySelectorAll(".pager")) p.classList.remove("hidden");
    window.tiltRefresh && window.tiltRefresh();  // back to the visitor's normal page
  }

  function run(q) {
    const my = ++seq;
    fetch("/search?q=" + encodeURIComponent(q), { cache: "no-store" })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (my === seq && d) showResults(d.posts || [], q); });  // stale responses dropped
  }

  input.addEventListener("input", () => {
    const q = input.value.trim();
    if (q.length < 3 || !/[\w:]/.test(q)) {   // below the minimum, or nothing searchable in it
      searching = false;
      for (const p of document.querySelectorAll(".pager")) p.classList.remove("hidden");
      window.tiltRefresh && window.tiltRefresh();
      return;
    }
    if (!searching) {
      searching = true;  // the poller now skips rendering - filter results stay put
      for (const p of document.querySelectorAll(".pager")) p.classList.add("hidden");
    }
    run(q);
  });

  icon.addEventListener("click", () => {
    if (!input.classList.contains("hidden")) { close(); return; }  // second click: clear + hide
    input.classList.remove("hidden"); place(); input.focus();
    icon.setAttribute("aria-pressed", "true");
  });
})();
</script>
<script>
// v1.5.4: delete a tilt - hover cross -> Delete/Cancel dialog -> POST /delete.
// The server removes the matching line from chat.txt and physically deletes
// the source file/picture if it still exists in the data folder.
(function () {
  const overlay = document.getElementById("confirmOverlay");
  const msg = document.getElementById("delMsg");
  let pending = null;

  function openDialog(card) {
    pending = { text: card.dataset.text, attach: card.dataset.attach || null };
    const what = pending.attach ? (card.querySelector(".attach-img") ? "its picture" : "the attached file") : "";
    msg.textContent = `Delete \u201C${pending.text}\u201D? ${what} will be physically deleted from the server too.`.trim();
    overlay.classList.remove("hidden");
    overlay.setAttribute("aria-hidden", "false");
  }

  function closeDialog() {
    pending = null;
    overlay.classList.add("hidden");
    overlay.setAttribute("aria-hidden", "true");
  }

  document.getElementById("delNo").addEventListener("click", closeDialog);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closeDialog(); }); // backdrop = cancel
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDialog(); });

  document.getElementById("delYes").addEventListener("click", () => {
    const post = pending;
    closeDialog();
    fetch("/delete", { method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ text: post.text, attach: post.attach }) })
      .then((r) => r.json().catch(() => ({})))
      // v1.25.0: after a successful delete, show the fresh board on page 1 -
      // reloading in place could re-fetch a stale ?page=N from the address bar.
      .then((res) => { if (res && res.ok) location.href = "/"; else alert("Delete failed: " + ((res && res.error) || "unknown error")); })
      .catch(() => alert("Delete failed - could not reach the server."));
  });

  // v1.23.0: one vote per visitor per tilt - localStorage is the simple
  // method; clearing browser cache re-allows rating, exactly as intended.
  function rateFp(card) { return "rated:" + card.dataset.text + "|" + (card.dataset.attach || ""); }
  function markRated() {
    for (const card of document.querySelectorAll(".tilt")) {
      if (!localStorage.getItem(rateFp(card))) continue;
      for (const b of card.querySelectorAll(".rate-btn")) b.classList.add("rated");
    }
  }
  window.markRated = markRated;  // v1.23.0 fix: render() in the poller script re-applies vote
                                 // marks on every re-render - it needs cross-script reach
  function rateTilt(btn) {
    const card = btn.closest(".tilt");
    fetch("/rate", { method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text: card.dataset.text,
                                           attach: card.dataset.attach || null,
                                           icon: btn.dataset.icon }) })
      .then((r) => r.json().catch(() => ({})))
      .then((res) => {
        if (!res || !res.ok) { alert("Rating failed: " + ((res && res.error) || "unknown error")); return; }
        localStorage.setItem(rateFp(card), "1");  // remember this visitor's vote
        const counts = Array.isArray(res.rating) ? res.rating : [0, 0, 0, 0];
        card.querySelectorAll(".rate-btn").forEach((b, k) => {  // update in place - no reload,
          b.classList.add("rated");                            // scroll position is kept
          let badge = b.querySelector("b");
          if (counts[k] > 0) {
            if (!badge) badge = document.createElement("b"), b.appendChild(badge);
            badge.textContent = String(counts[k]);
          } else if (badge) badge.remove();
        });
      })
      .catch(() => alert("Rating failed - could not reach the server."));
  }
  // One listener for every card on the board, live-polled or server-rendered.
  document.getElementById("board").addEventListener("click", (e) => {
    const del = e.target.closest && e.target.closest(".tilt .del");
    if (del) { openDialog(del.closest(".tilt")); return; }
    const rb = e.target.closest && e.target.closest(".tilt .rate-btn");
    if (rb && !rb.classList.contains("rated")) rateTilt(rb);
  });
})();
</script>
<script>
/* v2.2.0: drag & drop card swapping (full-access visitors only). Mousedown on a tilt's
   background, more than 5px of movement starts the drag; when the card sits inside another
   tilt's inner rectangle (the middle 2/3 zone per spec), both cards pulse as a swap preview;
   releasing there POSTs /swap with both cards' identity tokens and reloads the page.
   Mousedown on the tilt's text is NOT a drag: native text selection keeps working there,
   while background drags preventDefault() so no text gets selected along the way. */
(function () {
  if (window.TB_RO) return;  // read-only visitors never get reordering
  const board = document.getElementById("board");
  if (!board) return;
  // preview animation injected at runtime so no theme .css file is touched:
  // while a drag is held, EVERY hovered card shrinks AND rocks side-to-side (translate,
  // so it composes with each card's own --tilt rotation) - one uniform behavior for all
  const st = document.createElement("style");
  st.textContent = ".tilt.tb-swap-prev { animation: tbSwapPreview .35s ease-in-out infinite alternate; }\n"
    + "@keyframes tbSwapPreview { from { translate: -8px 0; opacity:.92; } to { translate: 8px 0; opacity:1; } }\n"
    + ".tb-drag-active .tilt:hover { transform: rotate(var(--tilt)) scale(.9) !important; z-index:3; transition:transform .15s ease; animation: tbSwapPreview .35s ease-in-out infinite alternate !important; }\n"
    + ".tilt.tb-drag-ghost { position:fixed !important; margin:0 !important; pointer-events:none; z-index:9999; opacity:.6; box-shadow:0 8px 24px rgba(0,0,0,.35) !important; }\n"
    + "@keyframes tbGhostPop { from { scale:.85; } to { scale:1; } }";
  document.head.appendChild(st);
  let heldCard = null, startX = 0, startY = 0, dragging = false;
  // the transparent clone that sticks to the cursor while a drag is active
  let ghost = null;

  function cardFromEvent(e) {
    const el = e.target;
    // ignore interactive content: buttons (delete / rate), links, pictures,
    // composer and any open overlay - only a tilt's own background starts a drag
    if (!el || !el.closest) return null;
    if (el.closest("button, a, img, .composer, #confirmOverlay, #loginOverlay")) return null;
    if (el.closest(".tilt .text")) return null;  // text area: native selection only, never a drag
    if (!document.getElementById("settingsBox").classList.contains("hidden")) return null;
    return el.closest(".tilt") || null;
  }

  function innerZoneHit(x, y) {
    for (const other of board.querySelectorAll(".tilt")) {
      if (other === heldCard) continue;
      const r = other.getBoundingClientRect();
      const dx = x - r.left, dy = y - r.top, w = r.width, h = r.height;
      // user spec: the middle 2/3 zone of a card
      if (dx >= w / 6 && dx < 5 * w / 6 && dy >= h / 6 && dy < 5 * h / 6) return other;
    }
    return null;
  }

  function setPreview(hit) {
    if (target === hit) return;
    board.querySelectorAll(".tb-swap-prev").forEach(el => el.classList.remove("tb-swap-prev"));
    target = hit;
    if (hit && dragging) { heldCard.classList.add("tb-swap-prev"); target.classList.add("tb-swap-prev"); }
  }

  function disarm() {
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  }

  function killGhost() { if (ghost) { ghost.remove(); ghost = null; } }

  function moveGhost(x, y) {
    // centered on the cursor: card stays under the mouse no matter where it was pressed
    const r = ghost.getBoundingClientRect();
    ghost.style.left = Math.round(x - r.width / 2) + "px";
    ghost.style.top = Math.round(y - r.height / 2) + "px";
  }

  function makeGhost(card, x, y) {
    if (ghost) return;  // one clone per drag
    const r = card.getBoundingClientRect();
    ghost = card.cloneNode(true);        // deep copy: text, rating row, buttons all travel along
    ghost.classList.add("tb-drag-ghost");
    ghost.style.width = r.width + "px";  // grid columns size .tilt, so fix the width explicitly
    document.body.appendChild(ghost);
    moveGhost(x, y);
  }

  function releaseVisuals() {
    killGhost();                        // a released drag drops its ghost
    heldCard.style.opacity = "";
    document.body.classList.remove("tb-drag-active");  // hover zoom + wiggle stop after release
  }

  function onMove(e) {
    if (!heldCard) return;
    if (!dragging) {  // the >5px threshold: a click or micro-slide never drags
      const dist = Math.abs(e.clientX - startX) + Math.abs(e.clientY - startY);
      if (dist < 5) return;
      dragging = true;
      document.body.classList.add("tb-drag-active");  // every hovered card now shrinks instead of zooming
      heldCard.style.opacity = "0.5";  // original stays behind as a dimmed empty slot
      makeGhost(heldCard, e.clientX, e.clientY);
    }
    e.preventDefault();  // an active drag never starts native text selection along its path
    if (dragging && ghost) moveGhost(e.clientX, e.clientY);  // the clone sticks to the cursor
  }

  function onUp(e) {
    if (!heldCard) return;
    const card = heldCard, wasDragging = dragging, hit = innerZoneHit(e.clientX, e.clientY);
    disarm(); releaseVisuals();
    heldCard = null; dragging = false;
    if (!wasDragging || !hit) return;  // plain click or released outside any zone
    fetch("/swap", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idA: card.dataset.id || "",
                             textA: card.dataset.text || "",
                             attachA: card.dataset.attach || "",
                             idB: hit.dataset.id || "", textB: hit.dataset.text || "",
                             attachB: hit.dataset.attach || "" })
    }).then(r => r.json()).then(j => {
      if (j.ok) location.reload();
      else alert("Swap failed - your board was not changed.");
    }).catch(() => alert("Swap failed - could not reach the server."));
  }

  board.addEventListener("mousedown", e => {
    if (e.button !== 0 || dragging) return;
    const card = cardFromEvent(e);
    if (!card) return;
    e.preventDefault();  // background press: no accidental text selection may start from it
    heldCard = card; startX = e.clientX; startY = e.clientY; dragging = false;
    document.addEventListener("mousemove", onMove);   // armed until the threshold
    document.addEventListener("mouseup", onUp, { once: true });
  });
})();
</script>
<script>
// v1.5.5: emoji picker - a built-in grid between the text box and attachment icon.
// Offline by design: no CDN library, just curated \u{...} escapes (ASCII-safe source).
(function () {
  const btn = document.getElementById("emojiBtn");
  const pick = document.getElementById("emojiPicker");
  const msg = document.getElementById("message");
  if (!btn || !pick || !msg) return;

  // Curated grid (~135 emoji). \u{...} escapes keep the source free of raw emoji.
  // FE0F (variation selector) is appended to text-default symbols so they always
  // render as color glyphs - without it browsers may show a plain monochrome char.
  const EMOJIS = [
    "\u{1F600}","\u{1F602}","\u{1F603}","\u{1F604}","\u{1F605}","\u{1F606}","\u{1F923}","\u{1F609}",
    "\u{1F60A}","\u{1F60B}","\u{1F642}","\u{1F60C}","\u{1F917}","\u{1F920}","\u{1F633}",
    "\u{1F601}","\u{1F929}","\u{1F92A}","\u{1F92D}","\u{1FAE3}","\u{1F92E}","\u{1F973}","\u{1F624}",
    "\u{1F625}","\u{1F62D}","\u{1F61E}","\u{1F61C}","\u{1F628}","\u{1F60F}","\u{1F914}",
    "\u{1F91D}","\u{1F924}","\u{1F634}","\u{1F629}","\u{1F631}","\u{1F97A}","\u{1F60D}",
    "\u{1F61A}","\u{1F61B}","\u{1F622}","\u{1F62E}","\u{1F975}","\u{1F644}",
    "\u{1F90D}","\u{1F636}","\u{1F648}","\u{1F64B}","\u{2764}\uFE0F","\u{1F495}","\u{1F49D}",
    "\u{1F494}","\u{1F49A}","\u{1F44F}","\u{270C}","\u{1F596}","\u{1F44C}","\u{1F44D}",
    "\u{1F44E}","\u{1F91F}","\u{1F918}","\u{270B}","\u{1FAF0}","\u{1F919}","\u{1F64F}","\u{1F4AA}","\u{1F4AF}",
    "\u{1FAF5}","\u{1F91C}","\u{1F64C}","\u{1F389}","\u{1F38A}","\u{2728}","\u{1F4AC}",
    "\u{1F525}","\u{1F60E}","\u{1F913}","\u{1F9D0}","\u{1F928}","\u{1F47A}","\u{1F47B}",
    "\u{1F47D}","\u{2620}\uFE0F","\u{1F4A9}","\u{1F431}","\u{1F432}","\u{1F98A}","\u{1F436}",
    "\u{1F43B}","\u{1F984}","\u{1F99B}","\u{1F98E}","\u{1F42D}","\u{1F407}","\u{1F986}","\u{1F9D9}","\u{1F9A1}",
    "\u{1F43E}","\u{1F408}","\u{1F427}","\u{1F437}","\u{1F41F}","\u{1F95D}","\u{1F98B}",
    "\u{1F430}","\u{1F41A}","\u{1F43C}","\u{2615}","\u{1F37D}\uFE0F","\u{1F37E}","\u{1F37A}",
    "\u{1F37B}","\u{1F354}","\u{1F951}","\u{1F95A}","\u{1F36B}","\u{1F490}","\u{274C}","\u{1F6D1}",
    "\u{2705}","\u{274E}","\u{1F382}","\u{1F9E8}","\u{26BD}","\u{1F3C0}","\u{1F440}",
    "\u{1F30D}","\u{1F3ED}","\u{1F6A6}","\u{27A4}\uFE0E","\u{2794}\uFE0E","\u{25CB}\uFE0E",
    "\u{25CF}\uFE0E","\u{1F31E}","\u{1F308}","\u{26A1}","\u{2744}\uFE0F","\u{1F384}",
    "\u{1F5A5}\uFE0F","\u{1F50D}","\u{1F4C4}","\u{2709}\uFE0F","\u{2699}\uFE0F",
    "\u{1F6AC}","\u{2622}\uFE0F"
  ];

  for (const e of EMOJIS) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "emojiCell";
    b.textContent = e; b.title = e;
    pick.appendChild(b);
  }

  function toggle(force) {
    const show = force !== undefined ? force : pick.classList.contains("hidden");
    pick.classList.toggle("hidden", !show);
  }

  btn.addEventListener("click", (e) => { e.stopPropagation(); toggle(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") toggle(false); });
  document.addEventListener("click", (e) => {
    if (!pick.classList.contains("hidden") && !pick.contains(e.target) && e.target !== btn) toggle(false);
  });

  pick.addEventListener("click", (e) => {
    const cell = e.target.closest && e.target.closest(".emojiCell");
    if (!cell) return;
    msg.focus();
    // Insert at the real cursor position; multi-codepoint emoji stay one unit.
    const start = msg.selectionStart != null ? msg.selectionStart : msg.value.length;
    const end = msg.selectionEnd != null ? msg.selectionEnd : start;
    msg.setRangeText(cell.textContent, start, end, "end");  // caret lands after the emoji
    msg.dispatchEvent(new Event("input", { bubbles: true }));
  });
})();
</script>
<script>
// v2.3.0: attachment previews inside cards - pdf / office (docx|odt) / markdown /
// plain text / html / media. Libraries are fetched from /libs/ on demand and cached
// per browser session; every card keeps its download link regardless of preview type.
(function () {
  "use strict";
  var loaded = {};                                       // url -> Promise, load each lib once
  function loadLib(url) {
    if (!loaded[url]) loaded[url] = new Promise(function (res, rej) {
      var s = document.createElement("script");
      s.src = url;                                        // /libs/* served with year-long cache
      s.onload = res;
      s.onerror = function () { rej(new Error("lib failed: " + url)); };
      document.head.appendChild(s);
    });
    return loaded[url];
  }
  var pdfWorkerSet = false;
  async function renderPdf(slot) {
    await loadLib("/libs/pdf.js-3.11.174.min.js");
    if (!pdfWorkerSet) { window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/libs/pdf.worker.min.js"; pdfWorkerSet = true; }
    var r = await fetch(slot.dataset.url);                // /files/ sets the real Content-Type
    var doc = await window.pdfjsLib.getDocument({ data: await r.arrayBuffer() }).promise;
    var page = await doc.getPage(1);
    var base = page.getViewport({ scale: 1 });
    /* v2.4.x: clientWidth includes the slot's padding - subtract it so the
       canvas keeps a visible gap to every card edge instead of touching one */
    var pcs = getComputedStyle(slot);
    var avail = (slot.clientWidth || 360) - parseFloat(pcs.paddingLeft || 0) - parseFloat(pcs.paddingRight || 0);
    var fitW = Math.min(avail, base.width);                  // fit-to-width
    var view = page.getViewport({ scale: fitW / base.width });
    if (view.height > 520) view = page.getViewport({ scale: 520 / base.height });   // max-height clamp
    var cv = document.createElement("canvas");            // pdf.js draws to a canvas, not HTML
    cv.width = Math.floor(view.width);
    cv.height = Math.floor(view.height);
    await page.render({ canvasContext: cv.getContext("2d"), viewport: view }).promise;
    slot.appendChild(cv);
  }
  async function renderHtmlDoc(slot) {                    // docx / odt -> capped HTML
    await loadLib("/libs/mammoth.browser.min.js");
    var r = await fetch(slot.dataset.url);                // mammoth needs an ArrayBuffer
    var res = await window.mammoth.convertToHtml({ arrayBuffer: await r.arrayBuffer() });
    capBlocks(slot, res.value);
  }
  async function renderMarkdown(slot) {
    await loadLib("/libs/marked.min.js");                 // v4 UMD exposes marked.parse
    var r = await fetch(slot.dataset.url);                // text/markdown - plain fetch is enough
    capBlocks(slot, window.marked.parse(await r.text()));
  }
  async function renderExcel(slot) {                      // v2.5.x: .xlsx -> SheetJS table (first sheet only)
    await loadLib("/libs/xlsx.full.min.js");              // UMD exposes window.XLSX
    var r = await fetch(slot.dataset.url);                // /files/ sets the real Content-Type
    var wb = window.XLSX.read(await r.arrayBuffer(), { type: "array" });
    if (!wb.SheetNames.length) throw new Error("workbook has no sheets");
    capBlocks(slot, window.XLSX.utils.sheet_to_html(wb.Sheets[wb.SheetNames[0]], { header: "", footer: "" }));
  }
  function capBlocks(slot, html) {                        // ~20 block lines / ~800 chars + hint
    // v2.5.x: kill disallowed <img> refs in the SOURCE before DOM insertion - README.md's
    // "screenshots/..." used to hit :8000 and 404 on every card render; only our own file
    // stream, data: URIs or absolute http(s) may load at all.
    html = String(html).replace(/<img\b[^>]*>/gi,
      (tag) => { const m = /src=["']?([^"' >]+)/i.exec(tag); return (m && /^(?:\/files\/|data:|https?:\/\/)/.test(m[1])) ? tag : ""; });
    slot.innerHTML = html;
    for (const im of slot.querySelectorAll("img"))        // v2.4.1: images embedded in a preview that can't load vanish -
      if (!/^(?:\/files\/|data:|https?:\/\/)/i.test(im.getAttribute("src") || "")) {  // relative paths would hit :8000 and 404 (e.g. README.md
        im.remove();                                       // screenshots) instead of showing a broken box
      } else if (im.complete && !im.naturalWidth) im.remove();
      else im.addEventListener("error", () => im.remove()); // remote/absolute src that fails later is removed too
    if (slot.textContent.length > 800 || slot.children.length > 24)
      slot.appendChild(hint());                           // CSS max-height is the backstop
  }
  async function renderRtf(slot) {                        // v2.5.x: real RTF rendering via rtfjs (libs/rtfjs.global.js - canvas per page)
    try {
      await loadLib("/libs/rtfjs.global.js");             // UMD script tag -> window.RTFRenderer
      var src = await (await fetch(slot.dataset.url)).text();   // .rtf is plain text to a browser fetch
      slot.innerHTML = "";
      var res = window.RTFRenderer.render(src, slot);    // sync parse->layout->canvas, stacked vertically in the slot
      for (let i = 0; i < res.canvases.length; i++) {
        const cv = res.canvases[i];
        if (i > 0) { cv.remove(); continue; }             // first page only - full document stays in the download
        cv.style.maxWidth = "100%";
        cv.style.height = "auto";
      }
      if (!res || !res.pageCount) throw new Error("rtfjs produced no pages");
    } catch (e) {
      await renderRtfLegacy(slot);                       // corrupt rtf / lib missing -> v2.3.0 plain-text preview
    }
  }
  async function renderRtfLegacy(slot) {                 // v2.3.0 plain-text backup - kept for rollback
    var src = await (await fetch(slot.dataset.url)).text();
    src = src.replace(/(?:\\'[0-9a-fA-F]{2})+/gi, (m) => {                   // 'hh runs are UTF-8 bytes of one character
      var b = [];
      for (var i = 0; i < m.length; i += 4) b.push(parseInt(m.substr(i + 2, 2), 16));
      try { return new TextDecoder("utf-8", { fatal: false }).decode(new Uint8Array(b)); } catch (e) { return ""; }
    });
    src = src.replace(/\\u(\d+)\s?[?!]/g, (m, d) => String.fromCharCode((parseInt(d) + 0x10000) % 0x10000)); // \uN? unicode escape
    src = src.replace(/\\(?:par|line|sect)\b/g, "\n");                      // paragraph / line breaks survive as newlines
    src = src.replace(/\\(?:[a-zA-Z]+-?\d*|[^\s0-9])\s?/g, " ");           // every control word AND symbol (\fs24 \*, \~, ...) -> space: plain text only
    src = src.replace(/[{}]/g, "");                                          // group braces vanish entirely
    var lines = src.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 20);   // first ~20 real lines only
    slot.innerHTML = "";
    var pre = document.createElement("pre");              // same capped <pre> as plain text files
    pre.textContent = lines.join("\n") + (lines.length ? "…" : "");
    slot.appendChild(pre);
  }
  async function renderText(slot) {                       // log / csv / ini / conf ... capped <pre>
    var r = await fetch(slot.dataset.url);
    var lines = (await r.text()).split(/\r?\n/).slice(0, 20);   // first ~20 lines only
    slot.innerHTML = "";
    var pre = document.createElement("pre");              // monospace preview of the raw content
    pre.textContent = lines.join("\n") + (lines.length ? "…" : "");
    slot.appendChild(pre);
  }
  function renderIframe(slot) {                           // html file: sandbox="" = zero capabilities
    var f = document.createElement("iframe");             // no allow-scripts, no same-origin escape
    f.sandbox = "";
    /* no srcdoc here at all: an empty one would beat `src` in the render order and show up as text */
    f.src = slot.dataset.url;
    slot.appendChild(f);
  }
  function renderMedia(slot) {                            // video / audio: native inline playback
    /* v2.4.x: the old test only matched names containing the literal word "video." - every other .mp4
       (e.g. my_movie.mp4) became an <audio> element and stayed silent; decide by real extension now */
    var n = ((slot.dataset.url || "").split("/").pop() || "").toLowerCase();
    var el = document.createElement(/\.(mp4|webm)$/.test(n) ? "video" : "audio");
    el.src = slot.dataset.url;
    el.controls = true;                                   // play/pause, seek, volume - built in
    el.preload = "metadata";
    slot.appendChild(el);
  }
  function renderGdiPreview(slot, t) {              // v2.4.x: .wmf / .ico / .exe -> server-side GDI+ raster (cached)
    var im = document.createElement("img");
    im.style.cssText = (t === "wmf")                                   // big metafiles fill the card
      ? "width:100%;height:auto;display:block;background:#fff;border-radius:4px"
      : "max-width:100%;display:block;margin:0 auto;background:#fff";  // icons: native size, centered - no stretch
    if (t !== "wmf") im.onload = function () {            /* v2.4.x: sub-256 icon -> render 2x */
      var w = im.naturalWidth, h = im.naturalHeight;
      if (w > 0 && Math.max(w, h) < 256) {
        im.style.width = (w * 2) + "px"; im.style.height = (h * 2) + "px"; im.style.maxWidth = "100%";
      }
    };
    im.onerror = () => { slot.textContent = "preview unavailable - download below"; };
    im.src = "/" + t + "/" + unescape(encodeURIComponent(slot.dataset.url.slice("/files/".length)));
    slot.appendChild(im);
  }
  function hint() {
    var h = document.createElement("div");
    h.className = "preview-more";
    h.textContent = "… open the file for full content";
    return h;
  }
  async function render(slot) {                           // dispatch on data-type, fail soft
    try {
      var t = slot.dataset.type;
      if (t === "pdf") await renderPdf(slot);
      else if (t === "office") await renderHtmlDoc(slot);
      else if (t === "markdown") await renderMarkdown(slot);
      else if (t === "excel") await renderExcel(slot);
      else if (t === "rtf") await renderRtf(slot);
      else if (t === "wmf" || t === "ico" || t === "exe") renderGdiPreview(slot, t);
      else if (t === "text") await renderText(slot);
      else if (t === "html") renderIframe(slot);
      else if (t === "media") renderMedia(slot);
    } catch (e) {                                         // one broken file must not kill the page
      console.warn("preview failed:", slot.dataset.url, e);
      slot.textContent = "(preview unavailable - download below)";
    }
  }
  function boot() {
    var slots = document.querySelectorAll(".preview-slot");
    for (var i = 0; i < slots.length; i++) render(slots[i]);   // every card, no hover needed
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  // v2.4.x: the live-update/search render() below replaces #board wholesale, so any
  // previews filled by boot() would be wiped - every board swap re-invokes this.
  window.tbRebootPreviews = boot;
})();
</script>
<style id="settingsStyles">
/* v2.1.4: hold the page invisible until /style.css has loaded and applied (see tb-loaded flag in
   <head>) - no more plain unstyled text + bare pictures for a moment on every full-page reload */
body { visibility: hidden; }
html.tb-loaded body { visibility: visible; }
#settingsIcon { position: fixed; top: 12px; right: 14px; z-index: 60; width: 42px; height: 42px;
  border-radius: 50%; border: none; cursor: pointer; font-size: 22px; line-height: 1;
  background: var(--panel, #fff); color: var(--ink, #333); box-shadow: 0 2px 8px rgba(0,0,0,.25); }
#settingsIcon:hover { transform: rotate(45deg); transition: transform .2s; }
/* v1.14.0: search toggle + bar - theme-aware through the same variables as #settingsIcon */
#searchIcon { position: fixed; top: 12px; right: 66px; z-index: 60; width: 42px; height: 42px;
  border-radius: 50%; border: none; cursor: pointer; font-size: 20px; line-height: 1;
  background: var(--panel, #fff); color: var(--ink, #333); box-shadow: 0 2px 8px rgba(0,0,0,.25); }
#searchIcon:hover { transform: scale(1.12); transition: transform .15s; }
#searchInput { position: fixed; top: 8px; left: 0; z-index: 61;
  width: 300px; height: 42px; line-height: 40px; box-sizing: border-box; outline: none; }
/* its padding / font / border / background come from each theme's textarea#message
   rule (shared selector), so the search bar looks exactly like the composer text box */
#settingsBox { position: fixed; top: 0; left: 0; right: 0; z-index: 50; display: flex; gap: 18px;
  align-items: center; padding: 14px 70px 14px 20px; background: var(--panel, #fff);
  color: var(--ink, #333); box-shadow: 0 4px 16px rgba(0,0,0,.3); }
#settingsBox .row { display: flex; align-items: center; gap: 8px; }
#settingsBox label { font-weight: 700; white-space: nowrap; }
#settingsBox input, #settingsBox select { padding: 6px 10px; border-radius: 8px;
  border: 1px solid var(--line, #ccc); background: var(--field, #fff); color: inherit; font-size: 14px; }
#settingsBox .hint { margin: 0; flex-basis: 100%; width: 100%; opacity: .65; font-size: 12px; }
.hidden { display: none !important; }
/* attachment affordances shared by every theme (visuals live in the stylesheets) */
button#attachBtn { flex: none; padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 16px;
  border: 1px solid var(--line, #ccc); background: var(--field, #fff); color: inherit; }
button#attachBtn:hover { transform: scale(1.12); transition: transform .15s; }
.msg-wrap { position: relative; display: block; flex: 1; min-width: 0; }
/* v1.17.x: every composer child gets one exact line height, so the text box,
   search bar and all buttons sit flush on every theme (PC + mobile). The
   auto-grow inline style still wins when the user types a new line */
textarea#message { width: 100%; box-sizing: border-box; min-height: 42px; }
button#emojiBtn, button#attachBtn, button#post { height: 42px; }
/* v1.19.x: pending attachments live INSIDE the text box - a right-anchored row of
   chips in its top-right corner, completely outside the composer flex flow (so smiley
   and paperclip buttons keep their normal single gap). Chips fill right-to-left; when
   they run out of room they wrap to a second line inside the box and fitChips() grows
   the textarea until every chip + one text line stay visible. Each clip keeps its own
   tiny ✕ (fades in on hover) that removes just that file, plus the v1.10.x pop-in +
   glow - currentColor paints each chip in the theme's vivid accent */
#pendingChips { position: absolute; top: 6px; right: 8px; z-index: 2;
  max-width: calc(100% - 16px); display: flex; flex-direction: row-reverse;
  align-items: center; gap: 6px; flex-wrap: wrap; }
.chip { position: relative; display: inline-flex;
  align-items: center; justify-content: center; width: 24px; height: 24px; cursor: default;
  color: var(--line, #9aa7b5);
  animation: chipPop .3s cubic-bezier(.34,1.56,.64,1); transition: transform .18s ease-out, filter .18s ease-out; }
.chip:hover { transform: scale(1.25) rotate(-8deg);
  filter: drop-shadow(0 0 5px currentColor) drop-shadow(0 0 12px currentColor); transition-delay: .4s; }
@keyframes chipPop { from { opacity: 0; transform: scale(.3); } to { opacity: 1; transform: none; } }
/* the ✕ sits just left of its clip and only becomes visible while hovering it or the chip */
.chip-x { position: absolute; right: 26px; top: 50%; transform: translateY(-50%);
  width: 18px; height: 18px;
  padding: 0; border: none; border-radius: 50%; background: transparent; color: inherit;
  font-size: 12px; line-height: 1; cursor: pointer; opacity: 0; transition: opacity .15s, transform .15s; }
.chip:hover .chip-x, .chip-x:hover { opacity: .9; }
.chip-x:hover { transform: translateY(-50%) scale(1.3); }
/* upload progress (v1.16.x): a semi-transparent fill painted over the text box
   while the paperclip path is sending - typed text stays readable underneath,
   label with filename + x / y MB sits on the left edge; structure here, any theme can restyle */
#uploadProg { position: absolute; inset: 0; z-index: 2; pointer-events: none; overflow: hidden; }
#uploadFill { position: absolute; top: 0; bottom: 0; left: 0; width: 0%;
  background: rgba(56,139,253,.40); transition: width .15s ease-out; }
#uploadLabel { position: absolute; top: 6px; right: 8px; z-index: 3; font-size: 12px;
  line-height: 1.4; color: #fff; background: rgba(0,0,0,.55); border-radius: 6px;
  padding: 2px 8px; max-width: calc(100% - 16px);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tilt { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
.tilt .text { white-space: pre-wrap; overflow-wrap: anywhere; }
.tilt img.preview { max-width: 100%; border-radius: 6px; }
.tilt a.download { text-decoration: none; font-size: 14px; opacity: .85; }
/* picture download icon (v1.5.3) - structure here, theme visuals in the stylesheets */
.attach-img { position: relative; display: inline-block; line-height: 0; }
.attach-img .dl { position: absolute; right: 6px; bottom: 6px; opacity: 0; transition: opacity .15s;
  text-decoration: none; font-size: 14px; line-height: 1; padding: 3px 7px; border-radius: 6px; }
.attach-img:hover .dl, .attach-img:focus-within .dl { opacity: 1; }
/* tilt rating (v1.23.0) - a small always-visible row just left of the
   delete cross; counts are shared content so they never hide on hover-out.
   Structure here, theme visuals in the stylesheets. */
.rate { position: absolute; top: 4px; right: 36px; z-index: 2; display: flex; gap: 1px; }
.rate-btn { border: none; background: transparent; cursor: pointer; font-size: 13px;
  line-height: 1; padding: 3px 4px; border-radius: 8px; opacity: .55;
  transition: opacity .15s, transform .15s; }
.rate-btn:hover { opacity: 1; transform: scale(1.2); }
.rate-btn b { font-size: 9px; font-weight: 700; margin-left: 1px; vertical-align: top; }
.rate-btn.rated { opacity: .3; pointer-events: none; }  /* this visitor already voted */
/* tilt delete (v1.5.4) - structure here, theme visuals in the stylesheets */
.tilt { position: relative; transition: transform .15s ease; }  /* v1.8.0: hover zoom */
.tilt .del { position: absolute; top: 6px; right: 8px; z-index: 2; width: 22px; height: 22px;
  border-radius: 50%; border: none; cursor: pointer; font-size: 12px; line-height: 1;
  opacity: 0; transition: opacity .15s, transform .15s; }
.tilt:hover .del, .tilt:focus-within .del { opacity: .8; }
.tilt .del:hover { opacity: 1; transform: scale(1.2); }
/* v1.9.x: pager arrows form two triplets (⏮ ◀◀ ◀ … ▶ ▶▶ ⏭) around the page
   info - one flex group per side with a full-character inner gap, and
   space-between on .pager distributes only between the three top-level items.
   Each arrow is a fixed-height box centred by line-height alone: no baseline,
   so fonts that draw media glyphs or squashed triangles slightly off-centre
   can't shift one icon up/down relative to its neighbours */
/* the icon ink now sits ~2px below its anchor-box centre (desktop squash +
   translateY tweak), so optically-centre the middle page text by moving it
   3px down - user instruction, all themes inherit this */
.pager-info { transform: translateY(3px); }
.pager-group { display: inline-flex; align-items: center; gap: 2em; }
.arrow { box-sizing: border-box; height: 42px; line-height: 40px; font-family: "Segoe UI Symbol", "Cascadia Code", "Noto Sans Symbols 2", monospace; }
/* v1.17.x: flat labels - arrow glyphs are squashed (same width, same box size,
   no per-glyph nudges) and kept on the inner span so theme hover transforms
   on the anchor stay intact. First/last-page glyphs use .g; the step arrows
   (.gs) and jump-5 triangles read a touch taller than them at desktop 34px,
   so they get one extra notch of squash (~85 percent of their current height).
   The mobile block below restores the uniform phone look. */
/* every inner glyph span gets the SAME fixed box (42px = .arrow height) so all
   four glyph kinds share one baseline and one vertical centre BEFORE squashing;
   scaleY then shrinks each around that common centre -> equal centres, no drift.
   Ink heights measured from the actually-rendering font (Segoe UI Symbol):
   U+25C0/25B6 = 126px @160px font (0.787em), U+23EE/23ED = 100px (0.625em).
   .g stays at the original uniform squash (.7) - first/last icons are NOT
   touched; .gs and jump-5 halves get .6 so their ink lands at ~85% of the
   working-state triangle height while pg-end keeps its exact old size. */
.arrow .g, .arrow .gs { display: inline-block; height: 42px; line-height: 42px;
  transform-origin: center; }
.arrow .g { transform: scaleY(.7); }
/* user tweak 2026-11-09: step + jump-5 icons sit 2px lower and at 95% of the
   previous squash (0.6 -> 0.57); first/last icons (.g) remain untouched */
.arrow .gs { transform: translateY(2px) scaleY(.57); }
/* v1.9.x: tilt cards rotate up to ~3deg around their centre, so a wide bottom row
   spills visually below the grid box - keep the bottom pager clear of it */
#board { margin-bottom: 22px; }
/* v1.9.x: pager arrows are Unicode media glyphs (⏮ U+23EE, ◀ U+25C0,
   ▶ U+25B6, ⏭ U+23ED) - no CSS bar box and no letter-spacing tricks left;
   each arrow is one self-contained symbol so it renders identically in
   every theme. The two jump-5 arrows are a tight pair of full-height,
   half-WIDTH triangles that tile to exactly one triangle's width in ANY font:
   each .half is a narrow clipping window and an inner span squashes its glyph
   with scaleX(.5) from the left edge. Spacing is user-verified (v1.9.x
   iteration): W = .45em windows with a -.1em pull give 0.35em pitch per
   triangle - tighter reads as triangles sitting on each other, looser leaves
   a visible gap, so this pitch stays as-is across all themes. */
.arrow .half { display: inline-block; width: .45em; margin-right: -.1em; overflow: hidden; }
.arrow .half > span { display: inline-block; height: 42px; line-height: 42px;
  transform: translateY(2px) scaleX(.5) scaleY(.57); transform-origin: left center; }
/* tilt hover zoom (v1.8.0) - same :hover event as the delete cross; keeps each card's rotation */
.tilt:hover, .tilt:focus-within { transform: rotate(var(--tilt)) scale(1.04); z-index: 3; }
/* emoji picker (v1.5.5) - constant black glyph color in every style (v2.1.3): monochrome
   text-presentation symbols must never inherit a theme's light/dark ink and vanish on the panel */
.composer { position: relative; }
button#emojiBtn { flex: none; padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 16px;
  border: 1px solid var(--line, #ccc); background: var(--field, #fff); color: inherit; }
button#emojiBtn:hover { transform: scale(1.12) rotate(-8deg); transition: transform .15s; }
#emojiPicker { position: absolute; left: 0; top: calc(100% + 8px); z-index: 40; width: min(92vw, 360px);
  max-height: 280px; overflow-y: auto; padding: 10px; border-radius: 12px;
  background: var(--panel, #fff); color: #000; border: 1px solid var(--line, #ccc);
  box-shadow: 0 8px 24px rgba(0,0,0,.3); display: grid; gap: 2px;
  grid-template-columns: repeat(auto-fill, minmax(36px, 1fr)); }
#emojiPicker button { font-size: 20px; line-height: 1; padding: 5px 2px; border: none; background: transparent;
  color: #000; cursor: pointer; border-radius: 8px; }
#emojiPicker button:hover { transform: scale(1.3); background: rgba(127,127,127,.15); transition: transform .1s; }
@keyframes emojiPopIn { from { opacity: 0; transform: translateY(-6px) scale(.94); } to { opacity: 1; transform: none; } }
#emojiPicker:not(.hidden) { animation: emojiPopIn .18s ease-out; }
/* optional flourish: a posted tilt carrying an emoji wiggles once */
@keyframes tiltWiggle {
  25% { transform: rotate(calc(var(--tilt, 0deg) + 4deg)) scale(1.06); }
  60% { transform: rotate(calc(var(--tilt, 0deg) - 3deg)); }
}
.tilt.has-emoji { animation: tiltWiggle .5s ease-in-out; }
#confirmOverlay { position: fixed; inset: 0; z-index: 70; display: flex;
  align-items: center; justify-content: center; background: rgba(0, 0, 0, .45); }
#confirmOverlay.hidden { display: none !important; }
.dialog { max-width: min(92vw, 380px); padding: 18px 22px; border-radius: 12px;
  background: var(--panel, #fff); color: var(--ink, #333);
  box-shadow: 0 10px 40px rgba(0, 0, 0, .4); font-size: 15px; }
.dialog p { margin: 0 0 16px; overflow-wrap: anywhere; }
.dialog .btns { display: flex; gap: 10px; justify-content: flex-end; }
.dialog button { padding: 7px 18px; border-radius: 8px; cursor: pointer;
  font-size: 14px; font-weight: 600; border: 1px solid var(--line, #999);
  background: var(--field, #fff); color: inherit; }
#loginOverlay { position: fixed; inset: 0; z-index: 70; display: flex;
  align-items: center; justify-content: center; background: rgba(0, 0, 0, .45); }
#loginOverlay.hidden { display: none !important; }
#loginPass { width: 100%; box-sizing: border-box; padding: 8px 12px; margin-bottom: 6px;
  border-radius: 8px; border: 1px solid var(--line, #999); background: var(--field, #fff);
  color: inherit; font-size: 14px; }
#loginGo { width: 100%; margin-top: 6px; }
#delNo:hover { opacity: .75; }
/* v2.1.x: screen-reader-only helper (login form's hidden username field) */
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
/* v1.17.0: the jump-5 arrows are two inline spans - without nowrap a narrow box
   wraps them onto two lines (the "falling apart" seen on phones). Desktop never
   wrapped because it fits, so this changes nothing visually there */
.arrow { white-space: nowrap; }
/* v1.17.0 mobile layout (~<=700px): the fixed top icons and the one-row settings
   box were built for wide screens - on a phone they crowd the page and the four
   controls overflow, so the user can't reach/save them all. Everything below is
   media-scoped; desktop rules above are untouched.
   1) both round buttons shrink from 42px to 30px (glyphs scale with the font)
      and move in toward the edges;
   2) #settingsBox stacks its rows vertically so Name / Style / Rows / Columns
      each get a full line - all four reachable at ~360px width. The right padding
      no longer reserves room for two fixed icons sitting inside it.
   3) pager: the user-verified icon shapes stay, only sizes drop one step
      (font 34 -> 22px, box 42 -> 28px). .arrow's inline height/line-height pair
      is kept in lockstep so glyphs stay centred exactly as on desktop. The
      2em inner gaps between triplets halve to 1em so all six icons plus the
      page info fit one line at 375px; the whole bar also gets a little smaller */
@media (max-width: 700px) {
  #settingsIcon, #searchIcon { top: 8px; width: 30px; height: 30px; font-size: 16px; }
  #settingsIcon { right: 10px; }
  #searchIcon { right: 46px; }
  #settingsBox { flex-direction: column; align-items: stretch; gap: 10px;
    padding: 12px 14px; }
  #settingsBox .row { justify-content: space-between; width: 100%; }
  #settingsBox input, #settingsBox select {
    flex: 1; min-width: 0; box-sizing: border-box; text-align: center; }
  /* the search bar's right edge must clear both shrunken round buttons;
     left+right instead of a vw-based width - immune to scrollbar quirks.
     max-width guards against intrinsic input sizing on narrow engines */
  #searchInput { width: auto; max-width: calc(100vw - 94px); right: 84px; top: 6px; }
  /* only Post gets half its desktop size - emoji/paperclip stay as-is, so the
     composer row frees exactly one button's worth of room for text */
  button#post { padding: 10px 12px; font-size: 14px; }
  .pager { padding: 2px 4px; }
  .arrow { font-size: 22px; height: 28px; line-height: 26px; }
  /* phones already looked uniform with every glyph at the base squash -
     undo the desktop-only extra flattening for step and jump-5 arrows;
     same shared fixed box as desktop (scaled to phone .arrow height) so
     alignment stays identical to what was approved on mobiles */
  .arrow .g, .arrow .gs { height: 28px; line-height: 28px; }
  .arrow .half > span { height: 28px; line-height: 28px; }
  .arrow .gs { transform: scaleY(.7); }
  .arrow .half > span { transform: scaleX(.5) scaleY(.7); transform-origin: left center; }
  .pager-group { gap: 1em; }
  /* phone icons were never shifted - keep the text exactly centred there */
  .pager-info { font-size: 10px; transform: none; }
}
/* v1.21.0: auto-linked URLs inside tilt text - clickable, opens a new tab.
   One rule here (always loaded) serves every theme; the colour resolves from
   each theme's own --tb-accent via var(). */
.text a.lnk { color: var(--tb-accent, #4a73b5); text-decoration: underline;
  overflow-wrap: anywhere; }
.text a.lnk:hover { filter: brightness(1.12); }
/* v2.4.x: in-card previews - theme-independent sizing so every style gets the same edge gap
   and clamps (per-theme sheets only restyle colours, never layout). Padding on the slot keeps
   PDF canvas / docx HTML away from card edges; overflow:hidden is the right+bottom clip for
   text lines that exceed a card. */
.preview-slot { display: block; width: 100%; box-sizing: border-box;
  padding: 8px 10px; margin: 4px 0; overflow: hidden; }
/* plain-text previews (log/csv/ini/...): small mono, hard-capped - long lines clip at the card
   edge, the bottom stops after ~230 px of preview instead of stretching the tilt */
.preview-slot pre { font-size: 12px; line-height: 1.45;
  white-space: pre; overflow: hidden; max-height: 230px; }
/* markdown / docx previews share one slightly smaller font and a bottom cap - right side is
   clipped by the slot's own overflow rule above */
.preview-slot[data-type="markdown"], .preview-slot[data-type="office"] { font-size: 13px;
  max-height: 420px; }
/* xlsx preview: SheetJS renders a real <table> - compact grid, clipped on both sides like text */
.preview-slot[data-type="excel"] { max-height: 420px; overflow: hidden; }
.preview-slot table { border-collapse: collapse; width: 100%; font-size: 12px; }
.preview-slot th, .preview-slot td { border: 1px solid rgba(128,128,128,.35); padding: 2px 6px;
  text-align: left; }
/* pdf.js paints into a fixed-size canvas - centre it inside its padded slot so the visible gap
   stays equal on both sides even when fit-to-width leaves slack */
.preview-slot[data-type="pdf"] canvas { display: block; margin: 0 auto;
  border-radius: 4px; }
/* html files and media players fill the card width (gap from slot padding), capped vertically */
.preview-slot iframe { width: 100%; height: 380px; border: none; display: block; }
.preview-slot video, .preview-slot audio { width: 100%; max-height: 320px;
  background: #000; border-radius: 4px; }
/* v2.4.x: icon-type previews (.ico/.exe) centre the raster on both axes in the remaining
   card space, and their download link leaves flow for a fixed bottom-centre spot */
.preview-slot[data-type="ico"], .preview-slot[data-type="exe"] { display: flex;
  align-items: center; justify-content: center; min-height: 120px; }
.tilt[data-icard] a.download { position: absolute; bottom: 4px; left: 50%;
  transform: translateX(-50%); white-space: nowrap; z-index: 1; }
/* the "more content below" hint added by capBlocks */
.preview-more { font-size: 11px; opacity: .6; text-align: center; margin-top: 4px; }
</style>
<script>/* v2.1.x: last-resort pass - whatever ran earlier (IIFEs, poller, cache),
   the locked page must end up with only the login dialog + settings gear visible.
   Runs after every other script on the page, so no later code can un-hide these. */
if (window.TB_AUTH_MODE) {
  document.querySelectorAll(".composer, .pager, #searchIcon, #searchInput, .arrow")
    .forEach(function (el) { el.style.display = "none"; });
  var lo2 = document.getElementById("loginOverlay");
  if (lo2 && !window.__TB_UNLOCKED__) lo2.classList.remove("hidden");
}
</script>
</body>
</html>
"""



def grid_from_query(query: str) -> tuple[int, int]:
    """v1.7.0: ?rows=&cols= override the config board for this request only;
    each value is bounded (0<rows<=MAX_ROWS, 0<cols<=MAX_COLUMNS), and an
    invalid or missing one falls back to the configured default."""
    q = parse_qs(query)

    def one(key: str, default: int, bound: int) -> int:
        try:
            v = int(q.get(key, [None])[0])
        except (TypeError, ValueError):
            return default
        return v if 0 < v <= bound else default

    return one("rows", ROWS, MAX_ROWS), one("cols", COLUMNS, MAX_COLUMNS)


NAME_RE = re.compile(r"^([^:/\\`\n]{1,24})(?::(?: |$))")


def _post_name(post: dict):
    """Poster prefix of a raw chat.txt line - the same rule as the badge in render()."""
    m = NAME_RE.match(post["text"])
    return (m.group(1), post["text"][len(m.group(0)):]) if m else (None, post["text"])


def search_posts(query: str) -> list:
    """v1.14.0 live filter over chat.txt content.

    Space-separated tokens are AND-ed; every token is a case-insensitive substring
    match with an optional prefix - n:/u:<text> searches the poster name, f:<text>
    the attached file's name and c:<text> only the message body (name stripped).
    A bare token searches the whole line. Newest first, like /posts.
    """
    toks = []
    for t in query.split():
        if t[:2] in ("n:", "u:") and len(t) > 2:   # an empty value matches nothing
            toks.append((t[2], t[2:].lower()))
        elif t[:2] == "f:" and len(t) > 2:
            toks.append(("f", t[2:].lower()))
        elif t[:2] == "c:" and len(t) > 2:         # body only, name prefix excluded
            toks.append(("c", t[2:].lower()))
        else:
            toks.append((None, t.lower()))
    out = []
    for p in reversed(POSTS):  # newest first
        name, body = _post_name(p)
        fname = (p.get("attach") or {}).get("name", "").lower()
        ok = True
        for kind, needle in toks:
            if kind is None:      ok = needle in p["text"].lower()
            elif kind == "f":     ok = needle in fname
            elif kind == "c":     ok = needle in body.lower()  # c: ignores the name prefix
            else:                 ok = bool(name) and needle in name.lower()  # n:/u:
            if not ok:
                break
        if ok:
            out.append(p)
    return out


def total_pages(size: int | None = None) -> int:
    """How many pages of `size` tilts chat.txt currently holds (>=1). The
    config rows x columns grid applies when no visitor override is given."""
    n = size or PAGE_SIZE
    return max(1, -(-len(POSTS) // n))  # ceil division


def posts_for_page(page: int, size: int | None = None) -> list[dict]:
    """Newest-first slice for `page` (1 = newest chunk), clamped to range."""
    n = size or PAGE_SIZE
    page = min(max(int(page), 1), total_pages(n))
    end = len(POSTS) - (page - 1) * n  # oldest-first boundary, exclusive
    start = max(end - n, 0)
    return list(reversed(POSTS[start:end]))


def _nav_arrow(href, label, active, cls=""):
    """One pager control (v1.9.0): an <a> when usable, a greyed-out span otherwise."""
    c = "arrow" + ((" " + cls) if cls else "")
    if active:
        return f'<a class="{c}" href="{href}">{label}</a>'
    return f'<span class="{c} disabled">{label}</span>'


def render_pager(current: int, total: int) -> str:
    """Top/bottom navigation row (v1.9.0). Standard order around the page info:
    |<  <<  <   Page X of Y   >  >>  >|
    |< goes to page 1, << jumps five pages back (active only while a whole
    jump fits), < steps one page back; right side mirrors it. Controls that
    cannot apply in place render as disabled spans.

    v1.9.x: the two jump-5 arrows are a tight pair of full-height, half-width
    triangles (two U+25C0 / two U+25B6), not the single media glyphs
    U+23EA/U+23E9 - those don't match the triangle style. Each glyph sits in an
    inner span squashed with scaleX(.5) inside a narrow `.half` clipping window,
    so the pair tiles to one triangle's width in any font (see `.arrow .half`).
    """
    left = (
        '<span class="pager-group">'
        + _nav_arrow("/?page=1", '<span class="g">&#9198;</span>', current > 1, "pg-end")
        + _nav_arrow(f"/?page={current - 5}", '<span class="half"><span>&#9664;</span></span><span class="half"><span>&#9664;</span></span>', current > 5)
        + _nav_arrow(f"/?page={current - 1}", '<span class="gs">&#9664;</span>', current > 1) + '</span>')
    right = (
        '<span class="pager-group">'
        + _nav_arrow(f"/?page={current + 1}", '<span class="gs">&#9654;</span>', current < total)
        + _nav_arrow(f"/?page={current + 5}", '<span class="half"><span>&#9654;</span></span><span class="half"><span>&#9654;</span></span>', current + 5 <= total)
        + _nav_arrow(f"/?page={total}", '<span class="g">&#9197;</span>', current < total, "pg-end") + '</span>')
    return f'<div class="pager">{left}<span class="pager-info">Page {current} of {total}</span>{right}</div>'


# v1.6.0: the "name:" prefix on a chat.txt line becomes a badge; the colon itself
# is not rendered. A name = up to 24 chars, no whitespace / ':' / '/' / '\\' / backtick,
# followed by ": " or end of line (so URLs like http://... stay untouched).
NAME_RE = re.compile(r"^([^:/\\\n`]{1,24}):(?: |$)")

# v1.21.0: bare URLs in post text become clickable links that open a new tab.
# Only explicit schemes match, so attachment hrefs (file:/relative paths) can never be hit.
URL_PREFIXES = ("http://", "https://", "ftp://")


def _fmt_loop(raw: str, start: int, out: list, depth: int = 0,
              stop: int | None = None) -> None:
    """Escape-interpret raw[start:] and append HTML to `out` (no name badge).
    v1.19.1: ~~ spans behave like a formatting word - escapes work inside them,
    and an escape run with no word right before a paired ~~ wraps the whole span.
    Spans nest at most one level deep; any further ~~ pair stays literal, same
    spirit as code spans.

    v1.19.1 fix: `stop` bounds the walk - a span's content is interpreted only up to its
    own closing pair (previously the recursive call ran past it and rendered the closer
    as an unmatched literal ~~)."""
    i = start
    n = len(raw) if stop is None else min(stop, len(raw))
    while i < n:
        ch = raw[i]
        if ch == "\\" and i + 1 < n and raw[i + 1] in "nubi":
            esc = raw[i + 1]
            if esc == "n":
                out.append("<br>")
                i += 2
                continue
            fmts = [esc]
            j = i + 2
            while j < n and raw[j] == "\\" and j + 1 < n \
                    and raw[j + 1] in "bui":
                if raw[j + 1] not in fmts:  # duplicates ignored, e.g. \u005cb\u005cbtext
                    fmts.append(raw[j + 1])
                j += 2
            k = j
            # v1.7.1: a token ends where a recognized escape starts, so chained escapes
            # (e.g. \uwork\n\bsee) each fire instead of being swallowed into one word.
            # v1.19.0: a token also ends at any tilde, so ~~spans~~ never swallow
            # formatted words (and vice versa) - same boundary as code spans.
            while k < n and not raw[k].isspace() \
                    and raw[k] != "~" \
                    and not (raw[k] == "\\" and k + 1 < n and raw[k + 1] in "nubi"):
                k += 1
            if k > j:  # a word really follows the escape(s)
                out.append("".join(f"<{t}>" for t in fmts))
                out.append(html.escape(raw[j:k]))
                out.append("".join(f"</{t}>" for t in reversed(fmts)))
                i = k
            elif raw[j:j + 2] == "~~":   # v1.19.1: no word, but a ~~span~~ follows - the
                end = raw.find("~~", j + 2)  # stacked escapes wrap its whole content
                if end != -1 and depth < 2:
                    out.append("".join(f"<{t}>" for t in fmts))
                    out.append("<s>")
                    _fmt_loop(raw, j + 2, out, depth + 1, end)   # v1.19.1: bounded by the closing pair
                    out.append("</s>")
                    out.append("".join(f"</{t}>" for t in reversed(fmts)))
                    i = end + 2
                else:      # no closing pair (or nested too deep) - literal escapes
                    out.append(html.escape(raw[i:j]))
                    i = j
            else:      # no word and no span after - keep the sequence literal, escaped
                out.append(html.escape(raw[i:j]))
                i = j
        elif ch == "`":
            end = raw.find("`", i + 1)
            if end != -1:
                # v1.5.9: \n still breaks lines inside code spans, all else literal.
                # escape first (entities contain no backslash) so the replace is safe.
                inner = html.escape(raw[i + 1:end]).replace("\\n", "<br>")
                out.append(f"<code>{inner}</code>")
                i = end + 1
            else:          # unmatched backtick stays literal
                out.append(html.escape(ch))
                i += 1
        elif ch == "~" and raw[i:i + 2] == "~~":   # v1.19.0: ~~text~~ strikethrough span
            end = raw.find("~~", i + 2)
            if depth < 2 and end != -1:
                # v1.19.1: escapes work inside the span too (\b/\u/\i per word, \n line breaks);
                # any further ~~ pair inside stays literal.
                out.append("<s>")
                _fmt_loop(raw, i + 2, out, depth + 1, end)   # v1.19.1: bounded by the closing pair
                out.append("</s>")
                i = end + 2
            else:          # unmatched ~~ (or a nested pair) keeps both tildes literal
                out.append(html.escape(raw[i:i + 2]))
                i += 2
        elif ch == "\n":   # real newline kept as a safety no-op since v1.5.6
            out.append("<br>")
            i += 1
        elif any(raw.startswith(p, i) for p in URL_PREFIXES):   # v1.21.0: auto-link URLs -> new tab
            # v1.21.1: the href ends at a space, a backslash (so an escape like \n right
            # after it is honoured as its own sequence), or end-of-line - whichever comes first.
            end = raw.find(" ", i)
            bs = raw.find("\\", i)
            if bs != -1 and (end == -1 or bs < end):
                end = bs
            if end == -1:
                end = n
            url = raw[i:end]
            out.append(f'<a class="lnk" href="{html.escape(url, quote=True)}" '
                       f'target="_blank" rel="noopener noreferrer">{html.escape(url)}</a>')
            i = end
        else:
            out.append(html.escape(ch))
            i += 1


def format_text(raw: str) -> str:
    """Safe HTML for one tilt's stored text. The escape set is documented in
    readme.md - every character not consumed by an escape or a span is
    html.escape()d, so user input can never inject markup:
      \\n        new line          `code`  inline code span, literal inside
      ~~text~~   strikethrough span - escapes work inside it (per word) and stacked
                 prefixes before it wrap the whole content; an unmatched ~~ keeps both tildes as-is
      \\bword    bold the next non-space token (\\u/\\i likewise)
      stacked    prefixes apply together in written order - \\b\\itext becomes <b><i>text</i></b>
                 with closing tags unwound in reverse; duplicate letters are ignored. An escape
                 run without a word after it stays literal, unless a ~~span~~ follows (v1.5.8/v1.19.1).
      A formatted token ends where any recognized escape starts or at the first tilde,
                 so \\uwork\\n\\bsee underlines work only, breaks the line, then bolds see -
                 chained escapes never get swallowed into the previous word (v1.7.1).
      name:     leading "name:" prefix renders as a badge; the colon disappears
                 (the app adds this prefix itself - see README)
      http(s):// / ftp(s)://  URLs written as their own word are auto-linked and open in
                 a new tab; the link ends at a space, a backslash or end-of-line - so an escape
                 glued right after (http://my_domain\n...) is honoured. Inside `code` spans they
                 stay literal, and an escape glued to one (\bhttp://...) bolds it as plain text -
                 keep a space before the URL (v1.21.0/v1.21.1).
    """
    out = []
    m = NAME_RE.match(raw)          # v1.6.0: name badge, colon hidden
    if m:
        out.append(f'<span class="user">{html.escape(m.group(1))}</span>')
        i = m.end()                 # past name + ':' and one space (or end of string)
    else:
        i = 0
    _fmt_loop(raw, i, out)          # v1.19.1: shared loop - also used inside ~~ spans
    return "".join(out)


def render_posts(page: int = 1) -> str:
    """Render one page of tilt cards as HTML, newest first."""
    if not POSTS:
        return '<p class="empty">Nothing posted yet - your tilted shapes will appear here.</p>'
    cards = []
    for post in posts_for_page(page):
        text = format_text(post["text"])  # v1.5.7: escape set, see readme.md
        tilt = f'{post["tilt"]}deg'
        attach = post.get("attach")
        emoji_cls = " has-emoji" if any(ord(ch) > 0xFFFF for ch in post["text"]) else ""
        extra = ""
        # v1.5.4: hover a tilt -> small cross in its upper-right corner
        delete_btn = '<button class="del" title="Delete this tilt">&#10005;</button>'
        if attach:
            if attach["is_image"]:
                # v1.5.3: hover a picture -> download icon in its right-bottom corner
                extra = (f'<span class="attach-img"><img class="preview" '
                         f'src="{html.escape(attach["url"])}" alt="{html.escape(attach["name"])}">'
                         f'<a class="dl" href="{html.escape(attach["url"])}" '
                         f'download="{html.escape(attach["name"], quote=True)}" '
                         f'title="Download">&#11015;</a></span>')
            elif attach.get("preview"):
                # v2.3.0: in-card preview slot (renderer below) + download link always kept
                ptype = html.escape(attach["preview"])
                extra = (f'<span class="preview-slot" data-type="{ptype}" '
                         f'data-url="{html.escape(attach["url"])}"></span>'
                         f'<a class="download" href="{html.escape(attach["url"])}">'
                         f'\U0001F4C4 {html.escape(attach["name"])}</a>')
            else:
                extra = (f'<a class="download" href="{html.escape(attach["url"])}">'
                         f'\U0001F4C4 {html.escape(attach["name"])}</a>')
        # v1.23.0: rating row, always visible (counts are shared content),
        # positioned just left of the delete cross - structure here, theme
        # visuals in the stylesheets; zero counts render no badge at all.
        counts = post.get("rating") or [0, 0, 0, 0]
        rate_icons = (("up", "\U0001F44D", "Rate up"), ("down", "\U0001F44E", "Rate down"),
                      ("heart", "\u2764\uFE0F", "Love it"), ("smile", "\U0001F600", "Funny"))
        rate_btns = " ".join(
            f'<button class="rate-btn" data-icon="{name}" title="{title}">{glyph}'
            + (f"<b>{c}</b>" if c else "") + "</button>"
            for (name, glyph, title), c in zip(rate_icons, counts))
        rate_row = f'<span class="rate">{rate_btns}</span>'
        # the button's identity rides on data-* so one click handler can serve
        # every card - quote=True keeps quotes/newlines inside the attribute
        attach_name = html.escape(attach["name"], quote=True) if attach else ""
        icard = ' data-icard' if (attach and attach.get("preview") in ("ico", "exe")) else ""  # v2.4.x
        cards.append(f'<div class="tilt{emoji_cls}{icard}" data-c="{post["color"]}" style="--tilt: {tilt} "'
                     f'data-text="{html.escape(post["text"], quote=True)}"'
                     f'data-attach="{attach_name}"'
                     f'data-id="{html.escape(str(post.get("id", "")), quote=True)}">{rate_row}{delete_btn}'
                     f'<span class="text">{text}</span>{extra}</div>')
    return "\n".join(cards)


def _header_html() -> str:
    """Optional page-top frame (v1.15.0). `header.<style>.html` wins when present,
    otherwise plain `header.html`. Read fresh on every request, so editing the
    file shows up on a normal browser refresh — no server restart needed.
    No header file = an empty string and the board renders exactly as before."""
    for name in (f"header.{STYLE_NAME}.html", "header.html"):
        path = os.path.join(BASE_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError as exc:  # unreadable/corrupt header must never kill the board
            log.warning("could not read %s: %s", path, exc)
    return ""


def _visitor_from_cookie(cookie_header: str) -> tuple[str | None, str | None, str | None, str | None]:
    """v1.27.0: decode the 'tiltboard' cookie written by the settings box - an encoded
    query string (name=..&style=..&cols=..&rows=..) carrying only values that differ from
    defaults. Missing or unreadable parts stay None, so a log line shows exactly what this
    browser remembers."""
    out = {"name": None, "style": None, "cols": None, "rows": None}
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == "tiltboard" and value:
            fields = parse_qs(unquote(value))  # one unquote: JS encodes the query string once
            for field in out:
                if field in fields:
                    out[field] = fields[field][0]
    return out["name"], out["style"], out["cols"], out["rows"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes = b"", headers=None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_stream(self, status: int, fileobj, length: int, headers=None) -> None:
        """v2.0.0 sync: stream an open binary handle without buffering it in RAM - /files/
        uses this for full downloads and 206 partials so a multi-GB attachment is never
        materialized as one bytes object (a plain _send would read the whole file first)."""
        self.send_response(status)
        self.send_header("Content-Length", str(length))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        sent = 0
        try:
            while sent < length:  # bounded writes - the loop exits on short read / EOF too
                chunk = fileobj.read(min(STREAM_BUF, length - sent))
                if not chunk:
                    break
                self.wfile.write(chunk)
                sent += len(chunk)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            # client aborted mid-stream (tab closed, refresh during download): WinError 10054
            # surfaces as ConnectionResetError, 10053 as ConnectionAbortedError - neither a fault.
            log.info("client %s dropped stream at byte %d/%d - ignored",
                     self.client_address[0], sent, length)

    def _css_for(self, name_param: str | None) -> tuple[bytes, bool]:  # (css_bytes, ok)
        """Resolve a /style.css request: an explicit ?name= overrides the config
        default. Unknown names fall back to the configured theme."""
        if name_param and os.path.isfile(os.path.join(STYLES_DIR, f"{name_param}.css")):
            with open(os.path.join(STYLES_DIR, f"{name_param}.css"), encoding="utf-8") as f:
                return f.read().encode("utf-8"), True
        return STYLE_CSS.encode("utf-8"), not name_param

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        self._quiet_401 = False  # v2.1.5: per-request flag, set by the auth gate and read/cleared by log_message
        # v2.0.0 sync handshake - the single endpoint a peer server calls for a full diff.
        if path == "/sync/state":
            self._handle_sync_state()
            return
        if AUTH_ENABLED and path.startswith(("/search", "/posts", "/files/")):
            # v2.1.0: data routes need a valid role; the shell page stays open so its baked-in
            # flag can render the login dialog before anything is served to unauthenticated users
            if _auth_role(self.headers.get("Cookie") or "") is None:
                # v2.1.5: a stale tab with an invalidated cookie polls /posts every 3 seconds (once per
                # minute when the browser throttles it in the background) - that expected 401 gets demoted
                # to debug-only by log_message via this flag; other routes' 401s stay at WARNING level
                self._quiet_401 = path == "/posts"
                self._send(401, json.dumps({"ok": False, "error": "login required"}).encode("utf-8"),
                           {"Content-Type": "application/json", "Cache-Control": "no-store"})
                return
        if path in ("/", "/index.html"):
            role_now = _auth_role(self.headers.get("Cookie") or "")  # 'full' on open boards, else 'full'/'ro'/None
            # v2.1.x: no valid cookie -> same shell page with the card area baked empty; the
            # script at <body> start then reveals the themed login overlay (composer, search and
            # pagers stay hidden until /login succeeds and location.replace('/') re-enters here).
            locked = AUTH_ENABLED and role_now is None
            # v1.27.0: who's here - client address plus whatever this browser has stored
            host, port_no = self.client_address[0], self.client_address[1]
            n_v, s_v, c_v, r_v = _visitor_from_cookie(self.headers.get("Cookie") or "")
            if n_v or s_v or c_v or r_v:
                log.info("page opened by %s:%d - name=%s style=%s cols=%s rows=%s",
                         host, port_no, n_v, s_v, c_v, r_v)
            else:
                log.info("page opened by %s:%d (first visit or cleared cookies - defaults apply from config.json)",
                         host, port_no)
            query_page = parse_qs(parsed.query).get("page", ["1"])[0]
            try:  # ?page=N picks the page to show; garbage falls back to page 1
                requested = min(max(int(query_page), 1), total_pages())
            except ValueError:
                requested = 1
            pager = "" if locked else render_pager(requested, total_pages())
            page = PAGE.replace("__POSTS__", "" if locked else render_posts(requested))
            page = (page.replace("__ARROWS_TOP__", pager).replace("__ARROWS_BOTTOM__", pager))
            page = (page.replace("__HEADER__", _header_html())           # optional top frame
                    .replace("__DEFAULT_STYLE__", STYLE_NAME)      # dropdown default
                    .replace("__DEFAULT_ROWS__", str(ROWS))
                    .replace("__DEFAULT_COLUMNS__", str(COLUMNS))
                    .replace("__SLOW_UPLOAD__", str(SLOW_UPLOAD)))       # v1.22.0: slow-network upload switch
            # role_now was computed at the top of this branch; locked visitors see only the overlay.
            page = page.replace("__AUTH_MODE__", "true" if locked else "false")
            page = page.replace("__RO_ROLE__", str(role_now == "ro").lower())  # v2.1.0: hide composer + delete crosses
            page = page.replace("__AUTH_ENABLED__", "true" if AUTH_ENABLED else "false")  # v2.1.x: Login button visibility
            body = page.encode("utf-8")
            # v1.18.1: no-store - the grid (rows/cols) and all settings logic live in this
            # document's inline JS, so a heuristically cached copy would silently ignore the
            # visitor's cookie preferences while server-side things (style) kept working.
            self._send(200, body, {"Content-Type": "text/html; charset=utf-8",
                                   "Cache-Control": "no-store"})
        elif path == "/style.css":
            name_param = parse_qs(parsed.query).get("name", [None])[0]  # per-visitor theme
            body, ok = self._css_for(name_param)
            if not ok:  # unknown theme requested explicitly -> plain 404
                self._send(404, b"")
                return
            self._send(200, body, {"Content-Type": "text/css", "Cache-Control": "no-store"})
        elif path == "/favicon.ico":  # v1.27.0: tab icon - also ends the default 404 warning storm
            try:
                with open(FAVICON_PATH, "rb") as f:
                    self._send(200, f.read(), {"Content-Type": "image/x-icon",
                                               "Cache-Control": "public, max-age=86400"})
            except OSError:  # icon missing on this install -> plain 404 as before
                self._send(404, b"Not found")
        elif path == "/styles":  # theme list for the settings dropdown
            self._send(200, STYLES_JSON, {"Content-Type": "application/json"})
        elif path == "/search":  # v1.14.0: live filter of chat.txt (n:/u: name, f: file, c: body)
            q = parse_qs(parsed.query).get("q", [""])[0].strip()
            self._send(200, json.dumps({"posts": search_posts(q)}).encode("utf-8"),
                       {"Content-Type": "application/json", "Cache-Control": "no-store"})
        elif path == "/posts":  # JSON snapshot for the client-side poller
            query_page = parse_qs(parsed.query).get("page", ["1"])[0]
            rows, cols = grid_from_query(parsed.query)  # v1.7.0: per-visitor page size
            size = rows * cols
            try:
                requested = min(max(int(query_page), 1), total_pages(size))
            except ValueError:
                requested = 1
            newest_first = posts_for_page(requested, size)  # attach included when present
            # v1.7.0: the poller needs len(POSTS) to count its own pages -
            # one page of JSON alone cannot say "page 2 exists".
            body = json.dumps({"total": len(POSTS), "posts": newest_first}).encode("utf-8")
            self._send(200, body, {"Content-Type": "application/json", "Cache-Control": "no-store"})
        elif path.startswith("/libs/"):   # v2.3.0: preview libraries (pdf.js / mammoth / marked) from <app-folder>/libs/
            name = unquote(path[len("/libs/"):])
            root = os.path.realpath(os.path.join(BASE_DIR, "libs"))
            real = os.path.realpath(os.path.join(root, name))  # traversal guard (same rule as /logo/, /files/)
            try:
                contained = os.path.commonpath([real, root]) == root
            except ValueError:      # cross-drive / UNC-vs-local mismatch -> outside folder
                contained = False
            if not contained or not os.path.isfile(real):
                self._send(404, b"Not found")
                return
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with open(real, "rb") as f:
                body = f.read()
            # version-pinned files: cache them for a year, re-validated only on app update
            self._send(200, body, {"Content-Type": ctype,
                                   "Cache-Control": "public, max-age=31536000"})
        elif path.startswith(("/wmf/", "/ico/", "/exe/")):  # v2.4.x: GDI+ raster previews (.wmf/.ico/.exe)
            self._gdi_preview(path)
        elif path.startswith("/logo/"):  # v1.16.1: static assets for header.html from <app-folder>/logo/
            name = unquote(path[len("/logo/"):])
            root = os.path.realpath(os.path.join(BASE_DIR, "logo"))
            real = os.path.realpath(os.path.join(root, name))  # traversal guard (same rule as /files/):
            try:
                contained = os.path.commonpath([real, root]) == root
            except ValueError:      # cross-drive / UNC-vs-local mismatch -> outside folder
                contained = False
            if not contained or not os.path.isfile(real):
                self._send(404, b"Not found")
                return
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            with open(real, "rb") as f:
                body = f.read()
            self._send(200, body, {"Content-Type": ctype})  # inline: <img> in the header renders it
        elif path.startswith("/files/"):
            name = unquote(path[len("/files/"):])
            real = os.path.realpath(os.path.join(DATA_FOLDER, name))  # traversal guard:
            root = os.path.realpath(DATA_FOLDER)
            try:
                contained = os.path.commonpath([real, root]) == root
            except ValueError:      # cross-drive / UNC-vs-local mismatch -> outside folder
                contained = False
            if not contained or not os.path.isfile(real):
                self._send(404, b"Not found")
                return
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            size = os.path.getsize(real)
            # v2.0.0: a Range request means the caller already holds the first N bytes and wants
            # only the rest - that is the resume primitive the sync worker uses for interrupted
            # downloads (and it lets any HTTP client resume an attachment after a network loss).
            start = 0
            rmatch = re.match(r"bytes=(\d+)-(\d*)$", self.headers.get("Range", "") or "")
            if rmatch and rmatch.group(1).isdigit():
                start = max(int(rmatch.group(1)), 0)
                end_inclusive = int(rmatch.group(2)) if rmatch.group(2) else size - 1
                end_inclusive = min(end_inclusive, size - 1)
            else:
                end_inclusive = size
            ranged = bool(rmatch)
            remaining = (end_inclusive - start + 1) if ranged else size  # bytes this request wants
            with open(real, "rb") as f:
                if ranged and start > 0:  # skip the bytes we already have on the other side
                    f.seek(start)
                # v2.4.x: a raw Czech/Chinese filename used to crash send_header here - latin-1
                # cannot encode ř/ě/č and the whole response died with zero bytes (browser saw
                # "Failed to fetch"). UTF-8 -> latin-1 smuggling is what every Windows browser expects.
                quoted = name.replace("\\", "\\\\").replace('"', '\\"').encode("utf-8").decode("latin-1")
                # v2.4.x: html files must go out WITHOUT the attachment header - a browser that
                # navigates an inline frame to such a URL paints nothing (the card showed only its
                # background color). Saving still works: the card's <a download="..."> forces it.
                dispo = {} if name.lower().endswith((".html", ".htm")) else {"Content-Disposition": f'attachment; filename="{quoted}"'}
                if ranged:  # 206 partial content - the peer appends to its .part and resumes from start
                    self._send_stream(206, f, remaining, {"Content-Type": ctype, **dispo,
                                                          "Content-Range": f"bytes {start}-{end_inclusive}/{size}",
                                                          "Accept-Ranges": "bytes"})
                else:  # full file - streamed too, never buffered whole in RAM
                    self._send_stream(200, f, remaining, {"Content-Type": ctype, **dispo,
                                                           "Accept-Ranges": "bytes"})
        else:
            self._send(404, b"Not found")

    def _gdi_preview(self, path: str) -> None:
        """v2.4.x: serve /wmf/, /ico/ and /exe/ as cached PNG previews (native size).

        Rasterize first when the cache is missing or stale (an early 404 on a cold cache would
        make conversion unreachable), then verify what actually exists before serving.
        Every failure is logged with full evidence - a 404 here is exactly what turns a card
        into 'preview unavailable', so the log must name the reason."""
        ext = path.split("/")[1]
        name = unquote(path[len(ext) + 2:])
        real = os.path.realpath(os.path.join(DATA_FOLDER, name))
        root = os.path.realpath(DATA_FOLDER)
        try:
            contained = os.path.commonpath([real, root]) == root
        except ValueError:
            contained = False
        if not contained or not real.lower().endswith("." + ext):
            log.warning("%s preview 404 for %r - not in data/ or extension mismatch", ext, name)
            self._send(404, b"Not found")
            return
        cache_dir = os.path.join(BASE_DIR, "_cache", ext)
        cached = os.path.realpath(os.path.join(cache_dir, os.path.basename(name) + ".png"))
        if not os.path.isfile(real):
            log.warning("%s preview 404 for %r - file missing in data/", ext, name)
            self._send(404, b"Not found")
            return
        if not (os.path.isfile(cached) and os.path.getmtime(cached) >= os.path.getmtime(real)):
            try:
                os.makedirs(cache_dir, exist_ok=True)
                if ext == "exe":  # v2.4.x: [System.Drawing.Icon]::ExtractAssociatedIcon straight on the .exe
                    if not self._gdi_rasterize(real, cached):           # same call Windows Explorer uses for icons
                        log.warning("exe preview of %s failed - no usable embedded icon", name)
                elif ext == "ico":    # v2.4.x: multi-image / PNG-compressed icons can defeat GDI+
                    if not self._gdi_rasterize(real, cached):
                        embedded = self._largest_ico_image_bytes(real)
                        if not embedded:
                            log.warning("ico preview of %s failed: no embedded raster image", name)
                        else:
                            with open(cached + ".raw", "wb") as f:
                                f.write(embedded)
                            self._gdi_rasterize(cached + ".raw", cached)  # re-encode via memory stream
                else:      # wmf
                    if not self._gdi_rasterize(real, cached):
                        log.warning("wmf preview of %s failed - GDI+ FromFile rejected it", name)
            except Exception as e:  # conversion crashed -> client falls back to download-only
                log.warning("%s preview of %s failed: %s: %s", ext, name,
                            type(e).__name__, str(e).strip()[:300])
        if not (os.path.isfile(cached)
                and cached.startswith(os.path.realpath(cache_dir) + os.sep)):  # traversal guard
            log.warning("%s preview 404 for %r after conversion - cache empty", ext, name)
            self._send(404, b"Not found")
            return
        with open(cached, "rb") as f:
            body = f.read()
        self._send(200, body, {"Content-Type": "image/png", "Cache-Control": "public, max-age=86400"})

    @staticmethod
    def _largest_ico_image_bytes(ico_path) -> bytes | None:
        """v2.4.x: biggest embedded raster of a .ico (multi-image files keep every size).

        PNG-compressed entries come back as-is; classic BITMAPINFOHEADER images are re-packed
        with an ICONDIR so GDI+ can load them from memory. None = no usable raster inside."""
        import struct
        try:
            with open(ico_path, "rb") as f:
                data = f.read()
            if len(data) < 6 or data[:4] != b"\x00\x00\x01\x00":
                return None
            count = struct.unpack("<H", data[4:6])[0]
            best, best_w = None, 0
            for i in range(count):
                rec = data[6 + i * 16:22 + i * 16]
                if len(rec) < 16:
                    break
                w, h, _cc, _res, planes, bpp, isize, off = struct.unpack("<BBBBHHII", rec)
                real_w, real_h = (w or 256), (h or 256)
                chunk = data[off:off + isize]
                if len(chunk) < isize:
                    continue
                if chunk[:8] == b"\x89PNG\r\n\x1a\n":
                    if real_w > best_w:
                        best, best_w = bytes(chunk), real_w     # PNG entry - serve verbatim
                    continue
                ihdr_size = struct.unpack("<I", chunk[:4])[0] if len(chunk) >= 8 else 0   # BITMAPINFOHEADER biSize
                pix = chunk[ihdr_size:]
                bmp = pix + (b"\x00" * (-len(pix) & 3))   # bottom-up, rows padded to 4-byte boundary
                # re-pack as a single-image ICONDIR so GDI+ FromFile can load it from memory:
                # header Reserved(H)=0 Type(H)=1 Count(H)=1 + one full IMAGE_ICONDIRENTRY (offset=22)
                packed_entry = struct.pack("<BBBBHHII",
                                           w or 256, h or 256,
                                           struct.unpack_from("<B", rec, 2)[0],
                                           struct.unpack_from("<B", rec, 3)[0],
                                           struct.unpack_from("<H", rec, 4)[0],
                                           struct.unpack_from("<H", rec, 6)[0],
                                           len(bmp), 22)
                if real_w > best_w:
                    best, best_w = (b"\x00\x00\x01\x00" + struct.pack("<H", 1) + packed_entry + bmp), real_w
            return best
        except Exception:
            return None

    @staticmethod
    def _gdi_rasterize(src: str, dst: str) -> bool:
        """v2.4.x: render a bare .wmf/.ico (GDI+ FromFile), or an executable's first embedded
        icon ([System.Drawing.Icon]::ExtractAssociatedIcon), natively sized on a white bitmap.
        No pip dependency - one external powershell process saves the result as PNG."""
        # paths arrive via -File args (ps1 stays pure ASCII) - inline interpolation broke on umlaut
        # and apostrophe file names. [System.Drawing.Icon]::ExtractAssociatedIcon is what Windows
        # Explorer itself uses for .exe icons; no PE parsing or pip deps needed.
        img_stmt = ("[System.Drawing.Icon]::ExtractAssociatedIcon($src)"
                    if src.lower().endswith(".exe")
                    else "[System.Drawing.Image]::FromFile($src)")
        script = (
            "$src = $args[0]\r\n"
            "$dst = $args[1]\r\n"
            "try {\r\n"
            "  Add-Type -AssemblyName System.Drawing\r\n"
            f"  $img = {img_stmt}\r\n"
            "  if ($img.Width -lt 2 -or $img.Height -lt 2) { Write-Host 'FAIL: no size'; exit }\r\n"
            "  $w = [Math]::Min([int]$img.Width, 1920); $h = [int]($img.Height * $w / $img.Width)\r\n"
            "  if ($h -lt 2) { $h = 2 }\r\n"
            "  $bmp = New-Object System.Drawing.Bitmap([int]$w,[int]$h)\r\n"
            "  $g = [System.Drawing.Graphics]::FromImage($bmp)\r\n"
            "  $g.Clear([System.Drawing.Color]::White)\r\n"
            "  $g.DrawImage($img,0,0,$bmp.Width,$bmp.Height)\r\n"
            "  $bmp.Save('OUTPUT',[System.Drawing.Imaging.ImageFormat]::Png)\r\n"
            "  $g.Dispose(); $bmp.Dispose(); $img.Dispose()\r\n"
            "  Write-Host SAVED\r\n"
            "} catch { Write-Host ('FAIL: ' + $_.Exception.Message); exit }\r\n"
        ).replace("INPUT", src).replace("OUTPUT", dst)
        # unique per worker thread - two browsers converting different .wmf/.ico/.exe files at once
        # must not overwrite each other's script mid-run (ThreadingHTTPServer)
        ps1 = os.path.join(os.path.dirname(dst), "_convert_0x%x.ps1" % threading.get_ident())
        try:
            with open(ps1, "w", encoding="ascii") as f:
                f.write(script)
            r = subprocess.run(["powershell", "-NoProfile", "-File", ps1, src, dst], capture_output=True,
                               text=True, timeout=120)
        finally:
            try:
                os.remove(ps1)
            except OSError:  # powershell may still hold the handle - next run overwrites it
                pass
        if "SAVED" not in (r.stdout or ""):  # GDI+ rejected it - let the caller's fallback fire
            return False
        log.debug("gdi raster ok: %s -> png in cache", os.path.basename(src))
        return True


    @staticmethod
    def _extract_first_ex_icon(exe_path) -> bytes | None:
        """v2.4.x: largest embedded icon image of an executable, straight from the .rsrc section.

        Pure Python (struct only - no pip deps). Walking the PE resource directory tree fails in
        many binaries (named entries are mislabelled and leaf offsets decode to garbage), so this
        reads the .rsrc raw file range once and returns the largest image blob found inside: a
        PNG-compressed icon (Vista+, walked over chunk lengths) or a classic BITMAPINFOHEADER DIB
        with its AND mask - which is exactly what Windows' own icon picker shows for these files."""
        import struct
        try:
            with open(exe_path, "rb") as f:
                dos = f.read(64)
                if len(dos) < 64 or dos[:2] != b"MZ":
                    return None
                pe_off = struct.unpack("<I", dos[0x3C:0x40])[0]
                f.seek(pe_off)
                if f.read(4) != b"PE\x00\x00":
                    return None
                coff = f.read(20)            # Machine H, Nsec H, TDS D, PtrSym D, NumSym D, OptLen H, Char H
                nsec = struct.unpack("<H", coff[2:4])[0]
                opt_len = struct.unpack("<H", coff[16:18])[0]   # COFF is 20 bytes; optional header follows it
                f.seek(pe_off + 24 + opt_len)
                sec_hdrs, sections = f.read(nsec * 40), []
                for i in range(nsec):    # section: Name(8) VSize(D) VA(D) RawSize(D) RawPtr(D)
                    s = sec_hdrs[i * 40:(i + 1) * 40]
                    vsize, vaddr, rawsize = struct.unpack("<III", s[8:20])
                    rawptr = struct.unpack("<I", s[20:24])[0]
                    sections.append((s[:8].rstrip(b"\x00"), vaddr, rawptr, rawsize, vsize))
                rsrc = next((sec for sec in sections if sec[0] == b".rsrc"), None)
                if rsrc is None:
                    return None
                _nm_r, rv_base, rw_ptr, rs_size, rs_vsize = rsrc   # .rsrc raw file range: [rw_ptr, rw_ptr + span)

                raw_span = rs_size or rs_vsize             # raw size may be 0 on stripped binaries - fall back to virtual size
                if not (rs_size and rw_ptr < os.path.getsize(exe_path)):
                    return None                            # malformed section table: .rsrc starts past end of file
                                                           # (.rsrc need NOT be the last section - read truncates at EOF)

                f.seek(rw_ptr)
                data = f.read(raw_span)          # whole section in one read - the tree walker below is gone on purpose

                def png_end(start):             # walk chunks (IHDR..IEND) to where this PNG stops, or None if truncated
                    i = start + 8
                    while True:
                        if len(data) < i + 12:
                            return None
                        length = struct.unpack("<I", data[i:i+4])[0]
                        end = i + 12 + length
                        if data[i+4:i+8] == b"IEND":
                            return end
                        i = end                 # next chunk starts right after this one's CRC
                best_png, best_w = None, 0             # PNG-compressed icon (Vista+) - keep the largest declared width
                pos = data.find(b"\x89PNG\r\n\x1a\n")
                while pos >= 0:
                    if len(data) < pos + 24 or data[pos+12:pos+16] != b"IHDR":   # chunk type field: 8-byte sig, then length(4) + "IHDR"
                        pass
                    else:
                        end = png_end(pos)
                        pw, _ph = struct.unpack(">HH", data[pos+16:pos+20])      # biWidth/biHeight inside IHDR
                        if end and (pw or 256) > best_w:
                            best_png, best_w = data[pos:end], (pw or 256)
                    pos = data.find(b"\x89PNG\r\n\x1a\n", pos + 8)
                best_dib, best_px = None, -1          # classic BITMAPINFOHEADER DIB + AND mask - keep the largest pixel count
                pos = data.find(b"\x28\x00\x00\x00")  # biSize=40 is the first 4 bytes of a BITMAPINFOHEADER
                while pos >= 0:
                    if len(data) < pos + 40:
                        break
                    w_, h_ = struct.unpack_from("<ii", data, pos + 4)   # height signed: negative = top-down storage
                    planes_, bpp_ = struct.unpack_from("<HH", data, pos + 12)
                    comp_, _nrchans = struct.unpack_from("<II", data, pos + 16)
                    if (planes_ == 1 and bpp_ in (32, 24) and comp_ == 0          # BI_RGB only - palette/compressed stay out of scope
                            and 0 < w_ <= 512 and abs(h_) <= 512):                # icon-scale sanity bounds
                        rowbytes = ((w_ * bpp_ + 31) // 32) * 4                   # rows are padded to a DWORD boundary
                        end = pos + 40 + rowbytes * abs(h_) + (((w_ + 31) // 32) * 4) * abs(h_)   # pixels + AND mask
                        if end <= len(data):
                            px_ = w_ * abs(h_)
                            if px_ > best_px:                       # real icon groups carry >=32x32 entries, so stray pixel hits lose
                                best_dib, best_px = data[pos:end], px_
                    pos = data.find(b"\x28\x00\x00\x00", pos + 4)
                if best_w * best_w >= abs(best_px):      # PNG wins on area - it is the sharper rendition of the same icon
                    return best_png
                log.debug("ex-icon: no image blob inside .rsrc (%s, %d bytes)", os.path.basename(exe_path), len(data))
                return best_dib or None
        except Exception as e:   # corrupt / partially readable exe - fail soft, download link still works
            log.debug("ex-icon extract failed for %s: %s", os.path.basename(exe_path), e)
            return None

    @staticmethod
    def _wrap_ex_icon_blob(raw: bytes | None) -> bytes | None:
        """v2.4.x: RT_ICON payloads are raw image streams, not .ico containers.

        PNG entries already load under any extension (GDI+ sniffs content), classic images are
        bare BITMAPINFOHEADER DIBs with an AND mask glued on - GDI+'s icon codec only detects a
        proper ICONDIR header, so re-pack those into a single-image .ico exactly like the .ico
        fallback does. None in -> None out (caller logs + download-only)."""
        import struct
        if not raw or len(raw) < 4:
            return None
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            # PNG-compressed icon (Vista+) - pass through VERBATIM, no ICONDIR re-pack: GDI+ sniffs
            # the PNG signature itself, and a synthetic entry around it would just be extra bytes
            # that make its image-size decode disagree with the IHDR. Serve as-is.
            return raw
        if len(raw) >= 40 and struct.unpack("<I", raw[0:4])[0] == 40 \
                and 0 < abs(struct.unpack_from("<i", raw, 4)[0]) <= 512:
            # classic BITMAPINFOHEADER DIB (+ AND mask): GDI+'s icon codec needs a real ICONDIR
            w = struct.unpack_from("<I", raw, 4)[0]
            h = abs(struct.unpack_from("<i", raw, 8)[0]) or w   # height signed: negative = top-down
            planes, bpp = struct.unpack_from("<HH", raw, 12)
            entry = struct.pack("<BBBBHHII",
                                w % 256 or 256, h % 256 or 256,
                                0, 0, planes & 0xFFFF or 1, bpp & 0xFFFF or 32,
                                len(raw), 22)
            return b"\x00\x00\x01\x00" + struct.pack("<H", 1) + entry + raw
        return None

    def _auth_gate(self) -> str | None:
        """v2.1.0 - role for this request ('full'/'ro'), or None after a 401 JSON body was sent."""
        role = _auth_role(self.headers.get("Cookie") or "")
        if role is not None:
            return role
        self._send(401, json.dumps({"ok": False, "error": "login required"}).encode("utf-8"),
                   {"Content-Type": "application/json", "Cache-Control": "no-store"})
        return None

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/login":  # v2.1.0: password -> signed tb_auth cookie (open board: always ok)
            self._handle_login()
            return
        peer_pass = self.headers.get("X-Tiltboard-Pass")  # v2.1.0: forwarded write from the sync worker
        if peer_pass is not None and not hmac.compare_digest(peer_pass, AUTH_FULL):
            # no local human sends this header - one-sided config or wrong credential -> hard refuse
            self._send(401, json.dumps({"ok": False, "error": "sync credential mismatch"}).encode("utf-8"),
                       {"Content-Type": "application/json", "Cache-Control": "no-store"})
            return
        role = "full" if (peer_pass is not None and AUTH_FULL) else self._auth_gate()  # open board -> 'full'; forwarded peer write skips the cookie gate
        if role == "ro" and parsed.path != "/rate":
            # v2.1.0: read-only may only rate - post/delete/upload get a distinct body the client
            # turns into locked UI instead of an error toast (the composer is hidden for RO anyway)
            self._send(403, json.dumps({"ok": False, "error": "read_only"}).encode("utf-8"),
                       {"Content-Type": "application/json", "Cache-Control": "no-store"})
            return
        if parsed.path == "/delete":    # v1.5.4: remove one tilt + its source file
            self._handle_delete()
            return
        if parsed.path == "/swap":     # v2.2.0: drag & drop card reordering (RO gate above keeps it full-access only)
            self._handle_swap()
            return
        if parsed.path == "/rate":      # v1.23.0: tilt rating, one vote per visitor
            self._handle_rate()
            return
        if parsed.path == "/upload/init":       # v1.16.0: chunked upload of big attachments - streamed, constant RAM
            self._upload_init()
            return
        if parsed.path == "/upload/chunk":
            self._upload_chunk()
            return
        if parsed.path == "/upload/abort":
            self._upload_abort()
            return
        if parsed.path != "/post":
            self._send(404, b"Not found")
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("multipart/form-data"):  # post carrying an attachment
            fields, files = parse_multipart(body, ctype)
            # v1.5.8: a real newline smuggled in by any client would break the
            # one-line-per-tilt contract of chat.txt - fold it into the \\n escape.
            message = re.sub(r"\r\n|\r|\n", "\\\\n", (fields.get("message") or "").strip())  # safety net: any real newline becomes a literal \n escape
            _, filename, payload = next(iter(files), ("attachment", None, b""))
            stored_name = save_upload(filename, payload) if payload else None
        elif ctype.startswith("application/json"):  # v1.16.0: commit a finished chunked upload
            req = json.loads(body.decode("utf-8"))
            message = re.sub(r"\r\n|\r|\n", "\\\\n", str(req.get("message") or "").strip())  # same newline safety net as the other paths
            real = _stored_path(req.get("attach_stored")) if req.get("attach_stored") else None
            stored_name = os.path.basename(real) if real and os.path.isfile(real) else None  # unknown/aborted name -> plain text post, no broken link
            if message or stored_name:
                add_post(message, stored_name)
                _sync_dirty()  # v2.0.0: wake the worker - this commit must reach the passive board
                _pending_actions.put(("post", {"text": message, "attach": stored_name}))
            # The chunked client parses this reply as JSON. A 302 would make fetch() follow
            # it to the HTML board page and crash r.json() - so answer with plain JSON here.
            self._send(200, json.dumps({"ok": True}).encode(), {"Content-Type": "application/json"})
            return
        else:  # plain text post - the form's default urlencoded path
            message = re.sub(r"\r\n|\r|\n", "\\\\n", parse_qs(body.decode("utf-8")).get("message", [""])[0].strip())  # safety net: any real newline becomes a literal \n escape
            stored_name = None
        if message or stored_name:
            add_post(message, stored_name)
            _sync_dirty()  # v2.0.0: wake the worker - this commit must reach the passive board
            _pending_actions.put(("post", {"text": message, "attach": stored_name}))
        self._send(302, headers={"Location": "/"})

    def _handle_login(self):
        """v2.1.0 POST /login - verify password and issue a signed HttpOnly tb_auth cookie."""
        if not AUTH_ENABLED:  # open board: accept anything, return the full role for uniformity
            self._send(200, json.dumps({"ok": True, "role": "full"}).encode("utf-8"),
                       {"Content-Type": "application/json"})
            return
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            password = str(json.loads(self.rfile.read(length) or b"{}").get("password") or "")
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode("utf-8"),
                       {"Content-Type": "application/json"})
            return
        now = time.time()
        ip = self.client_address[0]
        fails = [t for t in _LOGIN_FAILS.get(ip, []) if now - t < 60.0]  # sweep stale entries
        _LOGIN_FAILS[ip] = fails
        if len(fails) >= 5:  # cheap brute-force cooldown ~5 attempts / minute per IP
            self._send(429, json.dumps({"ok": False, "error": "too many tries"}).encode("utf-8"),
                       {"Content-Type": "application/json"})
            return
        role = _login_ok(password)
        if role is None:
            fails.append(now)
            log.info("login failed from %s", ip)  # generic message - don't leak which roles exist
            self._send(401, json.dumps({"ok": False, "error": "bad password"}).encode("utf-8"),
                       {"Content-Type": "application/json"})
            return
        _LOGIN_FAILS.pop(ip, None)  # success clears the failure history for this IP
        cookie = f"tb_auth={role}.{_auth_sign(role)}; HttpOnly; SameSite=Lax; Path=/"
        log.info("login ok from %s (role=%s)", ip, role)
        self._send(200, json.dumps({"ok": True, "role": role}).encode("utf-8"),
                   {"Content-Type": "application/json", "Set-Cookie": cookie})

    # --- v2.0.0 sync handshake -------------------------------------------------

    def _handle_sync_state(self):
        """GET /sync/state - full diff material for the active peer: every chat line keyed by its
        stable ID plus every stored file with its size.

        Serving this route means WE are the passive side, so make sure our own lines carry IDs
        first (one-time backfill) - the peer's remote-wins diff needs a stable identity per line.
        The token gate is opt-in: an empty sync_token on this board leaves the endpoint open,
        which also keeps pure single-server installs with no peer at zero overhead. Partial or
        in-progress downloads (.part plus its .off bookkeeping) are not real attachments yet, so
        they stay out of the map.
        """
        if SYNC_TOKEN:
            provided = self.headers.get("X-Tiltboard-Sync", "")
            if provided != SYNC_TOKEN:  # wrong or missing token -> JSON error per the app convention
                self._send(401, json.dumps({"ok": False, "error": "sync token mismatch"}).encode(),
                           {"Content-Type": "application/json", "Cache-Control": "no-store"})
                return
        provided_pass = self.headers.get("X-Tiltboard-Pass", "")  # v2.1.0: peer credential
        if not hmac.compare_digest(provided_pass, AUTH_FULL):  # both empty -> open sync; one-sided or wrong -> refuse
            self._send(401, json.dumps({"ok": False, "error": "sync credential mismatch"}).encode(),
                       {"Content-Type": "application/json", "Cache-Control": "no-store"})
            return
        backfill_line_ids()  # idempotent: no-op when every line already carries its ID
        lines = {}
        with _chat_lock:
            try:
                with open(CHAT_PATH, encoding="utf-8") as f:
                    raw_lines = [ln.rstrip("\n") for ln in f]
            except OSError:
                raw_lines = []
        dropped_no_id = 0
        for ln in raw_lines:  # skip blanks and the one-time backfill marker if present
            m = LINE_ID_RE.search(ln)
            if not m:
                if ln.strip():
                    dropped_no_id += 1
                    log.debug("sync/state: line without ID after backfill - %r", ln[:80])
                continue
            key = m.group(0)
            if key in lines:  # v2.2.x: residual duplicate would be hidden by last-wins - surface it
                log.warning("sync/state: duplicate line ID %s in chat.txt - earlier copy is shadowed", key.lstrip())
            lines[key] = ln
        files = {}
        try:
            for entry in os.scandir(DATA_FOLDER):
                if not entry.is_file() or entry.name.startswith("."):
                    continue  # staging names are dot-prefixed: .part bodies and .off offsets
                files[entry.name] = entry.stat().st_size
        except OSError:
            pass
        log.debug("sync/state serving to %s: %d line(s) with ID, %d file(s), dropped_no_id=%d, chat.txt lines total=%d",
                  self.client_address[0], len(lines), len(files), dropped_no_id, len(raw_lines))
        self._send(200, json.dumps({"lines": lines, "files": files}).encode("utf-8"),
                   {"Content-Type": "application/json", "Cache-Control": "no-store"})

    # --- v1.16.0: chunked upload of big attachments ---------------------------
    # Files above CHUNK_UPLOAD_LIMIT arrive in ~8 MB pieces (file.slice on the client), so
    # neither side ever holds a whole multi-GB body; every read below stays at STREAM_BUF bytes.

    def _upload_init(self):
        """POST /upload/init {name} - reserve a stored name for a chunked upload."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        stored = reserve_upload(req.get("name")) if isinstance(req.get("name"), str) else None
        self._send(200 if stored else 409,
                   json.dumps({"ok": bool(stored), "stored": stored}).encode())

    def _upload_chunk(self):
        """POST /upload/chunk, header X-Stored-Name (+ X-Chunk-Offset) - write one chunk to disk.

        v2.4.x: clients percent-encode the stored name for ISO-8859-1-only headers (Czech etc.); unquote
        restores it exactly - an ASCII name without '%' passes through untouched."""
        stored_name = urllib.parse.unquote(self.headers.get("X-Stored-Name") or "")
        real = _stored_path(stored_name)
        if not real:  # unknown or escaping name -> nothing to append to
            self._send(404, json.dumps({"ok": False, "error": "unknown upload"}).encode())
            return
        try:
            total = int(self.headers.get("Content-Length", 0))  # v1.24.0: remember for the debug log
            remaining = total
            offset = int(self.headers.get("X-Chunk-Offset", -1))
            # v1.16.1: with X-Chunk-Offset the write is idempotent - seek to this chunk's own byte
            # offset instead of appending, so a retried request after a dropped connection can never
            # duplicate bytes (sequential uploads keep the file exactly at that position).
            out = open(real, "r+b" if offset >= 0 else "ab")
            if offset >= 0:
                out.seek(offset)
            with out:  # stream to disk in STREAM_BUF reads - constant RAM
                while remaining > 0:
                    buf = self.rfile.read(min(STREAM_BUF, remaining))
                    if not buf:
                        break
                    out.write(buf)
                    remaining -= len(buf)
        except OSError as e:
            log.warning("chunked upload failed: %s", e)
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
            return
        if log.isEnabledFor(logging.DEBUG):  # v1.24.0: extended logging - which chunk landed on disk
            try:
                size = os.path.getsize(real)
            except OSError:
                size = -1
            log.debug("action=upload/chunk stored=%s offset=%d wrote=%d bytes file-size=%d",
                      stored_name, offset, total - remaining, size)
        self._send(200, json.dumps({"ok": True}).encode())

    def _upload_abort(self):
        """POST /upload/abort {stored} - best-effort removal of a partial upload."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        log.debug("action=upload/abort stored=%r", req.get("stored"))  # v1.24.0: extended logging
        real = _stored_path(req.get("stored")) if isinstance(req.get("stored"), str) else None
        if real and os.path.isfile(real):
            try:
                os.remove(real)
            except OSError as e:  # an abandoned name simply stays on disk
                log.warning("could not remove partial upload %r: %s", real, e)
        self._send(200, json.dumps({"ok": True}).encode())

    def _handle_delete(self):
        """POST /delete - remove one tilt from chat.txt and its source file.

        The client sends the exact text plus the attachment's stored name (or
        null). find_post_line() re-reads chat.txt fresh, so a concurrent post
        or blank line can never shift the match. Only lines that split back to
        exactly this identity are removed; if the attachment file still lives
        inside the data folder it is physically deleted too.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            text, name = str(req.get("text", "")), req.get("attach")
            attach_name = name if isinstance(name, str) and name else None
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        idx = find_post_line(text, attach_name)
        if not idx:
            self._send(404, json.dumps({"ok": False, "error": "tilt not found"}).encode())
            return
        log.debug("action=delete text=%r attach=%s", text[:80], attach_name)  # v1.24.0: extended logging
        removed_file = False
        try:
            with _chat_lock:  # v2.0.0: whole read-modify-write of chat.txt atomized
                with open(CHAT_PATH, encoding="utf-8") as f:
                    lines = [ln.rstrip("\n") for ln in f]
                _text, path = split_line(lines[idx - 1])
                if path and attach_name and os.path.basename(path) == attach_name:
                    real, root = os.path.realpath(path), os.path.realpath(DATA_FOLDER)
                    inside = True
                    try:
                        inside = os.path.commonpath([real, root]) == root
                    except ValueError:  # cross-drive / UNC-vs-local mismatch -> outside
                        inside = False
                    if inside and os.path.isfile(real):
                        os.remove(real)  # physically delete the source file/picture
                        removed_file = True
                del lines[idx - 1]
                with open(CHAT_PATH, "w", encoding="utf-8") as f:
                    for ln in lines:  # every other line is preserved byte-for-byte
                        if ln.strip():
                            f.write(ln + "\n")
        except OSError as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
            return
        try:  # keep the in-memory store consistent until the page reloads
            for i, p in enumerate(POSTS):
                if p["text"] == text and (not attach_name or
                        (p.get("attach") and p["attach"]["name"] == attach_name)):
                    del POSTS[i]
                    break
        except Exception:  # memory is only a cache; chat.txt is the source of truth
            pass
        snippet = text.replace("\n", " ")[:60]
        log.info("tilt deleted (chat.txt line %d): %s%s", idx, snippet,
                 f" (source file {attach_name} removed)" if removed_file else "")
        _sync_dirty()  # v2.0.0: queue the deletion for forwarding to the passive board
        _pending_actions.put(("delete", {"text": text, "attach": attach_name}))
        self._send(200, json.dumps({"ok": True, "removed_file": removed_file}).encode(),
                   {"Content-Type": "application/json"})

    def _handle_swap(self):  # v2.2.0: drag & drop card reordering - two tilts exchange places
        """POST /swap - exchange the positions of two tilts in chat.txt.

        The client sends both cards' identities (idA/textA/attachA, idB/...
        textA is the display text exactly as rendered - rating tails and ID
        tokens are stripped before it reaches us). Identity priority: the stable
        v2.0 line-ID token when present, else content match via find_post_line()
        (same semantics /delete uses). The two whole lines are swapped byte-for-byte,
        so ratings, attachments, names and IDs all travel with their cards.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        idA, textA = str(req.get("idA", "")), str(req.get("textA", ""))
        att_rawA = req.get("attachA")
        attachA = att_rawA if isinstance(att_rawA, str) and att_rawA else None
        idB, textB = str(req.get("idB", "")), str(req.get("textB", ""))
        att_rawB = req.get("attachB")
        attachB = att_rawB if isinstance(att_rawB, str) and att_rawB else None
        if not (idA or textA) or not (idB or textB):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        log.debug("action=swap A(id=%s %r) <-> B(id=%s %r)",  # v1.24.0: extended logging
                  idA or "-", textA[:60], idB or "-", textB[:60])
        try:  # same benign race as /delete and /rate accept for their index lookup
            lines = [ln.rstrip("\n") for ln in open(CHAT_PATH, encoding="utf-8")]
        except OSError as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
            return

        def id_index(token):  # stable v2.0 line-ID token wins when the card carries one
            if not token:
                return 0
            hits = []
            for n, ln in enumerate(lines, 1):
                m = LINE_ID_RE.search(ln)
                if m and m.group(0).strip() == token:
                    hits.append(n)
            if len(hits) > 1:  # v2.2.x: duplicated line-ID - first match is ambiguous, say so loudly
                log.warning("swap id '%s' occurs %d times (lines %s) - using the FIRST one; "
                            "the board has duplicate line IDs, repair chat.txt tokens",
                            token, len(hits), hits)
            return hits[0] if hits else 0
        idxA, idxB = id_index(idA), id_index(idB)  # pre-sync rows fall back to /delete semantics
        if not idxA:  # same benign race as /delete and /rate accept for their index lookup
            idxA = find_post_line(textA, attachA)
        if not idxB:
            idxB = find_post_line(textB, attachB)
        if not (idxA and idxB):
            self._send(404, json.dumps({"ok": False, "error": "tilt not found"}).encode())
            return
        try:
            if idxA == idxB:  # released inside its own zone - nothing to move
                log.debug("swap no-op (same line %d) - ignored", idxA)  # v1.24.0: extended logging
                self._send(200, json.dumps({"ok": True}).encode(),
                           {"Content-Type": "application/json"})
                return
            with _chat_lock:  # v2.0.0: the whole read-swap-write of chat.txt stays atomic
                lines = [ln.rstrip("\n") for ln in open(CHAT_PATH, encoding="utf-8")]
                if not (1 <= idxA <= len(lines)) or not (1 <= idxB <= len(lines)):  # v2.2.0: newest tilt is line len() - must stay valid
                    self._send(404,
                               json.dumps({"ok": False, "error": "tilt not found"}).encode())
                    return
                lines[idxA - 1], lines[idxB - 1] = (lines[idxB - 1], lines[idxA - 1])  # byte-for-byte swap
                with open(CHAT_PATH, "w", encoding="utf-8") as f:
                    for ln in lines:  # every other line is preserved byte-for-byte
                        if ln.strip():
                            f.write(ln + "\n")
        except OSError as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
            return
        def matches(p, text, attach):  # display text + stored attachment name identify a card
            if p.get("text") != text:
                return False
            pname = (p.get("attach") or {}).get("name", "") if isinstance(p.get("attach"), dict) else None
            return attach is None or pname == attach
        try:  # mirror the new order in memory - restore_posts() only runs at startup
            ia = ib = None
            for n, p in enumerate(POSTS):
                if ia is None and ((idA and p.get("id") == idA)
                        or (not idA and matches(p, textA, attachA))):
                    ia = n
                elif ib is None and n != ia and ((idB and p.get("id") == idB)
                        or (not idB and matches(p, textB, attachB))):
                    ib = n
            if ia is not None and ib is not None:
                POSTS[ia], POSTS[ib] = POSTS[ib], POSTS[ia]
        except Exception:  # memory is only a cache; chat.txt is the source of truth
            pass
        log.info("tilts swapped (chat.txt lines %d <-> %d): %r <-> %r", idxA, idxB,
                 textA[:40], textB[:40])
        _sync_dirty()  # v2.0.0: queue the swap for forwarding to the passive board
        _pending_actions.put(("swap", {"idA": idA, "textA": textA, "attachA": attachA,
                                       "idB": idB, "textB": textB, "attachB": attachB}))
        self._send(200, json.dumps({"ok": True}).encode(),
                   {"Content-Type": "application/json"})

    def _handle_rate(self):
        """POST /rate - add one vote (up/down/heart/smile) to a tilt.

        The client sends the exact text plus the attachment's stored name or
        null, like /delete. find_post_line() re-reads chat.txt fresh and skips
        rating tails when comparing identity, so rated lines still match. The
        "::a:b:c:d" tail is rebuilt between the display text and any file://
        token; bytes from the attachment marker onward are preserved verbatim.
        A brand-new line gets "::0:0:0:0" with just the clicked icon bumped,
        so the four counts always exist after the first rating.
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            text, name = str(req.get("text", "")), req.get("attach")
            attach_name = name if isinstance(name, str) and name else None
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        log.debug("action=rate icon=%s text=%r attach=%s",
                  req.get("icon", "?"), text[:80], attach_name)  # v1.24.0: extended logging
        icon_idx = {"up": 0, "down": 1, "heart": 2, "smile": 3}.get(req.get("icon", ""))
        if icon_idx is None:
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
        idx = find_post_line(text, attach_name)
        if not idx:
            self._send(404, json.dumps({"ok": False, "error": "tilt not found"}).encode())
            return
        try:
            with _chat_lock:  # v2.0.0: whole read-modify-write of chat.txt atomized
                with open(CHAT_PATH, encoding="utf-8") as f:
                    lines = [ln.rstrip("\n") for ln in f]
                raw = lines[idx - 1]
                id_m = LINE_ID_RE.search(raw)   # v2.0.0: the stable ID token rides at the very end
                line_no_id = (raw[:id_m.start()].rstrip() if id_m else raw)
                m = ATTACH_RE.search(line_no_id)      # keep the attachment tail byte-for-byte
                base = (line_no_id[:m.start()] if m else line_no_id).rstrip()
                counts = [0, 0, 0, 0]
                rm = RATING_RE.search(base)
                if rm:
                    counts = [int(g) for g in rm.groups()]
                    base = base[:rm.start()].rstrip()
                counts[icon_idx] += 1
                lines[idx - 1] = (f"{base}::{counts[0]}:{counts[1]}:{counts[2]}:{counts[3]}"
                                  + (line_no_id[m.start():] if m else "")
                                  + ((id_m.group(0) or " ") if id_m else ""))
                with open(CHAT_PATH, "w", encoding="utf-8") as f:
                    for ln in lines:  # every other line is preserved byte-for-byte
                        if ln.strip():
                            f.write(ln + "\n")
        except OSError as e:
            self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
            return
        try:  # keep the in-memory store consistent until the page reloads
            for p in POSTS:
                if p["text"] == text and (not attach_name or
                        (p.get("attach") and p["attach"]["name"] == attach_name)):
                    p["rating"] = counts
                    break
        except Exception:  # memory is only a cache; chat.txt is the source of truth
            pass
        log.info("tilt rated %s (chat.txt line %d): %d:%d:%d:%d", req.get("icon", "?"), idx, *counts)
        _sync_dirty()  # v2.0.0: queue the rating for forwarding to the passive board
        _pending_actions.put(("rate", {"icon": req.get("icon"), "text": text, "attach": attach_name}))
        self._send(200, json.dumps({"ok": True, "rating": counts}).encode(),
                   {"Content-Type": "application/json"})

    def log_message(self, fmt, *args):  # route stdlib access logging into tiltboard.log
        line = fmt % args if args else fmt
        code = None
        # The stdlib calls this as ('"%s" %s %s', requestline, '200', '-') — the numeric
        # status is a trailing arg but NOT last (last is size, usually '-'), so scan
        # backwards for the first purely-numeric argument.
        for a in reversed(args):
            try:
                code = int(str(a))
                break
            except ValueError:
                continue
        # v2.1.5: the /posts poll's 401 from a locked tab (do_GET sets _quiet_401 for that one route)
        # is expected noise - only shown with "debug": 1; every other failure remains visible at WARNING
        quiet = getattr(self, "_quiet_401", False) and code == 401
        self._quiet_401 = False  # consume it so a stale value can't leak into the next request
        if code is not None and code >= 400 and not quiet:
            log.warning("request: %s", line)   # failures always visible
        else:
            log.debug("request: %s", line)     # routine traffic (and quieted polls) stay quiet


def find_post_line(text: str, attach_name: str | None) -> int:
    """1-based index of the chat.txt line holding this exact tilt (0 = none).

    Identity is content-based - text must match exactly and, when the tilt has
    an attachment, the stored file's basename must equal `attach_name`. This
    survives blank lines or appends happening since startup; a text-only
    duplicate removes just one of them, which is what "delete this tilt" means.
    Attachment names stay unique while their files exist (save_upload numbers
    collisions with _1, _2 ...), so a real duplicate needs the same text and a
    file whose number was freed by deleting its old tilt.
    """
    try:
        with open(CHAT_PATH, encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
    except OSError:
        log.debug("find_post_line unreadable chat.txt for text=%r", text[:80])  # v1.24.0: extended logging
        return 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        t, path = split_line(line)
        if RATING_RE.sub("", t) != text:  # v1.23.0: a rating tail must not break identity
            continue
        if attach_name is None or (path and os.path.basename(path) == attach_name):
            log.debug("find_post_line matched chat.txt line %d of %d",
                      i + 1, len(lines))  # v1.24.0: extended logging
            return i + 1
    log.debug("find_post_line no match for text=%r attach=%s (%d lines)",
              text[:80], attach_name, len(lines))  # v1.24.0: extended logging
    return 0


def local_lan_ip():
    """Best-effort LAN IP for the startup banner (UDP connect sends no packets)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------------------
# v2.0.0 sync worker
# ---------------------------------------------------------------------------
# Active side only (server_1_sync set). Every tick the worker first forwards any
# locally committed actions to the passive board, then pulls the peer's full state
# and reconciles chat.txt line-by-line (remote-wins on same-ID conflicts), then
# downloads missing data files with Range-resume. On any transport error it backs
# off ~30 s and keeps ticking - the thread never dies from a single failed tick.
_SYNC_TICK = 2.0          # steady-state poll interval in seconds
_SYNC_BACKOFF = 30.0      # cooldown after a failed forward or pull before retrying
_FETCH_WORKERS = 3        # concurrent file downloads during large initial syncs
_FORWARD_FAIL_DROP = 5    # drop an action with a log entry after this many retries


def _sync_headers() -> dict:
    headers = {"User-Agent": "TiltboardSync/" + VERSION}
    if SYNC_TOKEN:
        headers["X-Tiltboard-Sync"] = SYNC_TOKEN
    if AUTH_FULL:  # v2.1.0: pass_full_access doubles as the peer credential for every sync call
        headers["X-Tiltboard-Pass"] = AUTH_FULL
    return headers


def _sync_push_file(stored_name: str) -> None:
    """Push a local attachment to the passive board via its chunked upload flow.
    No-op when the file already exists there (size matches)."""
    src = os.path.join(DATA_FOLDER, stored_name)
    if not os.path.isfile(src):
        log.warning("sync forward: local attach missing from data folder: %s", stored_name)
        return stored_name
    size = os.path.getsize(src)
    try:
        req = urllib.request.Request(SYNC_REMOTE + "/files/" + urllib.parse.quote(stored_name),
                                     headers=_sync_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            if int(resp.headers.get("Content-Length") or 0) == size:
                return stored_name  # already there - nothing to do
    except Exception:
        pass  # 404 (or unreachable) means we must upload it
    init_data = json.dumps({"name": stored_name}).encode()
    req = urllib.request.Request(SYNC_REMOTE + "/upload/init",
                                 headers={**_sync_headers(), "Content-Type": "application/json"},
                                 data=init_data)
    with urllib.request.urlopen(req, timeout=30) as resp:
        init_resp = json.loads(resp.read().decode())
    stored_name = init_resp.get("stored") or stored_name
    if not os.path.join(DATA_FOLDER, stored_name).startswith(DATA_FOLDER):
        raise RuntimeError(f"sync forward: unsafe stored name from remote {stored_name!r}")
    chunk = 8 * 1024 * 1024
    off = 0
    with open(src, "rb") as fh:
        while True:
            part = fh.read(chunk)
            if not part:
                break
            req = urllib.request.Request(SYNC_REMOTE + "/upload/chunk",
                                         data=part,
                                         headers={**_sync_headers(),  # v2.4.x: same ISO-8859-1 header rule as the browser
                                                   "X-Stored-Name": urllib.parse.quote(stored_name),
                                                   "X-Chunk-Offset": str(off),
                                                   "Content-Type": "application/octet-stream"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
            off += len(part)
    log.info("sync forward: uploaded %s (%d bytes) to passive board", stored_name, size)


def _sync_forward(action: str, payload: dict) -> None:
    """POST one local commit action to the passive board with its client JSON keys."""
    if action == "post":
        body = {"message": payload["text"]}
        attach = payload.get("attach")
        if attach:
            attached = _sync_push_file(attach)
            body["attach_stored"] = attached or payload.get("attach")
    elif action == "delete":
        body = {"text": payload["text"], "attach": payload.get("attach")}
    elif action == "swap":  # v2.2.0: forward the swap to a passive board's /swap
        body = {k: payload.get(k) for k in ("idA", "textA", "attachA",
                                            "idB", "textB", "attachB")}
    else:  # rate
        body = {"icon": payload.get("icon"), "text": payload["text"],
                "attach": payload.get("attach")}
    path = "/" + action
    data = json.dumps(body).encode()
    req = urllib.request.Request(SYNC_REMOTE + path, data=data,
                                 headers={**_sync_headers(),
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _sync_forward_queue() -> None:
    """Drain pending local actions; keep failing ones queued for the next tick."""
    if not SYNC_REMOTE or _pending_actions.empty():
        return
    retry: list[tuple[str, dict]] = []
    fails: dict[int, int] = {}
    while True:
        try:
            action, payload = _pending_actions.get_nowait()
        except queue.Empty:
            break
        try:
            _sync_forward(action, payload)
            log.info("sync forward ok: %s", action)
        except Exception as e:
            idx = id(payload)
            fails[idx] = fails.get(idx, 0) + 1
            if fails[idx] >= _FORWARD_FAIL_DROP:
                log.error("sync forward dropped after %d tries: %s (%s)",
                          fails[idx], action, e)
            else:
                retry.append((action, payload))
    for item in retry:
        _pending_actions.put(item)


def _sync_pull_state() -> dict | None:
    try:
        req = urllib.request.Request(SYNC_REMOTE + "/sync/state",
                                     headers=_sync_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            state = json.loads(resp.read().decode("utf-8"))
            log.debug("sync pull ok from %s: %d line(s), %d file(s)",
                      SYNC_REMOTE, len(state.get("lines") or {}), len(state.get("files") or {}))
            return state
    except Exception as e:
        log.debug("sync pull failed: %s", e)
        return None


def _sync_rehome(line: str) -> str:
    """Re-root a remote chat.txt line's trailing file:// token onto this board's data folder.

    persist_text() bakes each peer's own absolute path into every attachment token, so one and the same
    tilt carries different link roots on each side (file://D:/peer/data/x.jpg there vs ... here).
    Sync fetches data files by stored name, so once downloaded the local file is at DATA_FOLDER/<name>;
    only the root of the path inside the token needs rewriting. UNC tokens or names without a local
    counterpart pass through untouched rather than being mangled."""
    if not line:
        return line
    mid = LINE_ID_RE.search(line)   # trailing ID token would otherwise block the EOL attachment match below
    body, idtok = ((line[:mid.start()] or "").rstrip(), mid.group(0)) if mid else (line, "")
    m = ATTACH_RE.search(body)
    if not m:
        log.debug("sync_rehome: no attachment token in %r", line[:80])
        return line  # no attachment tail - plain text, nothing to re-root
    try:
        parsed = urllib.parse.urlsplit(m.group(1))
        netloc = parsed.netloc
        path = urllib.parse.unquote(parsed.path)
        if len(netloc) == 2 and netloc[1] == ":":   # file://D:/x/y.jpg -> drive sits in the netloc
            name = os.path.basename((netloc + path).replace("/", os.sep))
        elif netloc.startswith("//") or path.startswith("\\\\"):
            log.debug("sync_rehome: UNC token left untouched in %r", m.group(1))
            return line  # UNC - no local counterpart yet, leave alone
        else:                                              # file:///D:/x/y.jpg -> drive in the path
            name = os.path.basename(path.replace("/", os.sep))
    except Exception:
        log.debug("sync_rehome: unparseable token %r - left untouched", m.group(1))
        return line  # unparseable token - leave it untouched
    if not name or os.path.basename(name) != name \
            or not os.path.isfile(os.path.join(DATA_FOLDER, name)):
        log.debug("sync_rehome: local file NOT present for %r (expected in %s) - token left as-is",
                  name, DATA_FOLDER)
        return line  # must exist locally (sync fetched it by stored name)
    local = "file://" + os.path.normpath(os.path.join(DATA_FOLDER, name)).replace("\\", "/")
    log.debug("sync_rehome: %r -> %r", m.group(1), local)
    return body[:m.start(1)] + local + idtok  # keep the separating space; re-append ID token byte-identical


def _sync_apply_lines(state: dict) -> bool:
    """Reconcile chat.txt against the remote lines map under _chat_lock.
    Returns False when the peer's backfill has not run yet (empty lines)."""
    raw_remote = state.get("lines") or {}
    if not raw_remote:
        return False
    # keys arrive with LINE_ID_RE's leading space; drop it so every lookup below is space-free,
    # and re-root each remote line's attachment path onto our own data folder before comparing
    remote = {k[1:] if k.startswith(" ") else k: _sync_rehome(v) for k, v in raw_remote.items()}
    log.debug("sync apply: remote map has %d line(s)", len(remote))
    with open(CHAT_PATH, "r", encoding="utf-8", errors="replace") as fh:
        local_lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    log.debug("sync apply: local chat.txt has %d non-empty line(s)", len(local_lines))
    local_ids: set[str] = set()
    keep: list[str] = []
    dropped_lines: list[str] = []  # v2.3.x fix B: REMOTELY DELETED lines (strict mirror)
    conflict_lids: set[str] = set()  # same ID on both sides, different text -> remote wins
    for ln in local_lines:
        stripped, _seq = _strip_line_id(ln)
        m = LINE_ID_RE.search(stripped) or LINE_ID_RE.search(ln)
        lid = m.group(0)[1:] if m else None
        if lid and lid in local_ids:  # defensive - IDs are unique by construction
            keep.append(ln)
            continue
        local_ids.add(lid or ln)
        rtext = remote.get(lid) if lid else None
        if lid is None:
            keep.append(ln)  # ID-less line - no counterpart on the peer, never dropped
            continue
        if rtext is None:
            # v2.3.x sync fix B (strict mirror): a local line whose ID the remote map does not carry was
            # deleted on the peer (or its forward was dropped) - drop it locally too and unlink an attachment
            # nothing else references anymore. Safe: the forward queue drains before every pull, so no freshly-
            # posted local line can be missing from a successful pull's map; a failed pull skips this whole pass.
            dropped_lines.append(ln)
            log.debug("sync apply: REMOTELY DELETED line %s -> dropping locally: %r", lid, stripped[:60])
            continue
        if _strip_line_id(rtext.rstrip("\n"))[0] == stripped:
            keep.append(ln)  # identical content on both sides (IDs stripped from the remote value)
            log.debug("sync apply: line %s IDENTICAL on both sides - kept", lid)
            continue
        conflict_lids.add(lid)  # dropped from keep; the remote copy is appended below
        log.debug("sync apply: CONFLICT id=%s local=%r remote=%r -> remote wins, local dropped",
                  lid, stripped[:60], _strip_line_id(rtext.rstrip('\n'))[0][:60])
    # NOTE: keys of the lines map are IDs in the peer's chat.txt line order; values carry full line
    # text with that ID at end. That iteration IS the peer's authoritative sequence, so the rewrite
    # below emits shared/conflict/remote-only lines exactly there instead of scattering them - a remote-
    # only tilt must display where the peer shows it (their top = newest), not as our oldest tail line.
    kept_ids: set[str] = set()
    to_append: list[str] = []
    for rid, rtext in remote.items():
        if rid == "::":
            continue
        stripped_r, _seq = _strip_line_id(rtext.rstrip("\n"))
        m = LINE_ID_RE.search(stripped_r) or LINE_ID_RE.search(rtext.rstrip("\n"))
        rlid = m.group(0)[1:] if m else None
        if rlid is not None:
            rid_key = rlid
        else:
            rid_key = rid  # pre-backfill remote key form - tolerate it, never re-append ours
        if rid_key in local_ids and rid_key not in conflict_lids:
            log.debug("sync apply: remote line %s already present locally - keep its peer position", rid_key)
            continue  # identical copy kept above, or a pre-backfill key we never re-append
        to_append.append(rtext.rstrip("\n"))
        kept_ids.add(rid_key)
    # v2.3.x sync fix B: unlink attachments of REMOTELY DELETED lines when no surviving line still names
    # them. Duplicate-tolerant by design - a name referenced by any kept/appended line stays on disk;
    # conflict-lid drops are NOT handled here (their remote copy is appended; _sync_files fetches the file).
    if dropped_lines:
        surviving_names: set[str] = set()
        for ln2 in [*keep, *(t.rstrip("\n") for t in to_append)]:
            am = ATTACH_RE.search(_strip_line_id(ln2)[0])
            if am:
                surviving_names.add(am.group(1).rstrip("/").rsplit("/", 1)[-1].lower())
        for ln3 in dropped_lines:
            am = ATTACH_RE.search(_strip_line_id(ln3)[0])
            if not am:
                continue
            name = unquote(am.group(1).rstrip("/").rsplit("/", 1)[-1].lower())
            fpath = os.path.join(DATA_FOLDER, name)
            if name in surviving_names:
                log.debug("sync apply: dropped line %s attachment kept (still referenced): %r",
                          _strip_line_id(ln3)[0][-24:], name)
                continue
            try:
                if os.path.isfile(fpath):
                    os.remove(fpath)
                    log.info("sync unlink REMOTELY DELETED attachment: %s", fpath)
                else:
                    log.debug("sync apply: dropped line %s has no local attachment file to remove: %r",
                              _strip_line_id(ln3)[0][-24:], name)
            except OSError as exc:
                log.warning("sync unlink REMOTELY DELETED attachment failed for %r - %s", fpath, exc)
    # v2.3.x sync fix C (ordering): emit shared + remote-only lines in the PEER's map iteration order
    # (= its chat.txt line order; new posts sit at file TOP there), then any local-only leftovers - id-
    # less legacy and duplicate-ID defensive keeps - after them. Dropped/conflict lines stay excluded as
    # before. Content of a shared line is our own byte text (already re-homed); only its position may move.
    new_lines: list[str] = []
    local_by_id: dict[str, str] = {}
    for ln in keep:
        m2 = LINE_ID_RE.search(ln)
        lid2 = m2.group(0)[1:] if m2 else None
        if lid2 and lid2 not in local_by_id:
            local_by_id[lid2] = ln
    moved_lids: list[str] = []
    placed_ids: set[str] = set()  # lids already emitted at their peer slot - leftovers below keep only what this missed
    for rid, rtext in remote.items():
        if rid == "::":
            continue
        stripped_r, _seq = _strip_line_id(rtext.rstrip("\n"))
        m3 = LINE_ID_RE.search(stripped_r) or LINE_ID_RE.search(rtext.rstrip("\n"))
        rlid2 = m3.group(0)[1:] if m3 else None
        rid_key2 = rlid2 if rlid2 is not None else rid
        ln_local = local_by_id.get(rid_key2)
        placed_ids.add(rid_key2)
        if ln_local is not None and rid_key2 in conflict_lids:
            new_lines.append(rtext.rstrip("\n"))  # conflict - peer's copy wins content AND position
        elif ln_local is not None:
            new_lines.append(ln_local)            # shared identical text, now at the peer's slot
            if local_lines.index(ln_local) != len(new_lines):
                moved_lids.append(rid_key2)
        elif rid_key2 in kept_ids:                # remote-only / pre-backfill - was appended at our tail before
            new_lines.append(rtext.rstrip("\n"))
    for ln in keep:  # leftovers - id-less legacy lines + duplicate-ID defensive keeps, never moved by this pass
        m4 = LINE_ID_RE.search(ln)
        lid3 = m4.group(0)[1:] if m4 else None
        if lid3 is None or lid3 not in placed_ids:
            new_lines.append(ln)
    log.debug("sync apply: verdict - %d local line(s), %d kept (drops=%d conflict-lid), peer order %d line(s)%s",
              len(local_lines), len(keep), len(local_lines) - len(keep), len(new_lines),
              ", moved " + str(moved_lids) if moved_lids else "")
    changed = False
    if new_lines != local_lines:
        log.debug("sync apply: REWRITING chat.txt to peer sequence (%d -> %d lines)", len(local_lines), len(new_lines))
        tmp = CHAT_PATH + ".sync.tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            for ln in new_lines:
                fh.write(ln + "\n")
        os.replace(tmp, CHAT_PATH)
        changed = True
    if changed:
        restore_posts()
    return True


def _sync_fetch_file(name: str, size: int) -> None:
    """Download one data file with dot-prefixed staging and Range resume."""
    dest = os.path.join(DATA_FOLDER, name)
    part = os.path.join(DATA_FOLDER, "." + name + ".part")
    off_path = os.path.join(DATA_FOLDER, "." + name + ".off")
    have = 0
    if os.path.isfile(part) and os.path.isfile(off_path):
        try:
            with open(off_path, "r", encoding="utf-8") as fh:
                have = int(fh.read().strip() or 0)
        except Exception:
            have = 0
        log.debug("sync fetch %s: resuming from offset %d of %d", name, have, size)
    url = SYNC_REMOTE + "/files/" + urllib.parse.quote(name)
    while True:
        headers = _sync_headers()
        if have > 0:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                code = resp.status
                total = int(resp.headers.get("Content-Length") or 0)
                mode = "ab" if (code == 206 and have > 0) else "wb"
                if mode == "wb":
                    have = 0
                with open(part, mode, buffering=1024 * 1024) as fh:
                    while True:
                        chunk = resp.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        have += fh.write(chunk)
        except Exception as e:
            log.debug("sync fetch %s retry from offset %d: %s", name, have, e)
            with open(off_path, "w", encoding="utf-8") as fh:
                fh.write(str(have))
            time.sleep(_SYNC_BACKOFF)
            continue
        if os.path.isfile(part) and os.path.getsize(part) == size:
            os.replace(part, dest)
            try:
                os.remove(off_path)
            except OSError:
                pass
            log.info("sync fetched %s (%d bytes)", name, size)
            return
        with open(off_path, "w", encoding="utf-8") as fh:
            fh.write(str(have))
        if have >= size:
            os.replace(part, dest)
            try:
                os.remove(off_path)
            except OSError:
                pass
            return
    


def _sync_files(state: dict) -> None:
    remote = state.get("files") or {}
    local = set()
    if os.path.isdir(DATA_FOLDER):
        for entry in os.scandir(DATA_FOLDER):
            if not entry.name.startswith(".") and entry.is_file():
                local.add(entry.name)
    pending = [(n, s) for n, s in remote.items() if n not in local]
    lock = threading.Lock()
    threads: list[threading.Thread] = []

    def _claim():
        with lock:
            if not pending:
                return None
            return pending.pop(0)

    def _worker() -> None:
        while True:
            got = _claim()
            if got is None:  # queue drained - exit cleanly (no StopIteration gymnastics)
                return
            name, size = got
            try:
                _sync_fetch_file(name, size)
            except Exception as e:
                log.debug("sync fetch %s failed: %s", name, e)

    with lock:
        count = len(pending)
        for _ in range(min(_FETCH_WORKERS, count)):
            t = threading.Thread(target=_worker, daemon=True)
            threads.append(t)
            t.start()
    if count:
        log.info("sync fetch pool started: %d file(s), worker cap %d", count, min(_FETCH_WORKERS, count))
    else:
        log.debug("sync files: all %d remote file(s) already present locally - nothing to download",
                  len(remote))
    for t in threads:  # join every worker; each keeps claiming until the queue is dry
        t.join()


def _sync_worker() -> None:
    log.info("sync worker started: mirroring %s", SYNC_REMOTE)
    first_tick = True
    tick_no = 0
    while True:
        try:
            _sync_wake.wait(timeout=_SYNC_TICK)
            _sync_wake.clear()
            _sync_forward_queue()
            tick_no += 1
            log.debug("sync worker: tick #%d", tick_no)
            state = _sync_pull_state()
            if not isinstance(state, dict):
                log.debug("sync worker: tick #%d got no state (peer unreachable) - skipping diff", tick_no)
                continue  # next tick after a quiet backoff-free gap
            ok = _sync_apply_lines(state) 
            if not ok and first_tick:
                log.info("sync: passive board still backfilling line IDs - skipping line diff this tick")
            elif not ok:
                pass  # passive side genuinely empty; local file stays untouched
            else:
                _sync_files(state)
        except Exception as e:
            log.warning("sync worker tick error (retrying in %ds): %s", int(_SYNC_BACKOFF), e)
            time.sleep(_SYNC_BACKOFF)
        finally:
            first_tick = False


def main():
    backfill_line_ids()  # v2.0.0 sync: stable-ID backfill + _id_seq seed (idempotent, always runs)
    restore_posts()
    if SYNC_REMOTE:  # v2.0.0 active side - start the sync daemon before serving
        threading.Thread(target=_sync_worker, name="tiltboard-sync", daemon=True).start()
        if not AUTH_FULL:  # v2.1.0: a password-protected peer will refuse our uncredentialed sync calls
            log.warning("server_1_sync set but pass_full_access empty - "
                        "a password-protected peer board will reject this server's sync")
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:  # port already in use etc. - record it instead of dying silently
        log.error("cannot bind %s:%d: %s", HOST, PORT, e)
        sys.exit(1)
    lan_ip = local_lan_ip()
    log.info("Tiltboard v%s running at http://localhost:%d "
             "(also on network: http://%s:%d) "
             "(default style: %s, themes: %s) "
             "(data folder: %s) "
             "(Ctrl+C to stop, texts persist in chat.txt; board grid "
             "%dx%d, page size %d)",
             VERSION, PORT, lan_ip, PORT, STYLE_NAME,
             ", ".join(available_styles()), DATA_FOLDER, ROWS, COLUMNS, PAGE_SIZE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
