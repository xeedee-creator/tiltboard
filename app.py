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
import sys
import email.policy
from email.parser import BytesParser  # cgi module is gone on Python >= 3.13
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, quote, unquote, urlparse

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


def _init_logging() -> logging.Logger:
    """Persistent app log: tiltboard.log next to the app (1 MB x 3 rotations) plus
    stdout so terminal/nohup captures keep working. Routine traffic stays quiet;
    errors and notable events are always recorded."""
    logger = logging.getLogger("tiltboard")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    try:
        file_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_048_576,
                                           backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:  # a non-writable log must never kill the board
        pass
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    return logger


log = _init_logging()
VERSION = "1.16.0"
DEFAULT_ROWS, DEFAULT_COLUMNS = 35, 1  # board grid when config.json lacks rows/columns
MAX_ROWS, MAX_COLUMNS = 1000, 100      # hard validation bounds for the same keys
NUM_COLORS = 10  # each stylesheet defines its own palette for data-c="0..9"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}


def load_config() -> dict:
    """Read host/port/data_folder/rows/columns/style from config.json with fallbacks.

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
    return {"host": host, "port": port, "data_folder": data_folder,
            "rows": rows, "columns": columns, "style": style}


def ensure_default_config() -> None:
    """A missing config.json is written out with every default so the first
    run leaves an editable file behind next to the program. An existing one -
    even a broken one - is never touched."""
    if os.path.isfile(CONFIG_PATH):
        return
    payload = {"host": "0.0.0.0", "port": 8000, "data_folder": "",
               "rows": DEFAULT_ROWS, "columns": DEFAULT_COLUMNS,
               "style": "classic"}
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
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
HOST, PORT, DATA_FOLDER, ROWS, COLUMNS = (CONFIG["host"], CONFIG["port"],
                                          CONFIG["data_folder"], CONFIG["rows"],
                                          CONFIG["columns"])
PAGE_SIZE = ROWS * COLUMNS  # default page size; visitors may override via cookie

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


def split_line(line: str) -> tuple[str, str | None]:
    """Split a chat.txt line into (display text, attachment path or None)."""
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
    log.info("restored %d tilt%s from chat.txt", len(lines), "" if len(lines) == 1 else "s")
    for line in lines:
        text, path = split_line(line)
        attach = describe_attach(path) if path else None
        POSTS.append(_new_post(text, attach))


def persist_text(text: str, stored_name: str | None = None) -> None:
    """Append a tilt to chat.txt - append-only since v1.5.2.

    The file grows without bound; rows x columns only size each rendered
    page, so history older than one page is never destroyed. With an attachment
    the line becomes "<text> file:///<absolute path>", forward-slashed and
    %20-escaped so split_line() can read it back.
    """
    if stored_name:
        local = os.path.normpath(os.path.join(DATA_FOLDER, stored_name)) \
            .replace("\\", "/")  # E:\data\x.jpg -> E:/data/x.jpg ; UNC keeps //server
        text += f" file://{local.replace(' ', '%20')}"
    with open(CHAT_PATH, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def add_post(text: str, stored_name: str | None = None) -> None:
    persist_text(text, stored_name)
    attach_path = os.path.join(DATA_FOLDER, stored_name) if stored_name else None
    POSTS.append(_new_post(text, describe_attach(attach_path)))
    snippet = text.replace("\n", " ")[:60]  # one-line digest; escapes stay readable
    log.info("tilt posted: %s%s", snippet,
             f" (attachment {stored_name})" if stored_name else "")


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
    return {"url": "/files/" + quote(name), "name": name,
            "is_image": os.path.splitext(name)[1].lower() in IMAGE_EXTS}


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
    safe = re.sub(r"[^\w.\-]+", "_", base).strip("._")[:60] or "file"
    stem, ext = os.path.splitext(safe)
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
    safe = re.sub(r"[^\w.\-]+", "_", base).strip("._")[:60] or "file"
    stem, ext = os.path.splitext(safe)
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

    Returns (fields dict, list of (field_name, filename, payload_bytes)).
    """
    msg = BytesParser(policy=email.policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body)
    fields: dict[str, str] = {}
    files: list[tuple[str, str | None, bytes]] = []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append((str(name), str(filename), payload))
        else:
            fields[str(name)] = (payload.decode("utf-8", "replace"))
    return fields, files


PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tiltboard</title>
<link id="theme" rel="stylesheet" href="/style.css">
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
  <p class="hint">Changes are saved to your browser (cookie) and applied on reload.</p>
</div>

<div id="confirmOverlay" class="hidden" aria-hidden="true">
  <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="delMsg">
    <p id="delMsg"></p>
    <div class="btns"><button id="delYes">Delete</button><button id="delNo">Cancel</button></div>
  </div>
</div>

<div class="wrap">
__HEADER__
__ARROWS_TOP__
  <form class="composer" method="post" action="/post" enctype="multipart/form-data">
    <div class="msg-wrap">
      <textarea id="message" name="message" rows="1" placeholder="Say something... (paste or drop files)" autofocus></textarea>
      <div id="uploadProg" class="hidden"><div id="uploadFill"></div><span id="uploadLabel"></span></div>
      <span id="pendingChip" class="hidden" title="">
        <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true"><path fill="currentColor" d="M16.5 6v11.5a4 4 0 0 1-8 0V5a2.5 2.5 0 0 1 5 0v10.5a1 1 0 0 1-2 0V6H10v9.5a2.5 2.5 0 0 0 5 0V5a4 4 0 0 0-8 0v12.5a5.5 5.5 0 0 0 11 0V6h-1.5z"/></svg>
      </span>
      <button type="button" id="chipRemove" class="hidden" title="Remove attachment">&#10005;</button>
    </div>
    <div id="emojiPicker" class="hidden"></div>
    <button id="emojiBtn" type="button" title="Add an emoji">&#128578;</button>
    <button id="attachBtn" type="button" title="Attach a file">&#128206;</button>
    <input id="filePick" type="file" hidden>
    <button id="post" type="submit">Post</button>
  </form>

  <div class="board" id="board">
__POSTS__
  </div>
__ARROWS_BOTTOM__
</div>

