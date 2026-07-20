# dirview — Design for a Lightweight Local Directory Viewer

**Status:** Design only — not yet implemented.

A small web server you run in any local directory that gives you a two-column
browsing UI: directory tree on the left, rendered file on the right, with
first-class markdown rendering, syntax-highlighted code, git status awareness,
inline change indicators with click-through diffs, and live updates as files
change on disk. Catppuccin themed (Latte light / Mocha dark).

```
uv run dirview.py            # serve the current directory at http://127.0.0.1:7440
```

---

## 1. Requirements

1. Two-column layout: directory tree (left), viewed file (right)
2. GOOD markdown rendering (GitHub-flavored)
3. GOOD code rendering (real syntax highlighting, not an afterthought)
4. Git status shown in the tree; filter to changed/new files
5. For changed files, a *subtle* indication of *where* changes are, with
   click-through to a standard diff representation
6. Watches the directory tree and keeps open views up to date

Constraints: as little code as possible — assemble best-in-class existing
solutions rather than building anything from scratch. Catppuccin light + dark.

## 2. Research: what already exists

No single existing tool covers all six requirements; each covers a slice:

| Tool | Tree | Markdown | Code | Git status | Inline diffs | Watch | Verdict |
|---|---|---|---|---|---|---|---|
| [markserv](https://github.com/markserv/markserv) / [mdserver](https://github.com/deepdadou/mdserver) / [gh-markdown-preview](https://github.com/yusukebe/gh-markdown-preview) | dir index only | ✅ | partial | ❌ | ❌ | ✅ | Markdown + live reload, no git at all |
| [difit](https://github.com/yoshiko-pg/difit) | changed files only | ❌ | ✅ | ✅ | ✅ (GitHub-style) | partial | Excellent diff review UI, but not a directory *browser* — no markdown, no unchanged files |
| [diffhub](https://github.com/mblode/diffhub) | changed files only | ❌ | ✅ | ✅ | ✅ | ❌ | Same category as difit |
| `code serve-web` / code-server | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Covers everything but is a full IDE: heavyweight, editing-oriented, not a calm reading view |
| [Ferrite](https://github.com/OlaProeis/Ferrite) | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | Native desktop app (Rust/egui), not a web server |
| klaus / gitweb / Gitea | ✅ | ✅ | ✅ | commit-oriented | commit-oriented | ❌ | Browse *commits*, not the live working tree |

**Conclusion:** the gap is real but narrow — every individual capability is a
solved problem with a clear best-in-class library. The right build is a thin
glue server (~200–300 lines) plus one HTML page that composes those libraries,
not a new app.

## 3. Recommended architecture

**A single-file Python server + a single static HTML page.** All rendering
happens in the browser; the server only serves files, answers git questions,
and pushes change events. Total new code target: **under ~800 lines.**

### Why this shape

- The server stays trivial (static files + 4 JSON endpoints + 1 SSE stream) —
  no template engine, no server-side rendering, no build step.
- The heavy lifting (markdown, highlighting, diff HTML) is done by mature JS
  libraries loaded as ES modules — exactly the "pull from best-in-class"
  requirement.
- Python + `uv` matches this repo's existing tooling. With
  [PEP 723 inline script metadata](https://packaging.python.org/en/latest/specifications/inline-script-metadata/),
  `dirview.py` declares its own dependencies and `uv run dirview.py` just works
  in any directory, no venv setup.

### Component choices (all best-in-class, all boring)

| Concern | Choice | Why |
|---|---|---|
| HTTP server | **Starlette + uvicorn** (Python) | Minimal async framework; SSE and static files out of the box. (FastAPI works too but adds nothing we need.) |
| File watching | **[watchfiles](https://github.com/samuelcolvin/watchfiles)** | Rust `notify`-based, the watcher behind `uvicorn --reload`; `awatch()` gives an async iterator of debounced change batches — feeds SSE directly |
| Git interrogation | **`git` subprocess** (`status --porcelain=v2`, `diff`) | Zero dependencies, always agrees with the user's git; porcelain v2 is a stable machine format. GitPython/pygit2 add weight for no benefit here |
| Markdown | **[markdown-it](https://github.com/markdown-it/markdown-it)** (client-side) + task-list/anchor plugins | The de-facto standard CommonMark+GFM renderer (VS Code uses it). Critically, its token `map` gives **source line ranges per block** — which is what makes requirement 5 work on *rendered* markdown |
| Code highlighting | **[Shiki](https://shiki.style)** | TextMate-grammar highlighting (identical quality to VS Code). Ships **Catppuccin Latte/Frappé/Macchiato/Mocha as bundled themes**, and its [dual-theme mode](https://shiki.style/guide/dual-themes) emits CSS-variable output so light/dark switching is pure CSS |
| Diff rendering | **[diff2html](https://github.com/rtfpessoa/diff2html)** | The standard "GitHub-style diff from raw `git diff` text" library; line-by-line and side-by-side; colors overridable via CSS variables → Catppuccin-able |
| UI reactivity | **Alpine.js** | Already used by this repo's viewer; no build step; a recursive `<template>` renders the tree in ~30 lines |
| Theme | **[@catppuccin/palette](https://github.com/catppuccin/palette)** CSS variables | Official palette as CSS custom properties; Latte = light, Mocha = dark; follow `prefers-color-scheme` with a manual toggle persisted in `localStorage` |

JS libraries load from a CDN (esm.sh / jsdelivr) pinned to exact versions.
*Trade-off:* first load needs internet. If offline use matters, a `--vendor`
flag (or a tiny fetch-on-first-run cache) can mirror the five files locally —
noted as an open question below.

### Layout

```
┌────────────────────────────────────────────────────────────────┐
│ dirview — ~/some/directory        [changed only ⌥] [☾/☀]       │
├──────────────────┬─────────────────────────────────────────────┤
│ ▸ docs           │  README.md                    [Diff] [Raw]  │
│ ▾ scripts        │ ┌─────────────────────────────────────────┐ │
│    gen_efl.py  M │ │                                         │ │
│    gen_ipl.py    │ │   # Rendered markdown / highlighted     │ │
│ ▾ viewer         │ ▌│   code, with a subtle accent bar in    │ │
│    app.js      M │ │ │  the gutter beside changed regions    │ │
│    index.html    │ │                                         │ │
│  README.md     M │ └─────────────────────────────────────────┘ │
│  new_file.md   U │                                             │
└──────────────────┴─────────────────────────────────────────────┘
```

- Tree: collapsible directories, git status letter + Catppuccin color per file
  (M = yellow, A/U = green, D = red, renamed = teal). A header toggle filters
  the tree to changed/untracked files only (requirement 4).
- Right pane header: file path, git status badge, `[Diff]` button (only when
  the file has changes), `[Raw]` toggle for markdown source view.

## 4. Server design

One file, `dirview.py`, with PEP 723 metadata:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["starlette", "uvicorn", "watchfiles"]
# ///
```

CLI: `dirview.py [path] [--port 7440] [--host 127.0.0.1] [--no-open]`.
Binds to localhost only by default. Every request path is resolved and
verified to live under the served root (path-traversal guard). `.git/` is
never listed or served.

### Endpoints

| Endpoint | Returns |
|---|---|
| `GET /` | The static `index.html` |
| `GET /api/tree` | Nested JSON tree of the directory (skipping `.git`), each node annotated with git status from one `git status --porcelain=v2 --untracked-files=all` call; also flags gitignored files so the UI can dim or hide them |
| `GET /api/file?path=` | JSON: text content, detected language (by extension), size, binary flag, git status, and `changed_ranges` — a list of `{start, end, kind}` line ranges parsed from `git diff -U0 -- <path>` hunk headers (`kind` = added/modified; deletions become zero-width markers) |
| `GET /api/diff?path=` | Raw unified `git diff` text for that file (worktree vs HEAD, so staged + unstaged both show; untracked files are diffed against `/dev/null` via `git diff --no-index`) — fed straight to diff2html client-side |
| `GET /raw/<path>` | Raw bytes with correct MIME type — used for images and for relative links/images inside rendered markdown |
| `GET /api/events` | SSE stream of change events |

### Watching → SSE (requirement 6)

A single `watchfiles.awatch(root)` task feeds a broadcast queue consumed by
`/api/events` subscribers. Events are debounced batches (watchfiles does this
natively, ~50ms; we add a 200ms coalesce):

```json
{ "changed": ["scripts/gen_efl.py", "README.md"], "git": true }
```

- Changes under `.git/` (index, HEAD, refs) are **not** forwarded as file
  events; they set `"git": true`, meaning "statuses may have moved" (e.g. the
  user committed or staged something in a terminal).
- Client behavior: on any event, re-fetch `/api/tree` (cheap; the tree JSON for
  a normal project is small). If the currently open file is in `changed`, or
  `git` is true and the open file has status, re-fetch it and re-render **while
  preserving scroll position**. `EventSource` reconnects automatically; on
  reconnect the client does one full refresh to resync.

This is deliberately dumb — no granular cache invalidation, no tree diffing.
At local-directory scale, re-fetching JSON is faster than being clever.

## 5. Frontend design

One `index.html` (Alpine.js + inline module script + inline CSS). No build.

### Markdown rendering (requirement 2)

- markdown-it with GFM affordances: tables, strikethrough, autolinks,
  task-list checkboxes, heading anchors, footnotes.
- Fenced code blocks are highlighted with the **same Shiki instance** used for
  code files — so code inside markdown and standalone code files look
  identical.
- A ~10-line markdown-it core rule copies each block token's `map` (source
  line range) onto the rendered element as `data-lines="12-18"` — the standard
  trick from live-preview editors, reused here for change indicators (§6).
- Relative links between files are intercepted and opened *inside* dirview
  (tree selection follows); relative image sources are rewritten to `/raw/…`.
  External links open in a new tab.
- Optional (v1.1): Mermaid diagram blocks and KaTeX math, each ~5 lines of
  glue with their standard CDN builds. Omitted from v1 to keep the page lean.

### Code rendering (requirement 3)

- Shiki `codeToHtml` with
  `themes: { light: "catppuccin-latte", dark: "catppuccin-mocha" }` —
  dual-theme CSS-variable output, so theme switching never re-highlights.
- Language chosen by extension (Shiki's bundled grammar set covers everything
  in a typical project; unknown extensions fall back to plain text).
- Line numbers via CSS counters in the gutter. Large-file guard: above ~1 MB
  or ~10k lines, skip highlighting and show plain text with a notice.
- Binary files: images render via `/raw/`; other binaries show a metadata
  card (name, size, status) instead of content.

### Git change indication (requirements 4 & 5)

Tree level: status letters + colors as in §3; "changed only" filter collapses
the tree to changed/untracked files (directories auto-expanded).

In-file, the *subtle* indicator is the familiar editor gutter bar, driven by
`changed_ranges` from the server:

- **Code files:** a 3px vertical bar in the gutter beside changed lines —
  Catppuccin green for added, yellow for modified — plus a small red triangle
  marker where lines were deleted. Exactly the VS Code / JetBrains gutter
  convention, so it reads instantly and stays out of the way.
- **Rendered markdown:** any block whose `data-lines` range intersects a
  changed range gets a 3px accent left-border. Subtle, and it survives the
  source→rendered transformation because of the line-map plumbing above.
- **Click-through:** clicking any gutter bar/border, or the `[Diff]` button,
  opens a diff panel for that file: raw `git diff` text from `/api/diff`
  rendered by diff2html, with a line-by-line ⇄ side-by-side toggle, styled via
  diff2html's CSS variables mapped onto Catppuccin colors. Where possible the
  panel scrolls to the hunk containing the clicked line.

### Theming

`@catppuccin/palette` CSS variables define both palettes; a `data-theme`
attribute on `<html>` selects Latte or Mocha (default follows
`prefers-color-scheme`, toggle persisted in `localStorage`). Shiki dual themes
and diff2html variable overrides key off the same attribute, so one attribute
flip restyles everything with zero re-rendering.

## 6. Repository layout & size budget

```
tools/dirview/
  dirview.py        # server: CLI + endpoints + watcher   (~250 lines)
  static/
    index.html      # layout + Alpine templates + CSS     (~250 lines)
    app.js          # tree/view/diff/SSE logic            (~300 lines)
  README.md         # usage
```

If it proves generally useful it can graduate to its own repo /
`uv tool install` package later; nothing in the design ties it to this repo.

## 7. Alternatives considered and rejected

1. **Just run `code serve-web`** — genuinely zero code and covers all six
   requirements, but it's an IDE: heavy process, editing-focused chrome,
   markdown preview is a secondary pane, and the reading experience the
   requirements describe (calm two-pane viewer) isn't what you get. Worth
   knowing it exists as the fallback.
2. **Extend markserv or difit** — each would need the *other half* of the
   feature set bolted on (git for markserv, browsing/markdown for difit),
   inside someone else's architecture. More code than the glue server, less
   control.
3. **Node/Bun server instead of Python** — perfectly viable (chokidar +
   simple-git + the same client libraries), and would allow server-side Shiki.
   Chosen against only because this repo is uv/Python-first and PEP 723 makes
   the Python version a self-contained single file. The frontend is identical
   either way, so switching later is cheap.
4. **Server-side rendering (Python-Markdown + Pygments)** — fewer moving
   parts in the browser, but worse output quality than markdown-it + Shiki,
   no dual-theme CSS trick, and the line-map plumbing for change indicators
   gets harder. The client-side stack is where the best-in-class tools are.

## 8. Open questions

1. **Gitignored files:** hidden by default with a toggle, or always shown but
   dimmed? (Design assumes shown-but-dimmed, toggle to hide.)
2. **Diff baseline:** worktree vs `HEAD` (staged + unstaged together — the
   design default) or a staged/unstaged distinction like `git diff` vs
   `git diff --staged`? A dropdown is cheap but is it wanted?
3. **Offline use:** is CDN-loaded JS acceptable, or should v1 vendor the five
   libraries locally?
4. **Mermaid/KaTeX in v1?** Cheap to add; excluded only for leanness.
5. **Non-git directories:** everything except requirements 4–5 still works;
   the design degrades gracefully (no status column, no diff button). Confirm
   that's the desired behavior rather than an error.

## Sources

- [markserv](https://github.com/markserv/markserv), [mdserver](https://github.com/deepdadou/mdserver), [gh-markdown-preview](https://github.com/yusukebe/gh-markdown-preview), [markdown-proxy](https://github.com/patakuti/markdown-proxy) — markdown + live-reload servers survey
- [difit](https://github.com/yoshiko-pg/difit) ([npm](https://www.npmjs.com/package/difit)), [diffhub](https://github.com/mblode/diffhub) — local GitHub-style diff viewers
- [Ferrite](https://github.com/OlaProeis/Ferrite) — native-app near-miss
- [Shiki dual themes](https://shiki.style/guide/dual-themes), [Shiki bundled themes](https://shiki.style/themes) — Catppuccin Latte/Mocha bundled, CSS-variable dual-theme output
- [diff2html](https://github.com/rtfpessoa/diff2html) ([site](https://diff2html.xyz/)) — diff → HTML rendering
- [watchfiles](https://github.com/samuelcolvin/watchfiles) ([docs](https://watchfiles.helpmanual.io/)) — Rust-backed file watching with async API
- [Catppuccin palette](https://catppuccin.com/palette/), [catppuccin/palette](https://github.com/catppuccin/palette) — official CSS variables
