# Changelog

All notable changes to Tiltboard are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.16.0] - 2026-11-07

### Added
- Upload routing by source: files dragged onto the box or pasted up to **256 MB** keep using the original single-request multipart POST (that method proved reliable even for multi-GB drops — 4 GB verified); larger drops get a hint to attach via the paperclip instead. The paperclip path always uses the chunked protocol: name reservation → ~8 MB slices streamed one after another → commit, with automatic retries on individual steps.
- Live upload progress while the paperclip path is sending: a semi-transparent blue fill grows across the input text box itself (typed text stays readable underneath), and a small label pill inside the box's top-right corner shows `filename - x.x MB of y.y MB`, updating after every slice. The overlay is pinned to the text box's real height, so it never spills past its border even when the Post button stretches the row.
- Emoji grid extended with five more top-used faces/gestures: 😂 🙏 💯 👌 💪.

## [1.15.0] - 2026-11-07

### Added
- Optional page-top header frame: a plain HTML fragment placed next to `app.py` — `header.html` for all themes, or a per-theme override `header.<style>.html` that wins when present. The file is read fresh on every request, so edits show up with just a browser refresh (no server restart); no header file leaves the board unchanged. A ready-to-adapt template with usage comments ships as `header.example.html`.
- Each stylesheet in `styles/` now defines three additive CSS variables — `--tb-ink`, `--tb-accent`, `--tb-muted` (text, accent, faded color of that theme) — so one shared header fragment adapts to all seven themes without per-style files.

### Fixed
- First-time settings box: Name, Columns and Rows were empty because the prefill only ran on the gear-icon open path; the first-visit show now prefills them from config.json defaults (the style dropdown already filled itself once /styles landed).
- Editing Columns or Rows no longer saves + reloads on the first change (number spinners/wheel fired `change`); the box stays open until Enter is pressed or the gear icon closes it, as before.