<script>window.DEFAULT_STYLE = "__DEFAULT_STYLE__";
window.DEFAULT_ROWS = __DEFAULT_ROWS__;
window.DEFAULT_COLUMNS = __DEFAULT_COLUMNS__;</script>
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

  const saved = readCookie();
  const name = (saved && saved.get("name")) || DEFAULT_NAME;
  const style = (saved && saved.get("style")) || window.DEFAULT_STYLE;
  const cols = cleanGrid(saved && saved.get("cols"), window.DEFAULT_COLUMNS, 100);
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
    if (name !== DEFAULT_NAME && (t || pendingFile)) msg.value = t ? name + ": " + msg.value : name + ":";
  });

  if (!saved) {  // first visit: show the settings box so choices can be made
    nameInput.value = name;       // prefill like the icon-open path does - the box is
    colsInput.value = cols;       // shown without a click, so its inputs would stay empty
    rowsInput.value = rows;       // (the style dropdown prefills itself once /styles lands)
    box.classList.remove("hidden");
    box.setAttribute("aria-hidden", "false");
  }

  // Attachments: a pending file is kept in memory until posted (FormData).
  const form = document.querySelector(".composer");
  const message = document.getElementById("message");
  const chip = document.getElementById("pendingChip");
  const chipRemove = document.getElementById("chipRemove");
  const pick = document.getElementById("filePick");
  let pendingFile = null, pendingSource = "clip";   // v1.16.2: where the file came from (drop/paste/clip)
  const DROP_MAX = 256 * 1024 * 1024;     // v1.16.2: drops/pastes stay on the direct path up to this, then suggest the clip icon
  const CHUNK_SIZE = 8 * 1024 * 1024;     // slice size for chunked uploads (paperclip always chunks)

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

  function showPending(f) {
    pendingFile = f || null;
    if (f) {                                    // v1.10.2: SVG clip inherits the theme color; pop-in animation replays on every attach
      chip.title = f.name;
      chip.classList.remove("hidden");
      void chip.offsetWidth;                    // restart @keyframes chipPop so each new file gets the attention flash
      chipRemove.classList.remove("hidden");    // tiny ✕ fades in beside it (CSS sibling rule); clicking removes without posting
    }
    else { chip.title = ""; chip.classList.add("hidden"); chipRemove.classList.add("hidden"); }  // v1.10.1: icon only, name on hover
  }

  chipRemove.addEventListener("click", (e) => { e.preventDefault(); pick.value = ""; showPending(null); message.focus(); });

  document.getElementById("attachBtn").addEventListener("click", () => pick.click());
  pick.addEventListener("change", () => { pendingSource = "clip"; showPending(pick.files[0] || null); });
  message.addEventListener("paste", (e) => {  // pasted pictures/files -> attachment
    const items = [...(e.clipboardData && e.clipboardData.items || [])];
    for (const item of items) if (item.kind === "file") {
      pendingSource = "paste";
      showPending(item.getAsFile());
      e.preventDefault();
      return;
    }
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
  const normalizeTags = (s) => {  // <b>/<i>/<u> pairs -> stacked per-word prefixes, written order
    let out = "", stack = [], m;
    while ((m = s.match(/^(.*?)(?:<\/(b|i|u)>|<(b|i|u)>)/is))) {
      const plainPart = processPlain(m[1]);  // segment before the tag
      if (m[2]) stack.pop();                 // closing: prefixes shrink with it
      else if (!stack.includes(m[3])) stack.push(m[3]);  // opening, duplicates ignored like format_text()
      out += plainPart;
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
        res += /^\s/.test(w[1]) || !stack.length ? w[1] : "\\" + stack.join("") + escapeWord(w[1]);
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
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (f) { pendingSource = "drop"; showPending(f); }
  });

  form.addEventListener("submit", (e) => {
    const msg = document.getElementById("message");
    if (!msg.value.trim() && !pendingFile) { e.preventDefault(); return; }
    e.preventDefault();                     // v1.16.2: drops/pastes stay direct up to DROP_MAX, the paperclip always chunks
    const file = pendingFile;
    const text = msg.value.trim();
    const source = pendingSource || "clip";  // v1.16.2: where the file came from decides the upload path
    if (!file) {                            // v1.16.x: a plain text post never touches the upload paths
      const fd = new FormData(form);
      fd.set("message", text);
      fetch("/post", { method: "POST", body: fd }).then((r) => location.reload()).catch(fail);
      return;
    }
    function fail(detail) { hideUpload(); showPending(file); pick.value = ""; msg.value = text; alert("Upload failed - your post was restored." + (detail ? "\n(" + detail + ")" : "")); }
    if (source !== "clip" && file.size > DROP_MAX) {  // v1.16.2: oversized drop/paste -> suggest the clip icon, keep everything untouched
      msg.value = text;
      alert(file.name + " is over 256 MB - too big for a direct drop.\nPlease attach it with the paperclip icon instead (it uploads in pieces).");
      e.preventDefault(); return;
    }
    // The pending file is appended to the multipart body (it has no form control
    // of its own). Input + chip are cleared right away so a second submit event
    // on the same attempt cannot re-prefix or double-post.
    pendingFile = null; showPending(null); pick.value = "";
    msg.value = "";
    if (source === "clip") {                // v1.16.2: paperclip always chunks - retry-safe for any size
      let stored = null;                    // kept in outer scope so the catch below can abort it by name
      const postJson = (path, payload) => fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }).then((r) => r.json());
      // v1.16.1: one flaky request no longer kills the whole transfer - every step
      // is retried (3 tries, 2 s / 4 s apart); chunk data never changes on retry.
      const withRetry = async (label, task) => {
        for (let attempt = 1; ; attempt++) {
          try { return await task(); }
          catch (err) { if (attempt > 3) throw new Error(label + " failed after 4 tries: " + err.message); await new Promise((w) => setTimeout(w, 2000 * attempt)); }
        }
      };
      withRetry("upload/init", () => postJson("/upload/init", { name: file.name || "pasted" }))
        .then(async (res) => {
          if (!res.ok || !res.stored) throw new Error(res.error || "could not reserve a file name");
          stored = res.stored;
          showUpload(file.name || "pasted", 0, file.size);   // v1.16.x: overlay appears as soon as the transfer starts
          for (let off = 0; off < file.size; off += CHUNK_SIZE) {   // ~8 MB slices; the server streams each one to disk in 1 MB reads
            await withRetry("chunk " + Math.round(off / CHUNK_SIZE + 1), () =>
              fetch("/upload/chunk", { method: "POST", headers: { "X-Stored-Name": stored, "X-Chunk-Offset": String(off) }, body: file.slice(off, Math.min(off + CHUNK_SIZE, file.size)) })
                .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); }));
            showUpload(file.name || "pasted", off + CHUNK_SIZE, file.size);   // v1.16.x: advance the bar after each successful slice
          }
          return withRetry("commit", () => postJson("/post", { message: text, attach_stored: stored }));  // commit = same line format as a normal attachment post
        })
        .then((r) => location.reload())
        .catch((err) => {
          fail(err && err.message);         // best-effort cleanup of the partial file (fire and forget)
          if (!stored) return;
          fetch("/upload/abort", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stored: stored }) }).catch(function () {});
        });
    } else {
      const fd = new FormData(form);
      fd.set("message", text);
      fd.append("attachment", file, file.name || "pasted");
      fetch("/post", { method: "POST", body: fd }).then((r) => location.reload()).catch(fail);
    }
  });
})();
</script>
<script>
// Live update: poll /posts every 3 seconds and refresh only the board,
// so other people's posts appear without a manual page reload.
(function () {
  const board = document.getElementById("board");
  let lastSig = "";

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
      while (i < post.text.length) {
        const ch = post.text[i];
        if (ch === "\\" && "nubi".includes(post.text[i + 1] || "")) {
          const esc = post.text[++i];
          if (esc === "n") { span.appendChild(document.createElement("br")); i++; continue; }
          // v1.5.8: stacked escapes - every chained \b/\u/\i prefix applies to the same word;
          // opens in written order, closes in reverse. Lockstep with format_text().
          const fmts = [esc];
          let j = i + 1;
          while (j < post.text.length && post.text[j] === "\\"
                 && "bui".includes(post.text[j + 1] || "")) {
            if (!fmts.includes(post.text[j + 1])) fmts.push(post.text[j + 1]);
            j += 2;
          }
          let k = j;  // v1.7.1: a token ends where a recognized escape starts, so chained
                      // escapes each fire instead of being swallowed into one word - lockstep
                      while (k < post.text.length && !/\s/.test(post.text[k])
                 && !(post.text[k] === "\\" && "nubi".includes(post.text[k + 1] || ""))) k++;
          if (k > j) {
            // v1.5.8 fix: nest the tags around the word (b> i> text), lockstep with format_text()
            let cur = span;
            for (const t of fmts) { const el = document.createElement(t); cur.appendChild(el); cur = el; }
            cur.appendChild(document.createTextNode(post.text.slice(j, k)));  // textContent: always safe
            i = k;
          } else { span.appendChild(document.createTextNode(post.text.slice(i - 1, j))); i = j; }
        } else if (ch === "`") {
          const end = post.text.indexOf("`", i + 1);
          if (end !== -1) {
            const el = document.createElement("code");
            // v1.5.9: \n still breaks lines inside code spans; all else literal.
            let buf = "";
            for (let t = i + 1; t < end;) {
              if (post.text[t] === "\\" && post.text[t + 1] === "n") {
                if (buf) { el.appendChild(document.createTextNode(buf)); buf = ""; }
                el.appendChild(document.createElement("br"));
                t += 2;
              } else { buf += post.text[t]; t++; }
            }
            if (buf) el.appendChild(document.createTextNode(buf));
            span.appendChild(el);
            i = end + 1;
          } else { span.appendChild(document.createTextNode(ch)); i++; }
        } else if (ch === "\n") { span.appendChild(document.createElement("br")); i++; }
        else { span.appendChild(document.createTextNode(ch)); i++; }  // text nodes only: no injection
      }
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
        } else {                                       // data file -> download link
          const a = document.createElement("a");
          a.href = post.attach.url;
          a.className = "download";
          a.textContent = "\u{1F4C4} " + post.attach.name;
          div.appendChild(span);
          div.appendChild(a);
        }
      } else div.appendChild(span);
      // v1.5.4: same delete cross + identity as the server-rendered cards
      const del = document.createElement("button");
      del.className = "del";
      del.title = "Delete this tilt";
      del.textContent = "\u2715";  // U+2715, same glyph as &#10005; in the server HTML
      div.dataset.text = post.text;
      div.dataset.attach = post.attach ? post.attach.name : "";
      div.appendChild(del);
      frag.appendChild(div);
    }
    board.replaceChildren(frag);
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
        mk(page > 1 ? "/?page=" + (page - 1) : null, "\u25C0", page <= 1));
      const rightGroup = document.createElement("span");
      rightGroup.className = "pager-group";
      rightGroup.append(
        mk(page < totalPages ? "/?page=" + (page + 1) : null, "\u25B6", page >= totalPages),
        mk(page + 5 <= totalPages ? "/?page=" + (page + 5) : null, '<span class="half"><span>\u25B6</span></span><span class="half"><span>\u25B6</span></span>', !(page + 5 <= totalPages)),
        mk(page < totalPages ? "/?page=" + totalPages : null, '<span class="g">\u23ED</span>', page >= totalPages, "pg-end"));
      p.replaceChildren(leftGroup, info, rightGroup)
    }
  }

  async function poll() {
    if (window.tiltSearchActive && window.tiltSearchActive()) return;  // v1.14.0: filter owns the board
    try {
      const res = await fetch(postsUrl(), { cache: "no-store" });
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
    input.style.left = r.left + "px";
    input.style.width = Math.max(200, r.width) + "px";
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
      .then((res) => { if (res && res.ok) location.reload(); else alert("Delete failed: " + ((res && res.error) || "unknown error")); })
      .catch(() => alert("Delete failed - could not reach the server."));
  });

  // One listener for every card on the board, live-polled or server-rendered.
  document.getElementById("board").addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".tilt .del");
    if (btn) openDialog(btn.closest(".tilt"));
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

  // Curated grid (~90 emoji). \u{...} escapes keep the source free of raw emoji.
  const EMOJIS = [
    "\u{1F600}","\u{1F602}","\u{1F603}","\u{1F604}","\u{1F605}","\u{1F606}","\u{1F923}","\u{1F609}",
    "\u{1F60A}","\u{1F60B}","\u{1F642}","\u{1F60C}","\u{1F917}","\u{1F920}","\u{1F633}",
    "\u{1F970}","\u{1F625}","\u{1F62D}","\u{1F61E}","\u{1F61C}","\u{1F628}","\u{1F60F}",
    "\u{1F914}","\u{1F91D}","\u{1F924}","\u{1F634}","\u{1F629}","\u{1F631}","\u{1F97A}",
    "\u{1F60D}","\u{1F61A}","\u{1F61B}","\u{1F622}","\u{1F62E}","\u{1F975}","\u{1F644}",
    "\u{1F90A}","\u{1F90D}","\u{1F636}","\u{1F648}","\u{1F64B}","\u{2764}","\u{1F495}",
    "\u{1F49A}","\u{1F49D}","\u{270C}","\u{1F596}","\u{1F44C}","\u{1F44D}","\u{1F44E}","\u{1F91F}",
    "\u{1F918}","\u{270B}","\u{1F64F}","\u{1F4AA}","\u{1F4AF}","\u{1FAF5}","\u{1F91C}","\u{1F64C}","\u{1F389}","\u{1F38A}",
    "\u{2728}","\u{1F4AC}","\u{1F525}","\u{1F60E}","\u{1F913}","\u{1F9D0}","\u{1F928}",
    "\u{1F431}","\u{1F432}","\u{1F98A}","\u{1F436}","\u{1F43B}","\u{1F99B}","\u{1F98E}",
    "\u{1F42D}","\u{1F407}","\u{1F986}","\u{1F9A1}","\u{1F43E}","\u{1F43F}","\u{1F427}",
    "\u{1F95D}","\u{1F98B}","\u{1F430}","\u{1F41A}","\u{1F43C}","\u{2615}","\u{1F37D}",
    "\u{1F354}","\u{1F951}","\u{1F95A}","\u{1F36B}","\u{274C}",
    "\u{2705}","\u{274E}","\u{1F382}","\u{1F9E8}","\u{26BD}","\u{1F3C0}"
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
<style id="settingsStyles">
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
  width: 300px; box-sizing: border-box; outline: none; }
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
textarea#message { width: 100%; box-sizing: border-box; }
/* v1.10.2: frameless paperclip - an absolutely-positioned overlay in the text
   box's top-right corner (outside the composer flex flow, so it can never shrink
   or reflow the textarea). The SVG inherits currentColor, and each theme paints a
   vivid accent for it in its own stylesheet; hover zooms + glows with that color,
   attaching pops it in, and a tiny ✕ fades in beside it on hover to remove the file */
