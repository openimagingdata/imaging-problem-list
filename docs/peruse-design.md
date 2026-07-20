# peruse — Design for a Lightweight Local Directory Viewer

**Status:** Design only — not yet implemented. Will live in its own repository;
this copy is parked here while the design is being discussed.

A small web server you run in any local directory that gives you a two-column
browsing UI: directory tree on the left, rendered file on the right, with
first-class markdown rendering, syntax-highlighted code, git status awareness,
inline per-hunk diffs, and live updates as files change on disk. Catppuccin
themed (Latte light / Mocha dark).

```
npx @talkasab/peruse   # serve the current directory at http://127.0.0.1:7440
```

(The bare npm name `peruse` is squatted by an abandoned 2017 package, so the
package publishes under a scope; the installed command is still `peruse`.
Until it's published, `npx github:talkasab/peruse` works straight from the
repo.)

---

## 1. Requirements

1. Two-column layout: directory tree (left), viewed file (right)
2. GOOD markdown rendering (GitHub-flavored)
3. GOOD code rendering (real syntax highlighting, not an afterthought)
4. Git status shown in the tree; filter to changed/new files
5. For changed files, a *subtle* indication of *where* changes are; clicking an
   individual change expands that **individual hunk's diff inline, in place** —
   never a whole-page diff view
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
glue server plus one page that composes those libraries, not a new app.

## 3. Recommended architecture

**A small Node.js package: a ~5-route server plus one static page.** All
rendering happens in the browser; the server only serves files, answers git
questions, and pushes change events. Total new code target: **under ~900
lines**, distributed as an npm package so `npx @talkasab/peruse` works anywhere with no
setup.

### Why Node (and not Python)

An earlier draft proposed a Python/Starlette single-file server, anchored on
the host repo's uv tooling. For a standalone tool the trade-offs point the
other way:

- **Every rendering dependency is npm-native.** markdown-it, Shiki, diff2html,
  Alpine — the best-in-class stack *is* the JS ecosystem. With a Node package
  they're normal pinned dependencies, bundled at publish time. The Python
  version could only reach them via CDN at runtime (online requirement,
  version drift) or awkward vendoring.
- **Distribution:** `npx <package>` is the established idiom for exactly this
  kind of tool (difit, serve, vite preview…). "First install uv" is a real
  barrier for anyone else who wants it.
- **One language** across server and client; the server half is trivial in
  either language anyway (the watcher, git subprocess, and SSE all have
  equally good Node equivalents).

Bun would allow a single compiled binary and is noted as a future option
(§7); Node ≥ 20 is chosen for ubiquity.

### Component choices (all best-in-class, all boring)

