(() => {
  const APP_VERSION = window.APP_VERSION || 'dev';
  const STORAGE_PREFIX = 'extraction-reviewer:';
  const REVIEWER_KEY = STORAGE_PREFIX + 'reviewer';
  const GUIDE_SEEN_KEY = STORAGE_PREFIX + 'guide-seen';

  // ---------- State ----------
  const state = {
    reviewer: '',
    files: [], // [{sha1, name, data, collapsed}]
    manifest: [],
    selection: { sha1: null, findingIndex: null, panel: null }, // panel: null | "missing"
    reviews: {}, // sha1 -> {responses: {idx: {status, comment, firstReviewedAt, updatedAt}}, missing: [], notes}
  };

  // ---------- Elements ----------
  const el = {
    landing: document.getElementById('landing'),
    app: document.getElementById('app'),
    landingReviewer: document.getElementById('landingReviewer'),
    pickFolderBtn: document.getElementById('pickFolderBtn'),
    pickFilesBtn: document.getElementById('pickFilesBtn'),
    folderInput: document.getElementById('folderInput'),
    filesInput: document.getElementById('filesInput'),
    dropzone: document.getElementById('dropzone'),
    loadErrors: document.getElementById('loadErrors'),
    reviewerInput: document.getElementById('reviewerInput'),
    addFilesBtn: document.getElementById('addFilesBtn'),
    exportBtn: document.getElementById('exportBtn'),
    groupList: document.getElementById('groupList'),
    counts: document.getElementById('counts'),
    toolbarEyebrow: document.getElementById('toolbarEyebrow'),
    toolbarTitle: document.getElementById('toolbarTitle'),
    toolbarSubtitle: document.getElementById('toolbarSubtitle'),
    content: document.getElementById('content'),
    helpBtn: document.getElementById('helpBtn'),
    helpDialog: document.getElementById('helpDialog'),
    helpCloseBtn: document.getElementById('helpCloseBtn'),
  };

  // ---------- Helpers ----------
  function escapeHtml(v) {
    return String(v ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }
  function prettifyToken(v) {
    return String(v ?? '').replaceAll('_', ' ');
  }
  function slugify(v) {
    return (
      String(v || '')
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-+|-+$/g, '') || 'reviewer'
    );
  }
  function nowIso() {
    return new Date().toISOString();
  }

  async function sha1Hex(bytes) {
    const buf = await crypto.subtle.digest('SHA-1', bytes);
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }

  function isInApp() {
    return el.app.style.display !== 'none';
  }

  // ---------- Storage ----------
  function loadReviewer() {
    try {
      const v = localStorage.getItem(REVIEWER_KEY);
      if (v) state.reviewer = v;
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }
  function persistReviewer() {
    try {
      localStorage.setItem(REVIEWER_KEY, state.reviewer || '');
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }
  function loadReviewForFile(sha1) {
    try {
      const raw = localStorage.getItem(STORAGE_PREFIX + sha1);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
  function persistReviewForFile(sha1) {
    const r = state.reviews[sha1];
    if (!r) return;
    try {
      localStorage.setItem(STORAGE_PREFIX + sha1, JSON.stringify(r));
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }

  function ensureReview(sha1) {
    if (!state.reviews[sha1]) {
      const loaded = loadReviewForFile(sha1);
      state.reviews[sha1] = loaded || { responses: {}, missing: [], notes: '' };
    }
    return state.reviews[sha1];
  }
  function ensureResponse(sha1, findingIndex) {
    const rev = ensureReview(sha1);
    if (!rev.responses[findingIndex]) {
      rev.responses[findingIndex] = { status: 'pending', comment: '', firstReviewedAt: null, updatedAt: null };
    }
    return rev.responses[findingIndex];
  }

  // ---------- Loading files ----------
  function basenameWithoutExt(name) {
    return String(name || '')
      .replace(/\.(json|txt|md)$/i, '')
      .replace(/\.(extracted|coded)$/i, '');
  }

  function isCsvManifest(data) {
    return (
      Array.isArray(data) &&
      data.every(
        (entry) =>
          entry &&
          Number.isInteger(entry.row_number) &&
          typeof entry.source_id === 'string' &&
          typeof entry.safe_id === 'string' &&
          typeof entry.staged_path === 'string',
      )
    );
  }

  // Normalize report text: strip trailing whitespace per line, drop lines that
  // start with EHR boilerplate, and collapse runs of blank lines.
  function cleanReportText(raw) {
    if (!raw) return '';
    const lines = String(raw)
      .split(/\r?\n/)
      .map((l) => l.replace(/[ \t]+$/g, ''));
    const kept = lines.filter((l) => {
      const t = l.trim();
      if (/^ATTESTATION\b/i.test(t)) return false;
      if (/^A clinically significant result\b/i.test(t)) return false;
      return true;
    });
    const collapsed = [];
    let lastBlank = false;
    for (const l of kept) {
      const blank = l.trim().length === 0;
      if (blank && lastBlank) continue;
      collapsed.push(l);
      lastBlank = blank;
    }
    while (collapsed.length && !collapsed[0].trim()) collapsed.shift();
    while (collapsed.length && !collapsed[collapsed.length - 1].trim()) collapsed.pop();
    return collapsed.join('\n');
  }

  // Piece together a pseudo-report from extraction output when no report file
  // was provided. Deduped by trimmed content.
  function reconstructReportFromJson(data) {
    const chunks = [];
    const seen = new Set();
    const push = (t) => {
      const norm = String(t || '').trim();
      if (!norm || seen.has(norm)) return;
      seen.add(norm);
      chunks.push(norm);
    };
    const findings = Array.isArray(data.findings) ? data.findings : [];
    for (const f of findings) push(f.report_text);
    const nft = Array.isArray(data.non_finding_text) ? data.non_finding_text : [];
    for (const n of nft) push(n.text);
    return chunks.join('\n\n');
  }

  async function loadFileList(fileList) {
    const errors = [];
    const seenSha1 = new Set(state.files.map((f) => f.sha1));

    // Partition: JSON extractions + paired report text files keyed by basename.
    const textByBase = new Map();
    const jsonFiles = [];
    for (const file of fileList) {
      if (!file.name) continue;
      const lower = file.name.toLowerCase();
      if (lower === 'batch_results.jsonl' || lower === 'extraction_reviewer.html') continue;
      if (lower.endsWith('.txt') || lower.endsWith('.md')) {
        textByBase.set(basenameWithoutExt(file.name), file);
      } else if (lower.endsWith('.json')) {
        jsonFiles.push(file);
      }
    }

    for (const file of jsonFiles) {
      try {
        const text = await file.text();
        const bytes = new TextEncoder().encode(text);
        const sha1 = (await sha1Hex(bytes)).slice(0, 12);
        if (seenSha1.has(sha1)) continue;
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          if (/\.(extracted|coded)\.json$/i.test(file.name)) errors.push(`${file.name}: invalid JSON`);
          continue;
        }
        if (isCsvManifest(data)) {
          state.manifest = data;
          continue;
        }
        if (!data || !Array.isArray(data.findings)) {
          if (/\.(extracted|coded)\.json$/i.test(file.name)) errors.push(`${file.name}: missing findings[]`);
          continue;
        }

        // Pair with a sibling .txt / .md report; fall back to an embedded field
        // or a reconstruction pieced together from the extraction output.
        let reportText = null;
        let reportSourceName = null;
        let reportIsReconstructed = false;
        const sibling = textByBase.get(basenameWithoutExt(file.name));
        if (sibling) {
          try {
            reportText = await sibling.text();
            reportSourceName = sibling.name;
          } catch (e) {
            errors.push(`${sibling.name}: failed to read (${e.message || e})`);
          }
        } else if (typeof data.report_text === 'string' && data.report_text.trim()) {
          reportText = data.report_text;
          reportSourceName = `${file.name} (embedded)`;
        } else {
          const stitched = reconstructReportFromJson(data);
          if (stitched) {
            reportText = stitched;
            reportSourceName = `reconstructed from ${file.name}`;
            reportIsReconstructed = true;
          }
        }
        reportText = cleanReportText(reportText);

        seenSha1.add(sha1);
        state.files.push({
          sha1,
          name: file.name,
          data,
          collapsed: false,
          reportText,
          reportSourceName,
          reportIsReconstructed,
        });
        ensureReview(sha1);
      } catch (e) {
        errors.push(`${file.name}: ${e.message || e}`);
      }
    }
    state.files.sort((a, b) => a.name.localeCompare(b.name));
    return errors;
  }

  async function handleLoadedFiles(fileList) {
    const reviewerValue = (el.landingReviewer.value || '').trim();
    if (reviewerValue) {
      state.reviewer = reviewerValue;
      persistReviewer();
    }
    const errors = await loadFileList(fileList);
    showLoadErrors(errors);
    if (!state.files.length) return;

    const wasOnLanding = !isInApp();
    if (wasOnLanding) {
      const auto = findNextPending(null) || firstSelection();
      state.selection = auto;
      el.landing.style.display = 'none';
      el.app.style.display = 'grid';
      el.reviewerInput.value = state.reviewer;
    }
    applyAutoCollapse();
    render();
    if (wasOnLanding) maybeShowGuideOnFirstVisit();
  }

  function showLoadErrors(errors) {
    if (!errors.length) {
      el.loadErrors.style.display = 'none';
      el.loadErrors.textContent = '';
      return;
    }
    el.loadErrors.style.display = 'block';
    el.loadErrors.innerHTML =
      `<strong>Skipped ${errors.length} file(s):</strong><br>` + errors.map(escapeHtml).join('<br>');
  }

  async function readFilesFromDataTransfer(dt) {
    const items = dt.items ? Array.from(dt.items) : [];
    const files = [];
    const tasks = [];

    function walkEntry(entry) {
      return new Promise((resolve) => {
        if (entry.isFile) {
          entry.file(
            (f) => {
              files.push(f);
              resolve();
            },
            () => resolve(),
          );
        } else if (entry.isDirectory) {
          const reader = entry.createReader();
          const readBatch = () => {
            reader.readEntries(
              async (entries) => {
                if (!entries.length) {
                  resolve();
                  return;
                }
                await Promise.all(entries.map(walkEntry));
                readBatch();
              },
              () => resolve(),
            );
          };
          readBatch();
        } else resolve();
      });
    }

    for (const item of items) {
      if (item.kind !== 'file') continue;
      const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
      if (entry) tasks.push(walkEntry(entry));
      else {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (tasks.length) await Promise.all(tasks);
    else if (!files.length && dt.files) {
      for (const f of dt.files) files.push(f);
    }
    return files;
  }

  // ---------- Navigation helpers ----------
  function firstSelection() {
    if (!state.files.length) return { sha1: null, findingIndex: null, panel: null };
    const f = state.files[0];
    if (f.data.findings.length) return { sha1: f.sha1, findingIndex: 0, panel: null };
    return { sha1: f.sha1, findingIndex: null, panel: 'missing' };
  }

  function applyAutoCollapse() {
    const activeSha1 = state.selection.sha1;
    for (const f of state.files) {
      f.collapsed = f.sha1 !== activeSha1;
    }
  }

  function setSelection(sel) {
    const changedFile = sel && sel.sha1 !== state.selection.sha1;
    state.selection = sel;
    if (changedFile) applyAutoCollapse();
  }

  function findNextPending(startAfter) {
    let started = startAfter == null;
    for (const file of state.files) {
      for (let i = 0; i < file.data.findings.length; i++) {
        if (!started) {
          if (startAfter.sha1 === file.sha1 && startAfter.findingIndex === i) {
            started = true;
            continue;
          }
          continue;
        }
        const r = ensureResponse(file.sha1, i);
        if (r.status === 'pending') return { sha1: file.sha1, findingIndex: i, panel: null };
      }
    }
    return null;
  }

  function stepFinding(sel, dir) {
    if (!state.files.length) return null;
    let fi = state.files.findIndex((f) => f.sha1 === sel.sha1);
    if (fi < 0) fi = 0;
    let idx = sel.findingIndex ?? (dir > 0 ? -1 : state.files[fi].data.findings.length);
    idx += dir;
    while (fi >= 0 && fi < state.files.length) {
      const findings = state.files[fi].data.findings;
      if (idx >= 0 && idx < findings.length) return { sha1: state.files[fi].sha1, findingIndex: idx, panel: null };
      fi += dir;
      if (fi < 0 || fi >= state.files.length) return null;
      idx = dir > 0 ? 0 : state.files[fi].data.findings.length - 1;
    }
    return null;
  }

  function stepFile(dir) {
    if (!state.files.length) return;
    let fi = state.files.findIndex((f) => f.sha1 === state.selection.sha1);
    if (fi < 0) fi = 0;
    fi += dir;
    if (fi < 0 || fi >= state.files.length) return;
    const file = state.files[fi];
    const findings = file.data.findings;
    let idx = 0;
    if (findings.length) {
      const rev = ensureReview(file.sha1);
      const pending = findings.findIndex((_, i) => !rev.responses[i] || rev.responses[i].status === 'pending');
      idx = pending >= 0 ? pending : 0;
    }
    setSelection({
      sha1: file.sha1,
      findingIndex: findings.length ? idx : null,
      panel: findings.length ? null : 'missing',
    });
    render();
  }

  // ---------- Counts ----------
  function globalCounts() {
    let total = 0,
      approved = 0,
      flagged = 0,
      missingCount = 0;
    for (const file of state.files) {
      total += file.data.findings.length;
      const rev = ensureReview(file.sha1);
      for (const r of Object.values(rev.responses)) {
        if (r.status === 'approved') approved++;
        else if (r.status === 'flagged') flagged++;
      }
      missingCount += rev.missing.length;
    }
    return { total, approved, flagged, pending: total - approved - flagged, missingCount };
  }

  function fileCounts(file) {
    const rev = ensureReview(file.sha1);
    let approved = 0,
      flagged = 0,
      draft = 0;
    for (let i = 0; i < file.data.findings.length; i++) {
      const r = rev.responses[i];
      if (!r) continue;
      if (r.status === 'approved') approved++;
      else if (r.status === 'flagged') flagged++;
      else if ((r.comment || '').trim()) draft++;
    }
    const total = file.data.findings.length;
    return { total, approved, flagged, draft, missing: rev.missing.length, done: approved + flagged };
  }

  // ---------- Rendering ----------
  function render() {
    renderSidebar();
    renderMain();
  }

  function renderSidebar() {
    const c = globalCounts();
    const icon = {
      pending: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>`,
      approved: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 12.5l5 5 10-11" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
      flagged: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3v18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M6 4h12l-3 4.5 3 4.5H6z" fill="currentColor" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>`,
      missed: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M4 12h16" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>`,
    };
    el.counts.innerHTML = `
      <span class="pill" title="${c.pending} pending"><span class="pill-icon pending">${icon.pending}</span><strong>${c.pending}</strong></span>
      <span class="pill" title="${c.approved} approved"><span class="pill-icon approved">${icon.approved}</span><strong>${c.approved}</strong></span>
      <span class="pill" title="${c.flagged} flagged"><span class="pill-icon flagged">${icon.flagged}</span><strong>${c.flagged}</strong></span>
      <span class="pill" title="${c.missingCount} missed (logged by reviewer)"><span class="pill-icon missed">${icon.missed}</span><strong>${c.missingCount}</strong></span>
    `;
    el.exportBtn.disabled = !canExport();
    el.exportBtn.title = canExport()
      ? 'Download zip of review files'
      : 'Enter reviewer identifier and review at least one finding to enable';

    el.groupList.innerHTML = '';
    for (const file of state.files) {
      el.groupList.appendChild(renderGroup(file));
    }
  }

  function renderGroup(file) {
    const counts = fileCounts(file);
    const exam = file.data.exam_info || {};
    const group = document.createElement('div');
    group.className = 'group' + (file.collapsed ? ' collapsed' : '');

    const header = document.createElement('div');
    header.className = 'group-header';
    const metaBits = [
      exam.study_description || '',
      `${counts.done}/${counts.total}`,
      counts.flagged ? `${counts.flagged} flagged` : '',
      counts.missing ? `${counts.missing} missing` : '',
    ]
      .filter(Boolean)
      .join(' · ');
    header.innerHTML = `
      <span class="group-chevron">${file.collapsed ? '\u25B8' : '\u25BE'}</span>
      <div style="min-width:0; flex:1;">
        <div class="group-title" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
        <div class="group-meta">${escapeHtml(metaBits)}</div>
      </div>
    `;
    header.addEventListener('click', () => {
      file.collapsed = !file.collapsed;
      renderSidebar();
    });

    const items = document.createElement('div');
    items.className = 'group-items';
    file.data.findings.forEach((finding, idx) => {
      items.appendChild(renderListItem(file, finding, idx));
    });
    const rev = ensureReview(file.sha1);
    const missingBtn = document.createElement('button');
    missingBtn.type = 'button';
    missingBtn.className =
      'missing-link' + (state.selection.sha1 === file.sha1 && state.selection.panel === 'missing' ? ' active' : '');
    missingBtn.innerHTML = `<span>+ Missing findings</span><span>${rev.missing.length}</span>`;
    missingBtn.addEventListener('click', () => {
      setSelection({ sha1: file.sha1, findingIndex: null, panel: 'missing' });
      render();
    });
    items.appendChild(missingBtn);

    group.appendChild(header);
    group.appendChild(items);
    return group;
  }

  function renderListItem(file, finding, idx) {
    const rev = ensureReview(file.sha1);
    const r = rev.responses[idx];
    const status = r ? r.status : 'pending';
    const draft = r && status === 'pending' && (r.comment || '').trim();
    const active = state.selection.sha1 === file.sha1 && state.selection.findingIndex === idx;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = [
      'list-item',
      active ? 'active' : '',
      status === 'approved' ? 'status-approved done-approved' : '',
      status === 'flagged' ? 'status-flagged done-flagged' : '',
      draft ? 'status-draft' : '',
    ]
      .filter(Boolean)
      .join(' ');
    const locParts = [];
    if (finding.location && finding.location.specific_anatomy) locParts.push(finding.location.specific_anatomy);
    if (finding.location && finding.location.laterality) locParts.push(finding.location.laterality);
    const meta = [finding.presence, locParts.join(' ')].filter(Boolean).map(escapeHtml).join(' · ');
    btn.innerHTML = `
      <span class="status-dot"></span>
      <div style="min-width:0;">
        <div class="item-title">${escapeHtml(finding.finding_name || '(unnamed)')}</div>
        <div class="item-meta">${meta}</div>
      </div>
    `;
    btn.addEventListener('click', () => {
      setSelection({ sha1: file.sha1, findingIndex: idx, panel: null });
      render();
    });
    return btn;
  }

  function renderMain() {
    const sel = state.selection;
    const file = state.files.find((f) => f.sha1 === sel.sha1);
    if (!file) {
      el.toolbarTitle.textContent = '\u2014';
      el.toolbarSubtitle.textContent = '';
      el.content.innerHTML = `<div class="empty-state">Select a file to begin.</div>`;
      return;
    }
    if (sel.panel === 'missing') {
      el.toolbarEyebrow.textContent = 'Missing findings';
      el.toolbarTitle.textContent = file.name;
      el.toolbarSubtitle.textContent = file.data.exam_info?.study_description || '';
      renderMissingPanel(file);
      return;
    }
    const idx = sel.findingIndex ?? 0;
    const finding = file.data.findings[idx];
    if (!finding) {
      el.content.innerHTML = `<div class="empty-state">This report has no extracted findings.</div>`;
      return;
    }
    el.toolbarEyebrow.textContent = `${file.name} \u00B7 Finding ${idx + 1} of ${file.data.findings.length}`;
    el.toolbarTitle.textContent = finding.finding_name || '(unnamed)';
    el.toolbarSubtitle.textContent = file.data.exam_info?.study_description || '';
    renderFindingView(file, finding, idx);
  }

  function renderFindingView(file, finding, idx) {
    const response = ensureResponse(file.sha1, idx);
    const draft = response.status === 'pending' && (response.comment || '').trim();
    const titleStatus =
      response.status === 'approved'
        ? 'approved'
        : response.status === 'flagged'
          ? 'flagged'
          : draft
            ? 'draft'
            : 'pending';

    const exam = file.data.exam_info || {};
    const location = finding.location || {};
    const attrs = Array.isArray(finding.attributes) ? finding.attributes : [];
    const nonFindingText = Array.isArray(file.data.non_finding_text) ? file.data.non_finding_text : [];

    const presenceBadge = finding.presence
      ? `<span class="presence-badge presence-${escapeHtml(finding.presence)}">${escapeHtml(finding.presence)}</span>`
      : '';
    const sectionBadge = finding.source_section
      ? `<span class="source-badge source-badge-right">${escapeHtml(finding.source_section)}</span>`
      : '';
    const chip = statusChipHtml(response, draft);

    const examBits = [
      exam.study_description,
      exam.study_date,
      exam.modality,
      exam.body_part || exam.body_region,
      exam.contrast,
    ]
      .filter(Boolean)
      .map((v) => `<span>${escapeHtml(prettifyToken(String(v)))}</span>`);
    const examStrip = examBits.length
      ? `<div class="exam-strip"><span class="exam-label">Exam</span>${examBits.join(' <span class="sep">·</span> ')}</div>`
      : '';

    const attrsTable = attrs.length
      ? `<table class="attrs-table">${attrs.map((a) => `<tr><th>${escapeHtml(prettifyToken(a.key))}</th><td>${escapeHtml(a.value)}</td></tr>`).join('')}</table>`
      : '';

    const codingHtml = renderCoding(finding.coding);

    const ctxEntries = nonFindingText
      .map(
        (nt) => `
      <div class="context-entry">
        <div class="context-category">${escapeHtml(nt.category || 'other')}</div>
        <div class="context-text">${escapeHtml(nt.text || '')}</div>
      </div>
    `,
      )
      .join('');

    const locationChips = [
      locationChip('Anatomy', location.specific_anatomy),
      locationChip('Region', location.body_region),
      locationChip('Side', location.laterality),
    ]
      .filter(Boolean)
      .join('');

    el.content.innerHTML = `
      <article class="message">
        <div class="message-body">
          <div class="details-column">
            ${
              finding.report_text
                ? `
              <div class="section">
                <div class="section-title">Report text</div>
                <div class="quote">${escapeHtml(finding.report_text)}</div>
              </div>`
                : ''
            }
            <div class="extraction-block">
              <span class="status-indicator ${titleStatus}"></span>
              <h2 class="finding-title">${escapeHtml(finding.finding_name || '(unnamed)')}</h2>
              ${presenceBadge}
              ${sectionBadge}
            </div>
            ${locationChips ? `<div class="location-chips-row">${locationChips}</div>` : ''}
            ${
              attrsTable
                ? `
              <div class="section">
                <div class="section-title">Attributes</div>
                ${attrsTable}
              </div>`
                : ''
            }
            ${
              codingHtml
                ? `
              <div class="section">
                <div class="section-title">Coding</div>
                ${codingHtml}
              </div>`
                : ''
            }
            ${examStrip}
            ${
              ctxEntries
                ? `
              <details class="report-context">
                <summary>Report context (${nonFindingText.length} segments)</summary>
                <div class="context-body">${ctxEntries}</div>
              </details>`
                : ''
            }
          </div>
          <aside class="review-column">
            <div class="sticky-review">
              <div>${chip}</div>
              <div>
                <div class="section-title" style="margin-bottom:6px;">Reviewer comment</div>
                <textarea id="commentBox" placeholder="Notes for flagging. Drafts save automatically."></textarea>
              </div>
              <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:space-between;">
                <button type="button" id="clearBtn">Clear</button>
                <div style="display:flex; gap:8px;">
                  <button type="button" class="warning ${draft ? 'is-default' : ''}" id="flagBtn">Flag</button>
                  <button type="button" class="success ${draft ? '' : 'is-default'}" id="approveBtn">Approve</button>
                </div>
              </div>
              <div class="hint">Enter sends flag and jumps to the next pending finding. A approves. J/K move, H/L jump files.</div>
            </div>
          </aside>
        </div>
      </article>
    `;

    const box = document.getElementById('commentBox');
    box.value = response.comment || '';
    box.addEventListener('input', () => {
      response.comment = box.value;
      response.updatedAt = nowIso();
      persistReviewForFile(file.sha1);
      renderSidebar();
    });
    box.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        box.blur();
        return;
      }
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        submitFlag();
      }
    });
    document.getElementById('approveBtn').addEventListener('click', approveCurrent);
    document.getElementById('flagBtn').addEventListener('click', submitFlag);
    document.getElementById('clearBtn').addEventListener('click', () => {
      response.comment = '';
      response.updatedAt = nowIso();
      persistReviewForFile(file.sha1);
      render();
      const b = document.getElementById('commentBox');
      if (b) b.focus();
    });
  }

  function statusChipHtml(response, draft) {
    if (response.status === 'approved') return `<span class="status-chip approved">Approved</span>`;
    if (response.status === 'flagged') return `<span class="status-chip flagged">Flagged</span>`;
    if (draft) return `<span class="status-chip draft">Draft comment</span>`;
    return `<span class="status-chip pending">Pending</span>`;
  }

  function locationChip(label, value) {
    if (!value) return '';
    return `<span class="location-chip">
      <span class="location-chip-label">${escapeHtml(label)}</span>
      <span class="location-chip-value">${escapeHtml(prettifyToken(String(value)))}</span>
    </span>`;
  }

  function renderCoding(coding) {
    if (!coding) return '';
    const rows = [];
    if (coding.finding_code) rows.push(renderCodeRow('Finding', coding.finding_code, 'oifm_id', 'oifm_name'));
    const locCodes = Array.isArray(coding.location_codes) ? coding.location_codes : [];
    locCodes.forEach((lc, i) => {
      rows.push(
        renderCodeRow(locCodes.length > 1 ? `Location ${i + 1}` : 'Location', lc, 'location_id', 'location_name'),
      );
    });
    if (!rows.length) return '';
    return `<div class="coding-block">${rows.join('')}</div>`;
  }

  function renderCodeRow(label, code, idField, nameField) {
    if (!code) return '';
    const status = code.status || 'unmapped';
    const statusChip = `<span class="status-chip ${escapeHtml(status)}">${escapeHtml(status)}</span>`;
    const method = code.method ? `<span class="coding-method">${escapeHtml(code.method)}</span>` : '';
    const idName =
      status === 'coded'
        ? `<span class="coding-name">${escapeHtml(code[nameField] || '')}</span><span class="coding-id">${escapeHtml(code[idField] || '')}</span>`
        : code.reason
          ? `<span class="coding-reason">unmapped &mdash; ${escapeHtml(prettifyToken(code.reason))}</span>`
          : `<span class="coding-reason">unmapped</span>`;
    const reasoning = code.reasoning ? `<div class="coding-reasoning">${escapeHtml(code.reasoning)}</div>` : '';
    const candidates =
      Array.isArray(code.candidates) && code.candidates.length
        ? `<details class="candidates"><summary>${code.candidates.length} candidate(s)</summary><ul>${code.candidates
            .map((c) => {
              const cid = c.oifm_id || c.location_id || '';
              const cname = c.name || c.location_name || '';
              const closest = code.closest_candidate_id && cid === code.closest_candidate_id ? ' closest' : '';
              return `<li class="${closest.trim()}">${escapeHtml(cname)} <span class="coding-id">${escapeHtml(cid)}</span>${closest ? ' <em>(closest)</em>' : ''}</li>`;
            })
            .join('')}</ul></details>`
        : '';
    return `
      <div class="coding-row">
        <div class="coding-row-head">
          <span class="coding-kind">${escapeHtml(label)}</span>
          ${statusChip}
          ${idName}
          ${method}
        </div>
        ${reasoning}
        ${candidates}
      </div>
    `;
  }

  // ---------- Missing findings panel ----------
  function renderMissingPanel(file) {
    const rev = ensureReview(file.sha1);
    const entries = rev.missing
      .map(
        (m, i) => `
      <div class="missing-entry">
        <div class="missing-entry-head">
          <div class="missing-entry-desc">${escapeHtml(m.description)}</div>
          <button type="button" class="danger" data-remove="${i}">Remove</button>
        </div>
        ${m.report_text ? `<div class="missing-entry-quote">${escapeHtml(m.report_text)}</div>` : ''}
        <div class="hint">added ${escapeHtml(m.added_at || '')}</div>
      </div>
    `,
      )
      .join('');

    const reportBlock = file.reportText
      ? `<div class="missing-report">
           <div class="missing-report-head">
             <div class="section-title">Source report</div>
             ${file.reportSourceName ? `<span class="report-source">${escapeHtml(file.reportSourceName)}</span>` : ''}
             ${file.reportIsReconstructed ? `<span class="report-reconstructed" title="Pieced together from extraction snippets">reconstructed</span>` : ''}
           </div>
           <div class="missing-report-text" id="missReportText">${escapeHtml(file.reportText)}</div>
           <div class="hint">Highlight any text above to capture it as the supporting quote. Re-highlight to replace.</div>
         </div>`
      : `<div class="missing-report missing-report-absent">
           <div class="section-title">Source report</div>
           <p class="hint" style="margin:0;">No paired report loaded. Drop a <code>.txt</code> or <code>.md</code> file whose basename matches <code>${escapeHtml(basenameWithoutExt(file.name))}</code> to see the full report here.</p>
         </div>`;

    el.content.innerHTML = `
      <div class="missing-panel">
        <div class="missing-panel-header">
          <h2>Missing findings &mdash; ${escapeHtml(file.name)}</h2>
          <p class="hint" style="margin:0;">Log findings the extractor should have produced but didn&rsquo;t. Saved under <code>missing_findings</code> in this file&rsquo;s review JSON.</p>
        </div>
        ${reportBlock}
        <div class="missing-form">
          <div>
            <label for="missDesc">Describe the missing finding (required)</label>
            <textarea id="missDesc" rows="2" placeholder='e.g., "small left pleural effusion, not mentioned in the impression"'></textarea>
            <div class="hint" style="margin-top:4px;">Enter adds the finding &middot; Shift+Enter for a new line.</div>
          </div>
          <div>
            <div class="missing-quote-label">
              <label>Supporting quote</label>
              <button type="button" class="quote-clear" id="clearQuoteBtn" style="display:none;">Clear</button>
            </div>
            <div class="supporting-quote-box" id="missQuoteDisplay">
              <span class="supporting-quote-empty">${file.reportText ? 'Highlight text in the report above to set the supporting quote.' : 'No report text loaded.'}</span>
            </div>
          </div>
          <div style="display:flex; justify-content:flex-end;">
            <button type="button" class="primary" id="addMissBtn">Add missing finding</button>
          </div>
        </div>
        <div class="missing-list">
          ${entries || '<div class="empty-state">No missing findings logged yet for this report.</div>'}
        </div>
      </div>
    `;

    const descBox = document.getElementById('missDesc');
    const quoteDisplay = document.getElementById('missQuoteDisplay');
    const clearQuoteBtn = document.getElementById('clearQuoteBtn');
    const reportEl = document.getElementById('missReportText');
    let capturedQuote = '';

    function renderQuoteDisplay() {
      if (capturedQuote) {
        quoteDisplay.innerHTML = `<blockquote class="supporting-quote">${escapeHtml(capturedQuote)}</blockquote>`;
        quoteDisplay.classList.add('has-quote');
        if (clearQuoteBtn) clearQuoteBtn.style.display = '';
      } else {
        quoteDisplay.innerHTML = `<span class="supporting-quote-empty">${file.reportText ? 'Highlight text in the report above to set the supporting quote.' : 'No report text loaded.'}</span>`;
        quoteDisplay.classList.remove('has-quote');
        if (clearQuoteBtn) clearQuoteBtn.style.display = 'none';
      }
    }

    // Paint a persistent highlight in the report for the captured quote.
    function paintHighlight(quote) {
      if (!reportEl || !file.reportText) return;
      if (!quote) {
        reportEl.innerHTML = escapeHtml(file.reportText);
        return;
      }
      const idx = file.reportText.indexOf(quote);
      if (idx < 0) {
        reportEl.innerHTML = escapeHtml(file.reportText);
        return;
      }
      const before = file.reportText.slice(0, idx);
      const mid = file.reportText.slice(idx, idx + quote.length);
      const after = file.reportText.slice(idx + quote.length);
      reportEl.innerHTML =
        escapeHtml(before) + `<mark class="captured-quote">${escapeHtml(mid)}</mark>` + escapeHtml(after);
    }

    if (reportEl) {
      const pullSelection = () => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) return;
        if (!reportEl.contains(sel.anchorNode) || !reportEl.contains(sel.focusNode)) return;
        const text = sel
          .toString()
          .replace(/\r\n/g, '\n')
          .replace(/^\s+|\s+$/g, '');
        if (!text) return;
        capturedQuote = text;
        paintHighlight(capturedQuote);
        sel.removeAllRanges();
        renderQuoteDisplay();
        if (descBox) descBox.focus();
      };
      reportEl.addEventListener('mouseup', pullSelection);
      reportEl.addEventListener('keyup', (ev) => {
        if (ev.shiftKey || ev.key.startsWith('Arrow')) pullSelection();
      });
    }

    if (clearQuoteBtn) {
      clearQuoteBtn.addEventListener('click', () => {
        capturedQuote = '';
        paintHighlight('');
        renderQuoteDisplay();
      });
    }

    const addBtn = document.getElementById('addMissBtn');
    const submit = () => {
      const desc = (descBox.value || '').trim();
      if (!desc) {
        descBox.focus();
        return;
      }
      rev.missing.push({
        description: desc,
        report_text: capturedQuote,
        added_at: nowIso(),
      });
      persistReviewForFile(file.sha1);
      render();
    };
    addBtn.addEventListener('click', submit);
    descBox.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' && !ev.shiftKey) {
        ev.preventDefault();
        submit();
      }
    });

    el.content.querySelectorAll('[data-remove]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const i = parseInt(btn.getAttribute('data-remove'), 10);
        rev.missing.splice(i, 1);
        persistReviewForFile(file.sha1);
        render();
      });
    });
  }

  // ---------- Actions ----------
  function approveCurrent() {
    const sel = state.selection;
    if (sel.sha1 == null || sel.findingIndex == null) return;
    const r = ensureResponse(sel.sha1, sel.findingIndex);
    const now = nowIso();
    if (!r.firstReviewedAt) r.firstReviewedAt = now;
    r.status = 'approved';
    r.updatedAt = now;
    persistReviewForFile(sel.sha1);
    moveToNextPendingOrStay();
  }

  function submitFlag() {
    const sel = state.selection;
    if (sel.sha1 == null || sel.findingIndex == null) return;
    const r = ensureResponse(sel.sha1, sel.findingIndex);
    const comment = (r.comment || '').trim();
    if (!comment) {
      const box = document.getElementById('commentBox');
      if (box) box.focus();
      return;
    }
    const now = nowIso();
    if (!r.firstReviewedAt) r.firstReviewedAt = now;
    r.status = 'flagged';
    r.updatedAt = now;
    persistReviewForFile(sel.sha1);
    moveToNextPendingOrStay();
  }

  function moveToNextPendingOrStay() {
    const next = findNextPending(state.selection);
    if (next) setSelection(next);
    else {
      const step = stepFinding(state.selection, 1);
      if (step) setSelection(step);
    }
    render();
  }

  // ---------- Export ----------
  function canExport() {
    if (!(state.reviewer || '').trim()) return false;
    for (const file of state.files) {
      const rev = ensureReview(file.sha1);
      if (Object.keys(rev.responses).length || rev.missing.length || (rev.notes || '').trim()) return true;
    }
    return false;
  }

  function buildReviewJson(file) {
    const rev = ensureReview(file.sha1);
    const findings = file.data.findings || [];
    const responses = [];
    let approved = 0,
      flagged = 0;
    for (let i = 0; i < findings.length; i++) {
      const r = rev.responses[i];
      const status = r ? r.status : 'pending';
      if (status === 'approved') approved++;
      else if (status === 'flagged') flagged++;
      responses.push({
        finding_index: i,
        finding_name: findings[i].finding_name || '',
        presence: findings[i].presence || null,
        status,
        comment: r ? r.comment || '' : '',
        first_reviewed_at: r ? r.firstReviewedAt : null,
        updated_at: r ? r.updatedAt : null,
      });
    }
    const exam = file.data.exam_info || {};
    return {
      app_version: APP_VERSION,
      source_file: file.name,
      source_sha1: file.sha1,
      source_exam: {
        study_description: exam.study_description || null,
        study_date: exam.study_date || null,
        modality: exam.modality || null,
      },
      reviewer: { identifier: state.reviewer || '' },
      exported_at: nowIso(),
      summary: {
        total_findings: findings.length,
        approved,
        flagged,
        pending: findings.length - approved - flagged,
        missing_findings_count: rev.missing.length,
      },
      responses,
      report_level_notes: rev.notes || '',
      missing_findings: rev.missing,
    };
  }

  function reviewFilenameFor(file) {
    const base = file.name.replace(/\.json$/i, '');
    return `${base}.review.json`;
  }

  function exportZip() {
    if (!canExport()) return;
    const files = {};
    for (const f of state.files) {
      const rev = ensureReview(f.sha1);
      const hasAny = Object.keys(rev.responses).length || rev.missing.length || (rev.notes || '').trim();
      if (!hasAny) continue;
      const payload = buildReviewJson(f);
      const bytes = new TextEncoder().encode(JSON.stringify(payload, null, 2));
      files[reviewFilenameFor(f)] = bytes;
    }
    if (!Object.keys(files).length) return;
    const zipped = fflate.zipSync(files);
    const blob = new Blob([zipped], { type: 'application/zip' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const now = new Date();
    const stamp =
      [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join(
        '',
      ) +
      '-' +
      [String(now.getHours()).padStart(2, '0'), String(now.getMinutes()).padStart(2, '0')].join('');
    a.href = url;
    a.download = `reviews-${slugify(state.reviewer)}-${stamp}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // ---------- Keyboard ----------
  function onGlobalKey(ev) {
    const t = ev.target;
    const editing = t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable);
    if (editing || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    if (!isInApp()) return;
    const k = ev.key.toLowerCase();
    if (k === 'a') {
      ev.preventDefault();
      approveCurrent();
      return;
    }
    if (k === 'f') {
      ev.preventDefault();
      const box = document.getElementById('commentBox');
      if (!box) return;
      const r =
        state.selection.findingIndex != null
          ? ensureResponse(state.selection.sha1, state.selection.findingIndex)
          : null;
      if (r && (r.comment || '').trim()) submitFlag();
      else box.focus();
      return;
    }
    if (k === 'j') {
      ev.preventDefault();
      const s = stepFinding(state.selection, -1);
      if (s) {
        setSelection(s);
        render();
      }
      return;
    }
    if (k === 'k') {
      ev.preventDefault();
      const s = stepFinding(state.selection, 1);
      if (s) {
        setSelection(s);
        render();
      }
      return;
    }
    if (k === 'h') {
      ev.preventDefault();
      stepFile(-1);
      return;
    }
    if (k === 'l') {
      ev.preventDefault();
      stepFile(1);
      return;
    }
    if (k === '?' || ev.key === '?') {
      ev.preventDefault();
      openHelp();
      return;
    }
  }

  function openHelp() {
    if (el.helpDialog && typeof el.helpDialog.showModal === 'function' && !el.helpDialog.open) {
      el.helpDialog.showModal();
    }
    try {
      localStorage.setItem(GUIDE_SEEN_KEY, '1');
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }
  function closeHelp() {
    if (el.helpDialog && el.helpDialog.open) el.helpDialog.close();
  }
  function hasSeenGuide() {
    try {
      return localStorage.getItem(GUIDE_SEEN_KEY) === '1';
    } catch {
      return false;
    }
  }
  function maybeShowGuideOnFirstVisit() {
    if (hasSeenGuide()) return;
    openHelp();
  }

  // ---------- Wiring ----------
  loadReviewer();
  el.landingReviewer.value = state.reviewer;

  el.pickFolderBtn.addEventListener('click', () => el.folderInput.click());
  el.pickFilesBtn.addEventListener('click', () => el.filesInput.click());
  el.folderInput.addEventListener('change', async (ev) => {
    const files = Array.from(ev.target.files || []);
    ev.target.value = '';
    await handleLoadedFiles(files);
  });
  el.filesInput.addEventListener('change', async (ev) => {
    const files = Array.from(ev.target.files || []);
    ev.target.value = '';
    await handleLoadedFiles(files);
  });

  ['dragenter', 'dragover'].forEach((e) =>
    el.dropzone.addEventListener(e, (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      el.dropzone.classList.add('drag');
    }),
  );
  ['dragleave', 'drop'].forEach((e) =>
    el.dropzone.addEventListener(e, (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      el.dropzone.classList.remove('drag');
    }),
  );
  el.dropzone.addEventListener('drop', async (ev) => {
    const files = await readFilesFromDataTransfer(ev.dataTransfer);
    await handleLoadedFiles(files);
  });

  el.landingReviewer.addEventListener('input', () => {
    state.reviewer = el.landingReviewer.value;
    persistReviewer();
  });
  el.reviewerInput.addEventListener('input', () => {
    state.reviewer = el.reviewerInput.value;
    persistReviewer();
    renderSidebar();
  });

  el.addFilesBtn.addEventListener('click', () => el.filesInput.click());
  el.exportBtn.addEventListener('click', exportZip);
  if (el.helpBtn) el.helpBtn.addEventListener('click', openHelp);
  if (el.helpCloseBtn) el.helpCloseBtn.addEventListener('click', closeHelp);
  if (el.helpDialog) {
    // Click-outside-to-close: the <dialog> itself receives clicks on its backdrop.
    el.helpDialog.addEventListener('click', (ev) => {
      if (ev.target === el.helpDialog) closeHelp();
    });
  }

  document.addEventListener('keydown', onGlobalKey);

  // ---------- Embedded bundle auto-load ----------
  async function loadEmbeddedBundle() {
    const b64 = (window.EMBEDDED_BUNDLE_B64 || '').trim();
    if (!b64) return;
    try {
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const entries = fflate.unzipSync(bytes);
      const decoder = new TextDecoder('utf-8');
      const files = [];
      for (const [path, data] of Object.entries(entries)) {
        if (path.endsWith('/')) continue; // skip dir entries
        const name = path.split('/').pop();
        if (!name) continue;
        const lower = name.toLowerCase();
        if (!(lower.endsWith('.json') || lower.endsWith('.txt') || lower.endsWith('.md'))) continue;
        const text = decoder.decode(data);
        files.push({
          name,
          async text() {
            return text;
          },
        });
      }
      if (files.length) await handleLoadedFiles(files);
    } catch (e) {
      showLoadErrors([`embedded bundle failed to load: ${e.message || e}`]);
    }
  }
  loadEmbeddedBundle();
})();