#pendingChip { position: absolute; top: 6px; right: 8px; z-index: 2; display: inline-flex;
  align-items: center; justify-content: center; width: 24px; height: 24px; cursor: default;
  color: var(--line, #9aa7b5);
  animation: chipPop .3s cubic-bezier(.34,1.56,.64,1); transition: transform .18s ease-out, filter .18s ease-out; }
#pendingChip:hover { transform: scale(1.25) rotate(-8deg);
  filter: drop-shadow(0 0 5px currentColor) drop-shadow(0 0 12px currentColor); transition-delay: .4s; }
@keyframes chipPop { from { opacity: 0; transform: scale(.3); } to { opacity: 1; transform: none; } }
/* the ✕ sits just left of the clip and only becomes visible while hovering it or the clip */
#chipRemove { position: absolute; top: 7px; right: 34px; z-index: 2; width: 18px; height: 18px;
  padding: 0; border: none; border-radius: 50%; background: transparent; color: inherit;
  font-size: 12px; line-height: 1; cursor: pointer; opacity: 0; transition: opacity .15s, transform .15s; }
#pendingChip:hover ~ #chipRemove, #chipRemove:hover { opacity: .9; }
#chipRemove:hover { transform: scale(1.3); }
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
.pager-group { display: inline-flex; align-items: center; gap: 2em; }
.arrow { box-sizing: border-box; height: 42px; line-height: 40px; font-family: "Segoe UI Symbol", "Cascadia Code", "Noto Sans Symbols 2", monospace; }
/* v1.9.x: the first/last-page media glyphs (U+23EE / U+23ED) are inked a hair
   lower and smaller than the geometric triangles by the symbol font - nudge the
   two arrows up and stretch only their glyph span vertically (kept out of the
   anchor so the themes' hover transforms stay intact) */