| Concern | Choice | Why |
|---|---|---|
| HTTP server | **[Hono](https://hono.dev)** + `@hono/node-server` | Tiny, modern router with built-in static file serving and an SSE streaming helper; the whole server stays one small file |
| File watching | **[chokidar](https://github.com/paulmillr/chokidar)** | The de-facto standard Node watcher (powers Vite et al.); handles recursive watching, debouncing quirks, and platform differences |
| Git interrogation | **`git` subprocess** (`status --porcelain=v2`, `diff`) | Zero dependencies, always agrees with the user's git; porcelain v2 is a stable machine format. simple-git/nodegit add weight for no benefit |
| Markdown | **[markdown-it](https://github.com/markdown-it/markdown-it)** + task-list/anchor plugins | The de-facto CommonMark+GFM renderer (VS Code uses it). Critically, its token `map` gives **source line ranges per block** — which is what makes requirement 5 work on *rendered* markdown |
| Code highlighting | **[Shiki](https://shiki.style)** | TextMate-grammar highlighting (identical quality to VS Code). Ships **Catppuccin Latte/Frappé/Macchiato/Mocha as bundled themes**, and its [dual-theme mode](https://shiki.style/guide/dual-themes) emits CSS-variable output so light/dark switching is pure CSS |
| Hunk diff rendering | **[diff2html](https://github.com/rtfpessoa/diff2html)** (per-hunk) | The standard "GitHub-style diff from raw `git diff` text" library; we feed it one hunk at a time (§5); colors overridable via CSS variables → Catppuccin-able |
| UI reactivity | **Alpine.js** | No framework build; a recursive `<template>` renders the tree in ~30 lines. (If the inline-hunk DOM juggling outgrows it, preact+htm is the fallback — still buildless) |
| Client bundling | **esbuild**, one-shot at publish | End users never build; `npx` ships prebuilt assets. Solves offline use — no CDN anywhere |
| Theme | **[@catppuccin/palette](https://github.com/catppuccin/palette)** CSS variables | Official palette as CSS custom properties; Latte = light, Mocha = dark; follow `prefers-color-scheme` with a manual toggle persisted in `localStorage` |

### Layout

```
┌────────────────────────────────────────────────────────────────┐
│ peruse — ~/some/directory        [changed only ⌥] [☾/☀]       │
├──────────────────┬─────────────────────────────────────────────┤
│ ▸ docs           │  scripts/gen_efl.py            M   [Raw]    │
│ ▾ scripts        │ ┌─────────────────────────────────────────┐ │
│    gen_efl.py  M │ │  12  def load_sheet(path):              │ │
│    gen_ipl.py    │ │▌ 13      wb = openpyxl.load_workbook(   │ │
│ ▾ viewer         │ │▌ 14      sheet = wb.active              │ │
│    app.js      M │ │  15      return sheet                   │ │
│    index.html    │ │      ⌄ (clicked — hunk expands inline)  │ │
│  README.md     M │ │ ┌─────────────────────────────────────┐ │ │
│  new_file.md   U │ │ │ - 13  wb = load_workbook(path, ro)  │ │ │
│                  │ │ │ + 13  wb = openpyxl.load_workbook(  │ │ │
│                  │ │ │ + 14  sheet = wb.active             │ │ │
│                  │ │ └─────────────────────────────────────┘ │ │
│                  │ └─────────────────────────────────────────┘ │
└──────────────────┴─────────────────────────────────────────────┘
```

- Tree: collapsible directories, git status letter + Catppuccin color per file
  (M = yellow, A/U = green, D = red, renamed = teal). A header toggle filters
  the tree to changed/untracked files only (requirement 4).
- Right pane header: file path, git status badge, `[Raw]` toggle for markdown
  source view.

## 4. Server design

`peruse [path] [--port 7440] [--host 127.0.0.1] [--no-open]`.
Binds to localhost only by default. Every request path is resolved and
verified to live under the served root (path-traversal guard). `.git/` is
never listed or served.

### Endpoints

| Endpoint | Returns |
|---|---|
| `GET /` | The prebuilt static page |
| `GET /api/tree` | Nested JSON tree of the directory (skipping `.git`), each node annotated with git status from one `git status --porcelain=v2 --untracked-files=all` call; also flags gitignored files so the UI can dim or hide them |
| `GET /api/file?path=` | JSON: text content, detected language (by extension), size, binary flag, git status, and `hunks` (below) |
| `GET /raw/<path>` | Raw bytes with correct MIME type — used for images and for relative links/images inside rendered markdown |
| `GET /api/events` | SSE stream of change events |

### Hunk data (requirement 5)

`/api/file` runs `git diff --no-color -U3 -- <path>` (worktree vs `HEAD`, so
staged and unstaged changes both show; untracked files are diffed against
empty via `--no-index`) and parses it **once, server-side** into:

```json
"hunks": [
  {
    "newStart": 13, "newLines": 2,      // where the bar goes in the current file
    "oldStart": 13, "oldLines": 1,
    "kind": "modified",                  // added | modified | deleted
    "patch": "@@ -13,1 +13,2 @@ def load_sheet\n-...\n+...\n+..."
  }
]
```

`newStart`/`newLines` drive the gutter indicators; `patch` is the exact raw
hunk text, ready to be handed to diff2html client-side with a synthesized file
header. No whole-file diff endpoint exists — the hunk is the unit of diffing
throughout, matching the interaction model.

### Watching → SSE (requirement 6)

One chokidar watcher on the root feeds a broadcast queue consumed by
`/api/events` subscribers, coalesced into ~200ms batches:

```json
{ "changed": ["scripts/gen_efl.py", "README.md"], "git": true }
```

- Changes under `.git/` (index, HEAD, refs) are **not** forwarded as file
  events; they set `"git": true`, meaning "statuses may have moved" (e.g. the
  user committed or staged something in a terminal).
- Client behavior: on any event, re-fetch `/api/tree` (cheap; the tree JSON for
  a normal project is small). If the currently open file is in `changed`, or
  `git` is true and the open file has status, re-fetch it and re-render **while
  preserving scroll position and any expanded hunks that still exist**.
  `EventSource` reconnects automatically; on reconnect the client does one full
  refresh to resync.

This is deliberately dumb — no granular cache invalidation, no tree diffing.
At local-directory scale, re-fetching JSON is faster than being clever.

## 5. Frontend design

### Markdown rendering (requirement 2)

- markdown-it with GFM affordances: tables, strikethrough, autolinks,
  task-list checkboxes, heading anchors, footnotes.
- Fenced code blocks are highlighted with the **same Shiki instance** used for
  code files — so code inside markdown and standalone code files look
  identical.
- A ~10-line markdown-it core rule copies each block token's `map` (source
  line range) onto the rendered element as `data-lines="12-18"` — the standard
  trick from live-preview editors, reused here for change indicators (below).
- Relative links between files are intercepted and opened *inside* peruse
  (tree selection follows); relative image sources are rewritten to `/raw/…`.
  External links open in a new tab.
- Optional (v1.1): Mermaid diagram blocks and KaTeX math, each ~5 lines of
  glue with their standard npm builds. Omitted from v1 to keep the page lean.

### Code rendering (requirement 3)

- Shiki `codeToHtml` with
  `themes: { light: "catppuccin-latte", dark: "catppuccin-mocha" }` —
  dual-theme CSS-variable output, so theme switching never re-highlights.
- Language chosen by extension (Shiki's bundled grammar set covers everything
  in a typical project; unknown extensions fall back to plain text). To keep
  the client bundle sane, a curated grammar subset is bundled eagerly and the
  long tail lazy-loads from the package's own assets.
- Line numbers via CSS counters in the gutter. Large-file guard: above ~1 MB
  or ~10k lines, skip highlighting and show plain text with a notice.
- Binary files: images render via `/raw/`; other binaries show a metadata
  card (name, size, status) instead of content.

### Git change indication (requirements 4 & 5)

Tree level: status letters + colors as in §3; "changed only" filter collapses
the tree to changed/untracked files (directories auto-expanded).

In-file, the *subtle* indicator is the familiar editor gutter mark, driven by
the server's `hunks`:

- **Code files:** a 3px vertical bar in the gutter beside each hunk's
  `newStart..newStart+newLines` — Catppuccin green for added, yellow for
  modified — plus a small red triangle marker where lines were deleted.
  Exactly the VS Code / JetBrains gutter convention: legible, ignorable.
- **Rendered markdown:** any block whose `data-lines` range intersects a
  hunk's new-file range gets a 3px accent left-border.

**Click → inline hunk expansion.** Clicking a gutter bar (or a marked
markdown block) expands **that hunk only**, in place — the page never
navigates away:

- An expansion panel is inserted into the document flow directly below the
  last line of the hunk (below the marked block, for markdown). Content
  stays put above; content below shifts down, exactly like VS Code's
  dirty-diff peek or GitHub's expanded comment threads.
- The panel body is diff2html rendering *just that hunk*: the client wraps
  the hunk's `patch` in a minimal synthesized diff header and calls
  `Diff2HtmlUI` on it. Unified view by default; a per-panel toggle offers
  side-by-side. Deleted lines therefore appear only inside the panel —
  the main view always shows the current file.
- Toggle behavior: click again (or the panel's ✕, or `Esc`) collapses it.
  Multiple hunks can be open at once. A subtle "N changes" chip in the
  header offers expand-all/collapse-all for review-the-whole-file flow.
- On SSE-driven re-render, expanded panels re-attach to the hunk nearest
  their old `newStart` if it still exists; vanished hunks close silently.

There is deliberately **no whole-page diff mode** — the hunk panel is the
only diff representation, so the reading context is never lost.

### Theming

`@catppuccin/palette` CSS variables define both palettes; a `data-theme`
attribute on `<html>` selects Latte or Mocha (default follows
`prefers-color-scheme`, toggle persisted in `localStorage`). Shiki dual themes
and diff2html variable overrides key off the same attribute, so one attribute
flip restyles everything with zero re-rendering.

## 6. Repository layout & size budget

Standalone repo (name TBD — working title `peruse`):

```
peruse/
  package.json          # bin: {"peruse": "bin/peruse.js"}; publishes dist/
  bin/peruse.js        # CLI arg parsing, open browser        (~40 lines)
  server/index.js       # Hono app: routes, git, chokidar→SSE  (~280 lines)
  web/
    index.html          # layout + Alpine templates            (~120 lines)
    app.js              # tree/view/hunk/SSE logic             (~350 lines)
    style.css           # Catppuccin variables + layout        (~150 lines)
  scripts/build.js      # esbuild one-shot → dist/             (~30 lines)
  dist/                 # prebuilt client (generated, published to npm)
```

Plain modern ESM JavaScript, no TypeScript compile step (JSDoc types where
they pay for themselves); esbuild exists only to bundle the client libraries.

## 7. Alternatives considered and rejected

1. **Just run `code serve-web`** — genuinely zero code and covers all six
   requirements, but it's an IDE: heavy process, editing-focused chrome, and
   the reading experience the requirements describe isn't what you get.
2. **Extend markserv or difit** — each would need the *other half* of the
   feature set bolted on (git for markserv, browsing/markdown for difit),
   inside someone else's architecture. More code than the glue server, less
   control.
3. **Python (Starlette + uvicorn + watchfiles), PEP 723 single file** — the
   first draft of this design. Rejected for a standalone tool: all client
   libraries are npm-native (Python could only reach them via CDN at runtime),
   `npx` is the natural distribution channel for this category, and one
   language beats two. watchfiles/Starlette were fine; the ecosystem seam
   was the problem.
4. **Bun instead of Node** — attractive (single compiled binary via
   `bun build --compile`, built-in server and watcher), deliberately kept as
   a *future packaging option* rather than a requirement: the code is plain
   ESM and doesn't preclude it, but Node ≥ 20 is what everyone already has.
5. **Server-side rendering (markdown/highlighting on the server)** — fewer
   moving parts in the browser and Shiki can run in Node, but the dual-theme
   CSS trick, scroll-preserving in-place re-renders, and markdown line-map
   plumbing are all simpler with client-side rendering. The server stays a
   dumb file/git/events API.

## 8. Open questions

1. **Gitignored files:** hidden by default with a toggle, or always shown but
   dimmed? (Design assumes shown-but-dimmed, toggle to hide.)
2. **Diff baseline:** worktree vs `HEAD` (staged + unstaged together — the
   design default) or a staged/unstaged distinction like `git diff` vs
   `git diff --staged`? A dropdown is cheap but is it wanted?
3. **Mermaid/KaTeX in v1?** Cheap to add; excluded only for leanness.
4. **Non-git directories:** everything except requirements 4–5 still works;
   the design degrades gracefully (no status column, no gutter marks).
   Confirm that's the desired behavior rather than an error.
5. ~~**Name**~~ Resolved: `peruse`, repo `talkasab/peruse`, published as
   `@talkasab/peruse` (bare npm name is squatted); installed bin is `peruse`.

## Sources

- [markserv](https://github.com/markserv/markserv), [mdserver](https://github.com/deepdadou/mdserver), [gh-markdown-preview](https://github.com/yusukebe/gh-markdown-preview), [markdown-proxy](https://github.com/patakuti/markdown-proxy) — markdown + live-reload servers survey
- [difit](https://github.com/yoshiko-pg/difit) ([npm](https://www.npmjs.com/package/difit)), [diffhub](https://github.com/mblode/diffhub) — local GitHub-style diff viewers
- [Ferrite](https://github.com/OlaProeis/Ferrite) — native-app near-miss
- [Shiki dual themes](https://shiki.style/guide/dual-themes), [Shiki bundled themes](https://shiki.style/themes) — Catppuccin Latte/Mocha bundled, CSS-variable dual-theme output
- [diff2html](https://github.com/rtfpessoa/diff2html) ([site](https://diff2html.xyz/)) — diff → HTML rendering
- [chokidar](https://github.com/paulmillr/chokidar) — file watching
- [Hono](https://hono.dev) — minimal HTTP framework with SSE helper
- [Catppuccin palette](https://catppuccin.com/palette/), [catppuccin/palette](https://github.com/catppuccin/palette) — official CSS variables