### Changed
- Search bar restyle: instead of a full-width top strip it now sits at the very top like before, but sized and styled exactly like the composer text box (same padding, font, border and light field color in every theme - each stylesheet's `textarea#message` rule now also styles `input#searchInput`). Its left edge aligns with the composer input text box and its right edge with the right side of the Post button - it spans exactly the composer row. The width is measured from the form itself, so it follows the board columns automatically and re-measures on window resize.
- The page now starts 8px below the viewport edge instead of 32px (all seven themes), leaving exactly the same gap above the top navigation bar as there is under an active search bar. Opening the search bar pushes the whole page down further (top navigation bar, composer and card grid together) by the input's height plus that same 8px gap, so nothing ever sits under it; closing returns to the compact 8px spacing.

## [1.14.0] - 2026-11-07

### Added
- Search bar: a magnifier icon sits left of the settings gear at the top-right corner. Clicking it reveals a search input; clicking again clears the query and hides the bar. With three characters or more typed, the whole chat.txt is filtered live (case-insensitive substring) and every match renders as an ordinary tilt - badges, image previews and the delete cross included - while both pagers stay hidden.
- Search token prefixes: `n:name` / `u:name` matches only that poster's tilts, `f:name` searches attached file names, `c:text` searches message bodies with the name prefix stripped. A bare word searches the whole line; space-separated tokens are AND-ed (`u:John f:my_doc.txt`). Below three characters or without any searchable character the normal board view returns instantly.
- The search UI is styled through the existing theme variables, so all seven themes adapt automatically and no stylesheet needed changes.

## [1.13.0] - 2026-11-07

### Changed
- Uploads keep their original filename instead of the random UUID prefix: a first upload stores as `report.pdf`; when that name is already taken, the new file lands as `report_1.pdf`, then `_2`, … (number inserted before the extension). Exclusive file creation makes simultaneous uploads race-safe. Already stored attachments and every existing chat.txt line are untouched — old tilts still resolve to their original names.

## [1.12.0] - 2026-11-06

### Added
- Real application logging: the app now writes to `tiltboard.log` next to itself (rotating at 1 MB, keeping 3 old copies) in addition to the console. Startup banner, restored-tilts count, every tilt posted/deleted (with a one-line text digest and attachment name), config fallbacks and data-folder problems are recorded with timestamps; HTTP failures (4xx/5xx) are logged as warnings while routine traffic stays quiet.

### Fixed
- A port that is already in use no longer kills the process with a bare traceback before any banner appears - it is now logged (`cannot bind ...`) and the app exits cleanly, which also explains why earlier `> file.log` redirects sometimes left empty log files behind.

### Added
- Standalone Windows x64 executable: the app can now be shipped and run as a single `app.exe` (built with PyInstaller, `--onefile`) without any Python installation on the target machine. This release ships it in the project folder next to config.json.
- Path resolution is frozen-aware (`sys.frozen`): an exe anchors on its own location instead of the temp unpack directory, so it finds config.json, chat.txt and styles/ exactly like `python app.py` does; plain script mode behaves as before.

### Changed
- README Run section now documents both ways to run the server (Python script / standalone exe) and notes that host and port come from config.json only - there is no CLI argument for them.

### Changed
- Redesigned the pending-file indicator: it is now a frameless paperclip (an SVG that inherits its colour, so each theme gives it its own vivid accent - electric cyan in neon, phosphor green in terminal, warm orange in sunset, ...) that pops into view with a bounce when you attach a file and zooms up with a coloured glow while hovered. No more plain white box.

### Added
- Hovering the paperclip reveals a small ✕ right next to it; clicking it removes the pending file before posting (the filename tooltip on hover is unchanged). Text-box size behaviour is untouched - still zero reflow, exactly as in 1.10.1.

## [1.10.1] - 2026-11-06

### Fixed
- Attaching or dropping a file shrank the composer text box to its minimal one-line size: the pending-attachment chip was a full-width flex item (`flex-basis: 100%`) in the non-wrapping composer row, so it squeezed the textarea. The chip is now an absolutely-positioned 📎 icon inside the text box (top-right corner), completely outside the flex flow — the box keeps its exact size and dynamic growth behavior whether or not a file is pending.

### Changed
- The pending-attachment indicator shows only the paperclip icon; the filename appears on hover (native tooltip). Multi-line boxes show it in the top-right, single-line boxes have it at the right side of that one line. Posting still clears the icon and sends exactly one attachment — second attach replaces the first, as before.

## [1.10.0] - 2026-11-06

### Added
- Four new visual themes in `styles/` — the board now ships **seven** complete looks, each a self-contained stylesheet that the settings dropdown and `/styles` endpoint pick up automatically (no code change needed to add more):
  - `midnight.css` — elegant deep-navy dark theme with a soft indigo glow. Tuned over two iterations until clearly distinct from neon: near-black navy radial background (`#0e1733 → #080d1e → #04060f`), 2px indigo borders on inputs/pills/buttons, and cards with a doubled 4px border over a near-black `#0a0f22` fill plus deep shadows.
  - `mono.css` — strict black-and-white Swiss/brutalist look: no color at all.
  - `sunset.css` — warm peachy light theme with a friendly serif voice (Georgia).
  - `terminal.css` — retro CRT phosphor-green on near-black, monospace type, hard edges.
- The settings box's *Style* dropdown now offers all seven themes; switching stays client-side only (browser cookie + stylesheet swap), so no server restart is ever required to change the look. Visitors without a cookie still get `config.json`'s default (`neon`).

## [1.9.1] - 2026-11-06

### Fixed
- Settings dropdown always showed `classic`: the style cookie was stored and applied to the page correctly, but opening the settings box prefilled only the name/rows/columns — the `<select>` kept showing its first option until something set `.value`, which nothing did. The visitor's theme (cookie or server default) is now preselected both when the box opens and once the dropdown options arrive from `/styles`.

## [1.9.0] - 2026-11-06

### Changed
- Pager arrows are now Unicode media glyphs — ⏮ (first), ◀ (previous), ▶ (next), ⏭ (last): one self-contained symbol per control, so every theme renders identical shapes with no CSS-drawn bars or pipes. The jump-five controls are pairs of full-height, half-width triangles (two ◀ / two ▶); each triangle is an inner span squashed to 50% width inside a `.45em` clipping window pulled by `−.1em`, so the pair tiles exactly one triangle wide in any font — the pitch was tuned across several user-checked iterations and stays as-is.
- The six arrows group into two tight triplets — ⏮ ◀◀ ◀ left of the page info, ▶ ▶▶ ⏭ right of it — with a small inner gap inside each triplet and “Page X of Y” centred between them. Server-rendered markup and the no-reload poller build the same structure; the poller's info span now carries the `pager-info` class too, so its styling survives navigation.
- The bottom navigation bar sits 22px below the board: tilt cards rotate up to ~3° around their centre, so a wide bottom row spills visually past the grid box and used to overlap it.

### Added
- Extended pager: the navigation rows above and below the board now carry the full standard set of controls around the "Page X of Y" info — left side ⏮ (first page), ◀◀ (jump five pages back), ◀ (previous); right side ▶ (next), ▶▶ (jump five pages forward), ⏭ (last page). The jump buttons stay active only while a whole five-page step fits toward that boundary; first/last activate in place. Server-rendered fallback and the no-reload JS poller implement identical rules.

## [1.8.0] - 2026-11-06

### Added
- Hover zoom: a tilt card now scales up slightly (1.04x) with a short ease when the mouse hovers it - the exact same event that reveals the delete cross in its corner, so both appear and disappear together. The card keeps its individual tilt rotation while zoomed and is raised above neighbouring cards for the duration of the hover; keyboard focus on the cross triggers the same effect.

## [1.7.1] - 2026-11-06

### Fixed
- Chained escape combinations: a formatted token (`\b`/`\u`/`\i`) now ends where any recognized escape starts, so `\uwork\n\bsee` underlines *work* only, breaks the line, then bolds *see*. Before this fix the word scan stopped at whitespace only, and a following escape was swallowed into the previous token — e.g. john's post rendered `<u>work\n\bLet'…</u>` with the `\n`/`\b` visible as literal text. Both renderers (server-side `format_text()` and the live poller) apply the same rule; a backslash that does not start a recognized escape still stays literal inside its token.

## [1.7.0] - 2026-11-06

### Added
- **Per-user board grid** - the settings box now offers *Rows* and *Columns* next to *Name* and *Style*. Each visitor decides how many cards fill their page (rows × columns, bounds 1–1000 / 1–100); values persist in the browser cookie and beat `config.json`, new visitors start from the config defaults.
- Cards lay out row-major in a CSS grid: newest top-left, filling right along each row, oldest of the page bottom-right. The board's frame grows with the column count; one column stays pixel-identical to before.
- Paging is now client-side at the visitor's own page size: arrows step through pages without any full reload, disabled on first/last page, "Page X of Y" info included. `?page=N` still seeds the starting page.

### Changed
- `config.json`: `max_tilts` renamed to `rows`, new key `columns` (value 1). A legacy `max_tilts` is still read as `rows` so older configs keep working; out-of-range values fall back to defaults with a startup warning.
- `/posts` now answers `{"total": N, "posts": [...]}` — the poller needs the total item count to compute its own page size. Optional per-request grid params (`?rows=&cols=`) let each visitor fetch exactly their chunk; bare calls keep the config-sized default.

### Fixed
- Stale docstring in `persist_text()` claimed chat.txt was trimmed to one page; it grows without bound (true since 1.5.2).

## [1.6.0] - 2026-11-06

### Added
- **Name badge** - a leading `name:` prefix on any tilt (the one the app itself adds when *Name* is not the default) now renders as a small styled box in front of the text; the colon is no longer displayed. The pattern is identical in both renderers: up to 24 characters without whitespace, `:`, `/`, backslash or backtick, followed by ": " or end of line - so URLs such as `http://...` and escape sequences keep rendering exactly as before.
- Each theme styles the badge with its own look (classic: soft blue pill; neon: cyan-glow chip; paper: warm ink stamp).

## [1.5.10] - 2026-11-06

### Changed
- The composer is one line of text again by default (box + emoji/attach icons on a single row). The textarea now auto-sizes: every new line - Shift+Enter or pasted multi-line content - grows the box height to show it, and after posting the page reload puts it back at one line.
- Pasting no longer rewrites real line breaks into visible `\n` escape text inside the box; the text stays exactly as copied while it is being edited. The `/post` safety net still folds every CR/LF into the two-character `\n` escape before chat.txt sees it, so the one-line-per-tilt contract is unchanged.

## [1.5.9] - 2026-11-06

### Changed
- Inline code spans (text between backticks) now honor `\n` as a real line break while keeping everything else literal — multi-line JSON/config snippets posted inside one tilt finally render with proper new lines instead of a run-on string. `\b`, `\i`, `\u` remain unprocessed inside the span, and both the server renderer (`format_text()`) and the live poller apply the same rule.

## [1.5.8] - 2026-11-06

### Added
- Stacked escape prefixes: chaining any mix of `\b`, `\u`, `\i` in front of one word applies them all to that same word, in written order - `\b\itext` renders **bold + italic** (closing tags unwind in reverse). Duplicate letters are ignored (`\b\btext` = single bold); an escape run with no word after it stays literal as before. Server renderer and live poller stay in lockstep.
- Multi-line paste support: pasted CRLF/CR/LF line breaks become the two-character `\n` escape at cursor position, so tilts render with real new lines while chat.txt keeps exactly one line per tilt. A `/post` safety net maps any stray CR/LF to literal `\n`, so a tilt can never break the file format.
- Pasted `<b>…</b>` / `<i>…</i>` / `<u>…</u>` tag pairs are normalized at paste time into stacked per-word prefixes (`<b>Hello world</b>` → `\bHello \bworld`; nested tags stack in written order and close word-by-word automatically). The box shows exactly what will be posted; hand-typed tags stay literal.

### Changed
- The message input is a two-line textarea (`rows="2"`, no resize grip): **Enter posts, Shift+Enter inserts a new line** (the `\n` escape), and the placeholder no longer carries key hints - that guidance lives in `README.md`. Everything else about posting - cookie name prefixing, attachments, emoji picker cursor handling - works unchanged.

### Fixed
- Paste normalization regex matched literal backslash-r sequences instead of real carriage returns (and produced a one-char replacement), so pasted newlines reached the server as raw CR/LF bytes. It now folds CRLF/CR/LF one-to-one into the two-character `\n` escape at cursor position.
- The `/post` safety net folded only CRLF and CR, letting a bare LF through - chat.txt's one-line-per-tilt contract could break on Mac/Linux-style pastes. Pattern extended to `r"\r\n|\r|\n"` in both the multipart and urlencoded branches.
- All three themes still selected the composer as `input#message` after it became a textarea, so the box fell back to default browser sizing (wrong width/height). Selectors now target `textarea#message`; with `resize: none` + `rows="2"` the box is exactly two lines tall and keeps its previous full-width flex layout.
- Paste normalization prefixed **every** word with a stray backslash whenever no `<b>/<i>/<u>` tag was open (plain pastes, or text outside/after tags), mangling e.g. `Hello world this is underline` into `\Hello \word …`. Words now only receive prefixes while a tag stack is active; plain pasted text arrives in the box untouched.
- The stacked-escape rewrite of the live poller appended every `<b>/<i>/<u>` element as an **empty sibling** next to the word instead of nesting around it - `\bok` became `<b></b>ok<b></b>`: escapes were consumed (no backslashes left) but nothing ever landed inside a tag, so bold/italic/underline never appeared visually. Tags are now built as one nested chain with the word text inside (`<b><i>word</i></b>`), byte-for-byte lockstep with `format_text()`.

## [1.5.7] - 2026-11-05

### Added
- Inline text formatting inside tilts, typed directly in the message box (full reference now lives in `README.md`):
  - `\bword`, `\uword`, `\iword` — bold / underline / italicize the next non-space token (`\bbold rest` renders **bold** rest).
  - `` `snippet` `` — inline code span (backtick-delimited, the convention from Discord/Slack/GitHub); everything between the backticks is literal, no escapes are processed inside.
- Both render paths implement the identical scanner: server-side HTML escaping in `format_text()` and a DOM-building walk in the live poller (`textContent` only) — user input can never inject markup. An escape with nothing to format (e.g. a trailing `\b`) stays literal, as does an unmatched backtick.

### Changed
- The message box no longer carries formatting hints in its tooltip or placeholder; all help moved to the manual (`README.md`, new *Formatting* section).

## [1.5.6] - 2026-11-05

### Added
- Multi-line tilts: type the two characters `\n` (backslash + n) anywhere in the text box and it renders as a real line break inside the posted tilt. The sequence is stored literally in chat.txt, so each tilt still occupies exactly one file line.
- Hint for the feature lives on the input itself: hover tooltip plus the placeholder now mention `\n = new line`.

## [1.5.5] - 2026-11-05

### Added
- Emoji selector: a smiley button sits between the text input and the attachment icon. Clicking it opens a built-in grid of ~90 curated emojis (offline, no CDN library or webfont); picking one inserts it at the current cursor position in the input box (selections are replaced), with the caret landing right after the emoji.
- Picker UX: closes on Escape, on clicking outside, or by toggling the button again. Multi-codepoint emoji (e.g. family faces) are inserted as complete units and render correctly inside posted tilts.
- Optional animation: the picker pops in, cells scale on hover, and any tilt containing an emoji gets a one-shot wiggle on appear - both server-rendered pages and posts injected by the live poller get it.

## [1.5.4] - 2026-11-05

### Added
- Hovering over any tilt reveals a small cross in its upper-right corner; clicking it opens a dialog window with Delete/Cancel buttons warning that the source file/picture will be physically deleted from the server if it still exists. On confirmation the matching line is removed from `chat.txt` and the attachment file inside the data folder is deleted, then the page reloads without the tilt.
- New `POST /delete` endpoint: takes `{"text", "attach"}` JSON; returns 200 with `{"ok":true,"removed_file":bool}`, or 400/404/500 for a bad request, no matching line, or I/O error. Matching is by exact text plus stored filename (re-read from chat.txt on every call), so only the one intended tilt disappears even with duplicate texts. File removal reuses the same path-containment guard as `/files/`, and an already-missing file simply reports `removed_file: false`.

## [1.5.3] - 2026-11-05

### Added
- Hovering over a posted picture reveals a download icon in its right-bottom corner (it fades out again when the mouse leaves). Clicking it automatically saves the image under its original filename, using the same `/files/` attachment endpoint that data-file links already use. The icon is themed per stylesheet and works for both server-rendered pages and posts injected by the live poller.

## [1.5.2] - 2026-11-05

### Added
- Pagination over the whole chat.txt history: `max_tilts` (35) now sizes one page of newest tilts; when the file holds more, left/right arrows appear above and below the board to walk between pages (page 1 = newest chunk, "from bottom backwards"). The left arrow is inactive on the first page, the right arrow on the last one. A small "Page N of M" indicator sits between them.
- Page selection via URL: `/?page=N`. Both the rendered HTML and the `/posts` JSON feed used by the 3-second poller honor it, so a visitor browsing an older page is not yanked back to the newest one by live updates.

### Changed
- The in-memory board now keeps EVERY line of chat.txt (oldest first) instead of only the latest `max_tilts`; page slicing happens at render time. History older than one page survives a server restart and remains reachable through the arrows.

## [1.5.1] - 2026-11-05

### Fixed
- Picture-only posts (attachment without any text) from named users were saved anonymously: the name-prefix rule only fired when the input held text. They now carry the bare prefix, e.g. `leo:` next to the image, like every other post.

## [1.5.0] - 2026-11-05

### Added
- Drag & drop file attachment: dragging a picture or data file onto the message box shows a themed "release to attach" highlight (dashed border in classic, neon glow, hand-cut outline in paper) and dropping it attaches the file exactly like pasting does - the chip appears and Post sends text + attachment. The input placeholder now says so too.

## [1.4.1] - 2026-11-05

### Fixed
- Pasted/picked attachments were never actually sent: the JavaScript built a `FormData` from the form but the pending file has no named form control, so it was silently dropped and only the text arrived (`"file is unable to upload"`). The file is now appended explicitly with its original name before posting.
- Posting text + attachment could produce a doubled name prefix (e.g. `leo: leo: haha`): a second submit event on the same attempt re-prefixed the already-prefixed input and fired a duplicate request. The input, chip, file picker and pending-file state are now cleared immediately after building the multipart body.

## [1.4.0] - 2026-11-05

### Added
- `data/` subfolder inside the app directory (created at startup if missing) where attachments are stored under a collision-proof name: `<uuid12>_<original filename>`.
- Server settings moved into `config.json`: `host` (`"0.0.0.0"`) and `port` (`8000`, integer) - the app now starts from config only, no hardcoded address.
- `data_folder` key in `config.json`: empty or missing means `./data`; full paths are honored too (other local drives, UNC network shares like `\\server\share`). Unreachable target fails loudly at startup instead of falling back silently.
- Pasting pictures and files into the message box attaches them to the post: images render as an inline preview inside the tilt, other files become a download link with file icon. The paperclip button next to Post picks any file without pasting (addition beyond the request - trivially removable).
- Attachments persist in `chat.txt` on the same line as their text: a trailing `file:///<absolute path>` token that is hidden from view when rendering; lines without attachments stay plain text and render exactly as before.

### Changed
- Posts are parsed for the attachment tail on startup, so image/file tilts survive server restarts; missing files degrade to plain text rather than breaking the board. Uploads are written with a `uuid` prefix + sanitized original name so downloads keep recognizable filenames.
- Each stylesheet gained themed visuals for previews and download links (soft shadows in classic, neon glow, hand-cut frames in paper) plus the CSS variables the shared attachment UI uses; the neutral layout itself stays in one place inside `app.py`.

### Notes
- `/files/<name>` serves attachments to every visitor on the network with a path-traversal guard (`realpath` containment check) and a quoted `Content-Disposition`, so non-ASCII filenames survive. Multipart parsing uses the stdlib `email` module (no third-party deps). Config values still require a restart.

## [1.3.1] - 2026-11-05

### Changed
- Server binds to `0.0.0.0` instead of `127.0.0.1`, so other devices on the local network can open the board at `http://<your-ip>:8000`. The startup banner prints that LAN address (best-effort detection via a route-only UDP connect — no packets sent).

## [1.3.0] - 2026-11-05

### Added
- Per-visitor settings, stored in a browser cookie (`tiltboard`) — the server never reads cookies:
  - ⚙ icon fixed in the top-right corner; clicking it toggles a settings box at the top of the page.
  - The box shows **Name** (label + text input on the left) and **Style** (label + dropdown of all available themes, from `styles/`, on the right).
  - First visit with no cookie: the box opens automatically prefilled with defaults (`User` / the style from `config.json`). Closing it via the icon saves the values to the cookie and reloads the page.
- Name prefixing: if the saved name is not the default `User`, every new post is prefixed as `<Name>: <text>` (e.g. `Mark: Hello!`) — done client-side before submit; stored text keeps the prefix.

### Changed
- `/style.css` now accepts an optional `?name=<theme>` override, so a visitor's chosen theme applies after reload without touching `config.json`; unknown names get a 404 and no name falls back to the configured default (served as before).
- New `/styles` endpoint returns the list of available theme names (JSON array) feeding the settings dropdown.
- The page embeds the config-default style (`DEFAULT_STYLE`) for prefilling the dropdown; the stylesheet `<link>` gains an id so JS can swap it to `?name=<saved>`. Settings UI styles live in a small inline block (theme-neutral, using CSS variables from each stylesheet); all content styling remains external.

### Notes
- Default name is `User`; selecting defaults erases the cookie. The 3-second poller and max_tilts behavior are unchanged.

## [1.2.0] - 2026-11-05

### Added
- `style` parameter in `config.json` (default: `"classic"`) selects the visual theme at startup.
- External stylesheets in `styles/`, one per theme, each defining its own full look including a distinct card palette:
  - `classic.css` — the original v1.x pastel look on a light gradient background.
  - `neon.css` — dark cyberpunk theme: monospace font, deep purple-black background, cards with glowing neon borders and text glow.
  - `paper.css` — warm notebook-paper aesthetic: cream ruled background, handwritten-style fonts, hand-cut card corners with hard offset shadows.
- `/style.css` endpoint serving the active stylesheet (content type `text/css`).

### Changed
- All styling extracted from the inline `<style>` block in `app.py` into external CSS files; the page now links `/style.css`. Invalid or missing style names fall back to `classic` with a warning.
- Card coloring moved from Python/inline styles (hex palette) to per-theme CSS: posts carry only a color index (`data-c="0..9"`), which each stylesheet maps to its own colors — so switching themes changes every card's appearance. `/posts` JSON now returns the color index instead of a hex value.
- Startup banner reports the active style name (e.g. `style: classic`).

### Notes
- Style is chosen once at server start; change `config.json` and restart to switch themes.

## [1.1.0] - 2026-11-05

### Added
- `chat.txt` — every posted text is appended as one line (newest last); after each write the file is trimmed to the last `max_tilts` lines. Created on first post.
- `config.json` — configuration in JSON (no new dependencies): currently holds `max_tilts: 30`. If missing or invalid, the app falls back to a built-in default of 30 instead of crashing.
- Texts are restored from `chat.txt` at startup, so previously posted texts survive a server restart. Tilt angle and color are re-rolled randomly for each line (only text persists).

### Changed
- In-memory store replaced: unbounded list → bounded `collections.deque(maxlen=max_tilts)`. The oldest tilt is evicted automatically once more than `max_tilts` posts exist, so the board never shows more than `max_tilts` tilts (newest at top, as before).

## [1.0.0] - 2026-11-05

### Added
- Initial release: text box on top with a **Post** button right next to it; posted text appears below the composer as a tilted shape with a random tilt angle and pastel color, newest at the top of the page.
- Posts are held in memory only — closing the server clears everything.
- Client-side polling (every 3 s) so other users see new posts without reloading the page.