.arrow.pg-end { position: relative; top: -4px; }
.arrow.pg-end .g { display: inline-block; transform: scaleY(1.3); }
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
.arrow .half > span { display: inline-block; transform: scaleX(.5); transform-origin: left center; }
/* tilt hover zoom (v1.8.0) - same :hover event as the delete cross; keeps each card's rotation */
.tilt:hover, .tilt:focus-within { transform: rotate(var(--tilt)) scale(1.04); z-index: 3; }
/* emoji picker (v1.5.5) - structure here, neutral colors with theme-var fallbacks */
.composer { position: relative; }
button#emojiBtn { flex: none; padding: 8px 10px; border-radius: 8px; cursor: pointer; font-size: 16px;
  border: 1px solid var(--line, #ccc); background: var(--field, #fff); color: inherit; }
button#emojiBtn:hover { transform: scale(1.12) rotate(-8deg); transition: transform .15s; }
#emojiPicker { position: absolute; left: 0; top: calc(100% + 8px); z-index: 40; width: min(92vw, 360px);
  max-height: 280px; overflow-y: auto; padding: 10px; border-radius: 12px;
  background: var(--panel, #fff); color: var(--ink, #333); border: 1px solid var(--line, #ccc);
  box-shadow: 0 8px 24px rgba(0,0,0,.3); display: grid; gap: 2px;
  grid-template-columns: repeat(auto-fill, minmax(36px, 1fr)); }
#emojiPicker button { font-size: 20px; line-height: 1; padding: 5px 2px; border: none; background: transparent;
  cursor: pointer; border-radius: 8px; }
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
#delYes { background: #c2503f; border-color: #a83e2f; color: #fff; }
#delNo:hover { opacity: .75; }
</style>
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
        + _nav_arrow(f"/?page={current - 1}", "&#9664;", current > 1) + '</span>')
    right = (
        '<span class="pager-group">'
        + _nav_arrow(f"/?page={current + 1}", "&#9654;", current < total)
        + _nav_arrow(f"/?page={current + 5}", '<span class="half"><span>&#9654;</span></span><span class="half"><span>&#9654;</span></span>', current + 5 <= total)
        + _nav_arrow(f"/?page={total}", '<span class="g">&#9197;</span>', current < total, "pg-end") + '</span>')
    return f'<div class="pager">{left}<span class="pager-info">Page {current} of {total}</span>{right}</div>'


# v1.6.0: the "name:" prefix on a chat.txt line becomes a badge; the colon itself
# is not rendered. A name = up to 24 chars, no whitespace / ':' / '/' / '\\' / backtick,
# followed by ": " or end of line (so URLs like http://... stay untouched).
NAME_RE = re.compile(r"^([^:/\\\n`]{1,24}):(?: |$)")


def format_text(raw: str) -> str:
    """Safe HTML for one tilt's stored text. The escape set is documented in
    readme.md - every character not consumed by an escape or a code span is
    html.escape()d, so user input can never inject markup:
      \\n        new line          `code`  inline code span, literal inside
      \\bword    bold the next non-space token (\\u/\\i likewise)
      stacked    prefixes apply together in written order - \\b\\itext becomes <b><i>text</i></b>
                 with closing tags unwound in reverse; duplicate letters are ignored. An escape
                 run without a word after it stays literal (v1.5.8).
      A formatted token ends where any recognized escape starts, so \\uwork\\n\\bsee underlines
                 work only, breaks the line, then bolds see - chained escapes never get
                 swallowed into the previous word (v1.7.1).
      name:     leading "name:" prefix renders as a badge; the colon disappears
                 (the app adds this prefix itself - see README)
    """
    out = []
    m = NAME_RE.match(raw)          # v1.6.0: name badge, colon hidden
    if m:
        out.append(f'<span class="user">{html.escape(m.group(1))}</span>')
        i = m.end()                 # past name + ':' and one space (or end of string)
    else:
        i = 0
    n = len(raw)
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
            while k < n and not raw[k].isspace() \
                    and not (raw[k] == "\\" and k + 1 < n and raw[k + 1] in "nubi"):
                k += 1
            if k > j:  # a word really follows the escape(s)
                out.append("".join(f"<{t}>" for t in fmts))
                out.append(html.escape(raw[j:k]))
                out.append("".join(f"</{t}>" for t in reversed(fmts)))
                i = k
            else:      # no word - keep the sequence literal, escaped
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
        elif ch == "\n":   # real newline kept as a safety no-op since v1.5.6
            out.append("<br>")
            i += 1
        else:
            out.append(html.escape(ch))
            i += 1
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
            else:
                extra = (f'<a class="download" href="{html.escape(attach["url"])}">'
                         f'\U0001F4C4 {html.escape(attach["name"])}</a>')
        # the button's identity rides on data-* so one click handler can serve
        # every card - quote=True keeps quotes/newlines inside the attribute
        attach_name = html.escape(attach["name"], quote=True) if attach else ""
        cards.append(f'<div class="tilt{emoji_cls}" data-c="{post["color"]}" style="--tilt: {tilt} "'
                     f'data-text="{html.escape(post["text"], quote=True)} "'
                     f'data-attach="{attach_name}">{delete_btn}'
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


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes = b"", headers=None) -> None:
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

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
        if path in ("/", "/index.html"):
            query_page = parse_qs(parsed.query).get("page", ["1"])[0]
            try:  # ?page=N picks the page to show; garbage falls back to page 1
                requested = min(max(int(query_page), 1), total_pages())
            except ValueError:
                requested = 1
            pager = render_pager(requested, total_pages())
            page = PAGE.replace("__POSTS__", render_posts(requested))
            page = (page.replace("__ARROWS_TOP__", pager).replace("__ARROWS_BOTTOM__", pager))
            page = (page.replace("__HEADER__", _header_html())           # optional top frame
                    .replace("__DEFAULT_STYLE__", STYLE_NAME)      # dropdown default
                    .replace("__DEFAULT_ROWS__", str(ROWS))
                    .replace("__DEFAULT_COLUMNS__", str(COLUMNS)))
            body = page.encode("utf-8")
            self._send(200, body, {"Content-Type": "text/html; charset=utf-8"})
        elif path == "/style.css":
            name_param = parse_qs(parsed.query).get("name", [None])[0]  # per-visitor theme
            body, ok = self._css_for(name_param)
            if not ok:  # unknown theme requested explicitly -> plain 404
                self._send(404, b"")
                return
            self._send(200, body, {"Content-Type": "text/css", "Cache-Control": "no-store"})
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
            with open(real, "rb") as f:
                body = f.read()
            quoted = name.replace("\\", "\\\\").replace('"', '\\"')  # non-ASCII names survive too
            self._send(200, body, {"Content-Type": ctype,
                                   "Content-Disposition": f'attachment; filename="{quoted}"'})
        else:
            self._send(404, b"Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/delete":
            self._handle_delete()
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
            # The chunked client parses this reply as JSON. A 302 would make fetch() follow
            # it to the HTML board page and crash r.json() - so answer with plain JSON here.
            self._send(200, json.dumps({"ok": True}).encode(), {"Content-Type": "application/json"})
            return
        else:  # plain text post - the form's default urlencoded path
            message = re.sub(r"\r\n|\r|\n", "\\\\n", parse_qs(body.decode("utf-8")).get("message", [""])[0].strip())  # safety net: any real newline becomes a literal \n escape
            stored_name = None
        if message or stored_name:
            add_post(message, stored_name)
        self._send(302, headers={"Location": "/"})

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
        """POST /upload/chunk, header X-Stored-Name (+ X-Chunk-Offset) - write one chunk to disk."""
        real = _stored_path(self.headers.get("X-Stored-Name"))
        if not real:  # unknown or escaping name -> nothing to append to
            self._send(404, json.dumps({"ok": False, "error": "unknown upload"}).encode())
            return
        try:
            remaining = int(self.headers.get("Content-Length", 0))
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
        self._send(200, json.dumps({"ok": True}).encode())

    def _upload_abort(self):
        """POST /upload/abort {stored} - best-effort removal of a partial upload."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, json.dumps({"ok": False, "error": "bad request"}).encode())
            return
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
        removed_file = False
        try:
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
        log.info("tilt deleted: %s%s", snippet,
                 f" (source file {attach_name} removed)" if removed_file else "")
        self._send(200, json.dumps({"ok": True, "removed_file": removed_file}).encode(),
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
        if code is not None and code >= 400:
            log.warning("request: %s", line)   # failures always visible
        else:
            log.debug("request: %s", line)     # routine traffic stays quiet


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
        return 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        t, path = split_line(line)
        if t != text:
            continue
        if attach_name is None or (path and os.path.basename(path) == attach_name):
            return i + 1
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


def main():
    restore_posts()
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
