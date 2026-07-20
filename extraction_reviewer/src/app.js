(() => {
  const APP_VERSION = window.APP_VERSION || 'dev';
  const STORAGE_PREFIX = 'extraction-reviewer:';
  const LEGACY_REVIEWER_KEY = STORAGE_PREFIX + 'reviewer';
  const PREFS_KEY = STORAGE_PREFIX + 'preferences';
  const BATCH_INDEX_KEY = STORAGE_PREFIX + 'batch-index';
  const DB_NAME = STORAGE_PREFIX + 'batches';
  const DB_STORE = 'batches';
  const FLAG_TARGETS = [
    ['finding_name', 'Finding name'],
    ['presence', 'Presence'],
    ['anatomic_site', 'Anatomic site'],
    ['laterality', 'Laterality'],
    ['size', 'Size'],
    ['severity', 'Severity'],
    ['extent', 'Extent'],
    ['temporal_status', 'Temporal status'],
    ['hedged_language', 'Hedged language'],
    ['aggregated_findings', 'Lumps multiple findings'],
  ];

  // ---------- State ----------
  const state = {
    reviewer: '',
    files: [], // [{sha1, name, data, collapsed}]
    manifest: [],
    invalidResults: [],
    extractionSet: [],
    csv: null,
    localBatch: null,
    wizardStep: 1,
    joinSummary: null,
    savedBatchCandidate: null,
    prefs: { reviewer: '', guideSeen: false, lastColumnMapping: null },
    batchIndex: [],
    selection: { sha1: null, findingIndex: null, panel: null }, // panel: null | "missing"
    reviews: {}, // sha1 -> {responses: {idx: {status, comment, firstReviewedAt, updatedAt}}, missing: [], notes}
  };

  // ---------- Elements ----------
  const el = {
    landing: document.getElementById('landing'),
    app: document.getElementById('app'),
    landingReviewerLabel: document.getElementById('landingReviewerLabel'),
    landingReviewerChange: document.getElementById('landingReviewerChange'),
    pickCsvBtn: document.getElementById('pickCsvBtn'),
    csvInput: document.getElementById('csvInput'),
    csvDropzone: document.getElementById('csvDropzone'),
    csvSelection: document.getElementById('csvSelection'),
    csvErrors: document.getElementById('csvErrors'),
    columnPicker: document.getElementById('columnPicker'),
    idColumnSelect: document.getElementById('idColumnSelect'),
    textColumnSelect: document.getElementById('textColumnSelect'),
    csvNextBtn: document.getElementById('csvNextBtn'),
    pickResultsBtn: document.getElementById('pickResultsBtn'),
    resultsDropzone: document.getElementById('resultsDropzone'),
    resultsSelection: document.getElementById('resultsSelection'),
    resultsBackBtn: document.getElementById('resultsBackBtn'),
    resultsNextBtn: document.getElementById('resultsNextBtn'),
    confirmBackBtn: document.getElementById('confirmBackBtn'),
    startReviewBtn: document.getElementById('startReviewBtn'),
    joinSummary: document.getElementById('joinSummary'),
    quoteCheck: document.getElementById('quoteCheck'),
    savedBatches: document.getElementById('savedBatches'),
    savedBatchList: document.getElementById('savedBatchList'),
    wizardSteps: [1, 2, 3].map((n) => document.getElementById(`wizardStep${n}`)),
    progressSteps: [1, 2, 3].map((n) => document.getElementById(`progressStep${n}`)),
    pickFilesBtn: document.getElementById('pickFilesBtn'),
    pickCompatFolderBtn: document.getElementById('pickCompatFolderBtn'),
    folderInput: document.getElementById('folderInput'),
    filesInput: document.getElementById('filesInput'),
    compatFolderInput: document.getElementById('compatFolderInput'),
    loadErrors: document.getElementById('loadErrors'),
    reviewerChip: document.getElementById('reviewerChip'),
    reviewerChipName: document.getElementById('reviewerChipName'),
    reviewerChipChange: document.getElementById('reviewerChipChange'),
    addFilesBtn: document.getElementById('addFilesBtn'),
    exportBtn: document.getElementById('exportBtn'),
    exportMenuBtn: document.getElementById('exportMenuBtn'),
    exportMenu: document.getElementById('exportMenu'),
    exportZipBtn: document.getElementById('exportZipBtn'),
    groupList: document.getElementById('groupList'),
    counts: document.getElementById('counts'),
    toolbarEyebrow: document.getElementById('toolbarEyebrow'),
    toolbarJoinWarning: document.getElementById('toolbarJoinWarning'),
    toolbarTitle: document.getElementById('toolbarTitle'),
    toolbarSubtitle: document.getElementById('toolbarSubtitle'),
    content: document.getElementById('content'),
    reviewerDialog: document.getElementById('reviewerDialog'),
    reviewerForm: document.getElementById('reviewerForm'),
    reviewerDialogTitle: document.getElementById('reviewerDialogTitle'),
    reviewerNameInput: document.getElementById('reviewerNameInput'),
    reviewerCancelBtn: document.getElementById('reviewerCancelBtn'),
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

  async function sha256Hex(bytes) {
    const buf = await crypto.subtle.digest('SHA-256', bytes);
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }

  function isInApp() {
    return el.app.style.display !== 'none';
  }

  function updateReviewerUi() {
    const name = (state.reviewer || '').trim();
    el.landingReviewerLabel.textContent = name ? `Reviewing as ${name}` : 'No reviewer set';
    el.landingReviewerChange.textContent = name ? 'Change' : 'Set reviewer';
    el.reviewerChipName.textContent = name || 'Set reviewer';
    el.reviewerChip.classList.toggle('missing', !name);
    el.reviewerChipChange.textContent = name ? 'Change' : 'Set';
  }

  function openReviewerDialog() {
    if (!el.reviewerDialog || el.reviewerDialog.open) return;
    const name = (state.reviewer || '').trim();
    el.reviewerDialogTitle.textContent = name ? 'Change reviewer' : "Who's reviewing?";
    el.reviewerNameInput.value = name;
    el.reviewerDialog.showModal();
    window.setTimeout(() => {
      el.reviewerNameInput.focus();
      el.reviewerNameInput.select();
    }, 0);
  }

  function saveReviewerName() {
    const name = (el.reviewerNameInput.value || '').trim();
    if (!name) {
      el.reviewerNameInput.focus();
      return;
    }
    state.reviewer = name;
    persistPreferences();
    scheduleBatchSave();
    updateReviewerUi();
    if (isInApp()) renderSidebar();
    el.reviewerDialog.close();
  }

  // ---------- Storage ----------
  function loadPreferences() {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (raw) state.prefs = { ...state.prefs, ...JSON.parse(raw) };
      if (!state.prefs.reviewer) state.prefs.reviewer = localStorage.getItem(LEGACY_REVIEWER_KEY) || '';
      state.reviewer = state.prefs.reviewer || '';
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }

  function persistPreferences() {
    state.prefs.reviewer = state.reviewer || '';
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }

  function loadBatchIndex() {
    try {
      const raw = localStorage.getItem(BATCH_INDEX_KEY);
      state.batchIndex = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(state.batchIndex)) state.batchIndex = [];
    } catch {
      state.batchIndex = [];
    }
  }

  function persistBatchIndex() {
    try {
      localStorage.setItem(BATCH_INDEX_KEY, JSON.stringify(state.batchIndex));
    } catch {
      // localStorage may be unavailable under strict browser/privacy settings.
    }
  }

  function openReviewDb() {
    return new Promise((resolve, reject) => {
      if (!window.indexedDB) {
        reject(new Error('IndexedDB is unavailable.'));
        return;
      }
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(DB_STORE)) db.createObjectStore(DB_STORE, { keyPath: 'batchId' });
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error || new Error('Could not open IndexedDB.'));
    });
  }

  async function withBatchStore(mode, operation) {
    const db = await openReviewDb();
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction(DB_STORE, mode);
        const store = transaction.objectStore(DB_STORE);
        const request = operation(store);
        let result;
        request.onsuccess = () => {
          result = request.result;
        };
        request.onerror = () => reject(request.error || new Error('IndexedDB request failed.'));
        transaction.oncomplete = () => resolve(result);
        transaction.onabort = () => reject(transaction.error || new Error('IndexedDB transaction aborted.'));
      });
    } finally {
      db.close();
    }
  }

  function getSavedBatch(batchId) {
    return withBatchStore('readonly', (store) => store.get(batchId));
  }

  function putSavedBatch(payload) {
    return withBatchStore('readwrite', (store) => store.put(payload));
  }

  function removeSavedBatch(batchId) {
    return withBatchStore('readwrite', (store) => store.delete(batchId));
  }

  function serializeFiles() {
    return state.files.map((file) => ({ ...file }));
  }

  function currentBatchId() {
    return state.csv?.batchId || state.localBatch?.batchId || null;
  }

  function currentBatchLabel() {
    return state.csv?.filename || state.localBatch?.label || 'Review batch';
  }

  function buildBatchPayload() {
    const batchId = currentBatchId();
    if (!batchId) return null;
    return {
      batchId,
      batchKind: state.csv ? 'csv' : state.localBatch.kind,
      csvFilename: currentBatchLabel(),
      csvText: state.csv?.text ?? null,
      csvHeaders: state.csv?.headers ?? null,
      csvRecords: state.csv?.records ?? null,
      idColumnIndex: state.csv?.idColumnIndex ?? null,
      textColumnIndex: state.csv?.textColumnIndex ?? null,
      manifest: state.manifest,
      files: serializeFiles(),
      invalidResults: state.invalidResults,
      extractionSet: state.extractionSet,
      reviews: state.reviews,
      reportNotes: Object.fromEntries(
        Object.entries(state.reviews).map(([sha1, review]) => [sha1, review.notes || '']),
      ),
      missingFindings: Object.fromEntries(
        Object.entries(state.reviews).map(([sha1, review]) => [sha1, review.missing || []]),
      ),
      selection: state.selection,
      joinSummary: state.joinSummary,
      reviewer: state.reviewer,
      updatedAt: nowIso(),
    };
  }

  let saveTimer = null;
  function scheduleBatchSave() {
    if (!currentBatchId() || !state.files.length) return;
    window.clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      saveCurrentBatch();
    }, 150);
  }

  async function saveCurrentBatch() {
    const payload = buildBatchPayload();
    if (!payload) return false;
    try {
      await putSavedBatch(payload);
      const counts = globalCounts();
      const entry = {
        batchId: payload.batchId,
        csvFilename: payload.csvFilename,
        updatedAt: payload.updatedAt,
        counts: {
          reportsTotal: state.files.length,
          findingsTotal: counts.total,
          approved: counts.approved,
          flagged: counts.flagged,
          unsure: counts.unsure,
          reviewed: counts.approved + counts.flagged + counts.unsure,
        },
      };
      state.batchIndex = [entry, ...state.batchIndex.filter((item) => item.batchId !== entry.batchId)];
      persistBatchIndex();
      renderSavedBatches();
      return true;
    } catch (e) {
      console.warn('Batch persistence unavailable:', e);
      return false;
    }
  }

  function persistReviewForFile() {
    scheduleBatchSave();
  }

  function renderSavedBatches() {
    if (!el.savedBatches || !el.savedBatchList) return;
    el.savedBatches.style.display = state.batchIndex.length ? 'grid' : 'none';
    el.savedBatchList.innerHTML = '';
    for (const batch of state.batchIndex) {
      const row = document.createElement('div');
      row.className = 'saved-batch-row';
      const counts = batch.counts || {};
      row.innerHTML = `
        <div>
          <strong>${escapeHtml(batch.csvFilename)}</strong>
          <span>${escapeHtml(String(counts.reportsTotal ?? 0))} reports · ${escapeHtml(String(counts.reviewed ?? 0))}/${escapeHtml(String(counts.findingsTotal ?? 0))} reviewed · ${escapeHtml(String(counts.approved ?? 0))} approved · ${escapeHtml(String(counts.flagged ?? 0))} flagged · ${escapeHtml(String(counts.unsure ?? 0))} unsure</span>
        </div>
        <div class="saved-batch-actions">
          <button type="button" data-resume-batch="${escapeHtml(batch.batchId)}">Resume</button>
          <button type="button" class="danger" data-delete-batch="${escapeHtml(batch.batchId)}">Delete</button>
        </div>
      `;
      el.savedBatchList.appendChild(row);
    }
    el.savedBatchList.querySelectorAll('[data-resume-batch]').forEach((button) => {
      button.addEventListener('click', async () => {
        const payload = await getSavedBatch(button.dataset.resumeBatch).catch(() => null);
        if (payload) restoreBatch(payload, { openReview: true });
      });
    });
    el.savedBatchList.querySelectorAll('[data-delete-batch]').forEach((button) => {
      button.addEventListener('click', async () => {
        const batchId = button.dataset.deleteBatch;
        if (!window.confirm('Delete this saved review batch from this browser?')) return;
        await deleteBatch(batchId);
      });
    });
  }

  async function deleteBatch(batchId) {
    try {
      await removeSavedBatch(batchId);
    } catch (e) {
      console.warn('Could not delete saved batch:', e);
    }
    state.batchIndex = state.batchIndex.filter((item) => item.batchId !== batchId);
    persistBatchIndex();
    renderSavedBatches();
  }

  function restoreBatch(payload, { openReview = false } = {}) {
    const isCsvBatch = payload.batchKind ? payload.batchKind === 'csv' : payload.csvText != null;
    state.csv = isCsvBatch
      ? {
          filename: payload.csvFilename,
          text: payload.csvText,
          batchId: payload.batchId,
          headers: payload.csvHeaders,
          records: payload.csvRecords,
          idColumnIndex: payload.idColumnIndex,
          textColumnIndex: payload.textColumnIndex,
        }
      : null;
    state.localBatch = isCsvBatch
      ? null
      : { batchId: payload.batchId, label: payload.csvFilename, kind: payload.batchKind || 'direct' };
    state.manifest = payload.manifest || [];
    state.files = payload.files || [];
    state.invalidResults = payload.invalidResults || [];
    state.extractionSet = payload.extractionSet || [];
    state.reviews = payload.reviews || {};
    state.selection = payload.selection || firstSelection();
    state.joinSummary = payload.joinSummary || null;
    state.reviewer = payload.reviewer || state.reviewer;
    state.prefs.reviewer = state.reviewer;
    persistPreferences();
    if (openReview) enterReview({ preserveSelection: true });
  }

  function extractionSetsEqual(left, right) {
    const normalize = (items) =>
      (items || [])
        .map((item) => `${item.name}\u0000${item.hash}`)
        .sort()
        .join('\n');
    return normalize(left) === normalize(right);
  }

  async function deriveLocalBatchId() {
    const hashes = state.files.map((file) => file.contentHash || file.sha1).sort();
    return sha256Hex(new TextEncoder().encode(hashes.join('\n')));
  }

  async function prepareLocalBatch({ label, kind, offerResume = false }) {
    if (!state.files.length || state.csv) return false;
    const batchId = await deriveLocalBatchId();
    state.localBatch = { batchId, label, kind };
    const saved = await getSavedBatch(batchId).catch(() => null);
    if (!saved) return false;
    if (offerResume && !window.confirm(`Resume the saved review for ${label}?`)) return false;
    state.reviews = saved.reviews || {};
    for (const file of state.files) ensureReview(file.sha1);
    state.selection = saved.selection || firstSelection();
    state.reviewer = saved.reviewer || state.reviewer;
    state.prefs.reviewer = state.reviewer;
    persistPreferences();
    enterReview({ preserveSelection: true });
    return true;
  }

  function findingStableKey(finding, index) {
    const explicitId = finding.id || finding.observation_id || finding.observationId || finding.finding_id;
    if (explicitId) return `id:${explicitId}`;
    return `content:${index}:${finding.finding_name || ''}:${finding.presence || ''}:${finding.report_text || ''}`;
  }

  function preserveApplicableReviews(savedPayload) {
    const oldFiles = new Map((savedPayload.files || []).map((file) => [file.safeId, file]));
    const preserved = {};
    for (const file of state.files) {
      const oldFile = oldFiles.get(file.safeId);
      const oldReview = oldFile ? savedPayload.reviews?.[oldFile.sha1] : null;
      if (!oldFile || !oldReview) continue;
      const oldResponses = new Map();
      (oldFile.data.findings || []).forEach((finding, index) => {
        if (oldReview.responses?.[index]) {
          oldResponses.set(findingStableKey(finding, index), oldReview.responses[index]);
        }
      });
      const responses = {};
      (file.data.findings || []).forEach((finding, index) => {
        const response = oldResponses.get(findingStableKey(finding, index));
        if (response) responses[index] = response;
      });
      preserved[file.sha1] = {
        responses,
        missing: oldReview.missing || [],
        notes: oldReview.notes || '',
      };
    }
    state.reviews = preserved;
    for (const file of state.files) ensureReview(file.sha1);
  }

  function ensureReview(sha1) {
    if (!state.reviews[sha1]) {
      state.reviews[sha1] = { responses: {}, missing: [], notes: '' };
    }
    return state.reviews[sha1];
  }
  function ensureResponse(sha1, findingIndex) {
    const rev = ensureReview(sha1);
    if (!rev.responses[findingIndex]) {
      rev.responses[findingIndex] = {
        status: 'pending',
        comment: '',
        flagTargets: [],
        firstReviewedAt: null,
        updatedAt: null,
      };
    }
    if (!Array.isArray(rev.responses[findingIndex].flagTargets)) rev.responses[findingIndex].flagTargets = [];
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

  function parseCsv(csvText) {
    const rows = [];
    let row = [];
    let field = '';
    let quoted = false;
    for (let i = 0; i < csvText.length; i++) {
      const char = csvText[i];
      if (quoted) {
        if (char === '"') {
          if (csvText[i + 1] === '"') {
            field += '"';
            i++;
          } else {
            quoted = false;
          }
        } else {
          field += char;
        }
        continue;
      }
      if (char === '"' && field.length === 0) {
        quoted = true;
      } else if (char === ',') {
        row.push(field);
        field = '';
      } else if (char === '\r' || char === '\n') {
        row.push(field);
        rows.push(row);
        row = [];
        field = '';
        if (char === '\r' && csvText[i + 1] === '\n') i++;
      } else {
        field += char;
      }
    }
    if (quoted) throw new Error('CSV ends inside a quoted field.');
    if (field.length || row.length) {
      row.push(field);
      rows.push(row);
    }
    if (!rows.length || !rows[0].length || rows[0].every((value) => value === '')) {
      throw new Error('CSV must have a header row.');
    }
    const headers = rows[0];
    const records = rows
      .slice(1)
      .filter((values) => !(values.length === 1 && values[0] === ''))
      .map((values, index) => ({ rowNumber: index + 2, values }));
    return { headers, records };
  }

  function normalizeCsvReportText(reportText) {
    const original = String(reportText || '');
    const trimmed = original.trim();
    const marker = /(?<![A-Za-z])(FINDINGS|IMPRESSION)(?![A-Za-z])(\s*:\s*|\s+)/g;
    const normalized = trimmed.replace(marker, (match, header, separator, offset) => {
      if (!separator.includes(':') && (separator === ' ' || separator === '\t')) {
        const nextChar = original.slice(offset + match.length, offset + match.length + 1);
        if (['.', ',', ';', ')'].includes(nextChar)) return match;
      }
      const prefix = offset === 0 ? '' : '\n\n';
      return `${prefix}${header.toUpperCase()}:\n`;
    });
    return normalized.replace(/[ \t]+\n\n(FINDINGS|IMPRESSION):/g, '\n\n$1:').trim();
  }

  function csvValue(record, columnIndex) {
    return columnIndex < 0 ? '' : record.values[columnIndex] || '';
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

  function relativePathFor(file) {
    return String(file.webkitRelativePath || file.reviewerRelativePath || file.name || '').replace(/^\/+/, '');
  }

  function isStagedReportFile(file) {
    return relativePathFor(file)
      .split('/')
      .some((part) => part === '_staged_reports');
  }

  async function loadFileList(fileList, { replace = false } = {}) {
    const errors = [];
    if (replace) {
      state.files = [];
      state.manifest = [];
      state.invalidResults = [];
      state.extractionSet = [];
      state.reviews = {};
    }
    const seenFiles = new Set(state.files.map((f) => `${f.name}\u0000${f.contentHash || f.sha1}`));

    // Partition extraction JSONs and source text, retaining staged reports as
    // a separate, higher-precedence source.
    const textByBase = new Map();
    const stagedTextByBase = new Map();
    const jsonFiles = [];
    for (const file of fileList) {
      if (!file.name) continue;
      const lower = file.name.toLowerCase();
      if (lower === 'batch_results.jsonl' || lower === 'extraction_reviewer.html') continue;
      if (lower.endsWith('.txt') || lower.endsWith('.md')) {
        const target = isStagedReportFile(file) ? stagedTextByBase : textByBase;
        target.set(basenameWithoutExt(file.name), file);
      } else if (lower.endsWith('.json')) {
        jsonFiles.push(file);
      }
    }

    for (const file of jsonFiles) {
      try {
        const text = await file.text();
        const bytes = new TextEncoder().encode(text);
        const sha1 = (await sha1Hex(bytes)).slice(0, 12);
        const contentHash = await sha256Hex(bytes);
        const fileKey = `${file.name}\u0000${contentHash}`;
        if (seenFiles.has(fileKey)) continue;
        const extractionNamed = /\.(extracted|coded)\.json$/i.test(file.name);
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          if (extractionNamed) {
            errors.push(`${file.name}: invalid JSON`);
            state.invalidResults.push({ name: file.name, reason: 'invalid JSON' });
            state.extractionSet.push({ name: file.name, hash: contentHash });
          }
          continue;
        }
        if (isCsvManifest(data)) {
          state.manifest = data;
          continue;
        }
        if (!data || !Array.isArray(data.findings)) {
          if (extractionNamed) {
            errors.push(`${file.name}: missing findings[]`);
            state.invalidResults.push({ name: file.name, reason: 'missing findings[]' });
            state.extractionSet.push({ name: file.name, hash: contentHash });
          }
          continue;
        }
        state.extractionSet.push({ name: file.name, hash: contentHash });

        // Pair with a sibling .txt / .md report; fall back to an embedded field
        // or a reconstruction pieced together from the extraction output.
        let reportText = null;
        let reportSourceName = null;
        let reportIsReconstructed = false;
        let reportSourceKind = null;
        let siblingReportText = null;
        const safeId = basenameWithoutExt(file.name);
        const staged = stagedTextByBase.get(safeId);
        const sibling = textByBase.get(safeId);
        if (staged) {
          try {
            reportText = await staged.text();
            reportSourceName = relativePathFor(staged);
            reportSourceKind = 'staged';
          } catch (e) {
            errors.push(`${staged.name}: failed to read (${e.message || e})`);
          }
        } else if (sibling) {
          try {
            siblingReportText = await sibling.text();
            reportText = cleanReportText(siblingReportText);
            reportSourceName = relativePathFor(sibling);
            reportSourceKind = 'sibling';
          } catch (e) {
            errors.push(`${sibling.name}: failed to read (${e.message || e})`);
          }
        } else if (typeof data.report_text === 'string' && data.report_text.trim()) {
          reportText = cleanReportText(data.report_text);
          reportSourceName = `${file.name} (embedded)`;
          reportSourceKind = 'embedded';
        } else {
          const stitched = reconstructReportFromJson(data);
          if (stitched) {
            reportText = cleanReportText(stitched);
            reportSourceName = `reconstructed from ${file.name}`;
            reportIsReconstructed = true;
            reportSourceKind = 'reconstructed';
          }
        }

        seenFiles.add(fileKey);
        state.files.push({
          sha1,
          contentHash,
          name: file.name,
          safeId,
          data,
          collapsed: false,
          reportText,
          reportSourceName,
          reportSourceKind,
          reportIsReconstructed,
          siblingReportText,
        });
        ensureReview(sha1);
      } catch (e) {
        errors.push(`${file.name}: ${e.message || e}`);
      }
    }
    state.files.sort((a, b) => a.name.localeCompare(b.name));
    state.extractionSet.sort((a, b) => a.name.localeCompare(b.name));
    return errors;
  }

  async function handleLoadedFiles(fileList, { label = null, kind = 'direct', offerResume = false } = {}) {
    const errors = await loadFileList(fileList);
    showLoadErrors(errors);
    if (!state.files.length) return;

    const batchLabel = label || (fileList.length === 1 ? fileList[0].name : `Direct files (${fileList.length})`);
    if (await prepareLocalBatch({ label: batchLabel, kind, offerResume })) return;

    const wasOnLanding = !isInApp();
    if (wasOnLanding) {
      const auto = findNextPending(null) || firstSelection();
      state.selection = auto;
      el.landing.style.display = 'none';
      el.app.style.display = 'grid';
    }
    applyAutoCollapse();
    render();
    scheduleBatchSave();
    if (wasOnLanding) maybeShowGuideOnFirstVisit();
  }

  function enterReview({ preserveSelection = false } = {}) {
    if (!state.files.length) return;
    if (!preserveSelection) state.selection = findNextPending(null) || firstSelection();
    el.landing.style.display = 'none';
    el.app.style.display = 'grid';
    applyAutoCollapse();
    render();
    scheduleBatchSave();
    maybeShowGuideOnFirstVisit();
  }

  function setWizardStep(step) {
    state.wizardStep = step;
    el.wizardSteps.forEach((section, index) => {
      section.style.display = index + 1 === step ? 'grid' : 'none';
    });
    el.progressSteps.forEach((item, index) => {
      item.classList.toggle('active', index + 1 === step);
      item.classList.toggle('complete', index + 1 < step);
    });
  }

  function setCsvError(message) {
    el.csvErrors.style.display = message ? 'block' : 'none';
    el.csvErrors.textContent = message || '';
  }

  function updateColumnMapping() {
    if (!state.csv) return;
    state.csv.idColumnIndex = Number(el.idColumnSelect.value);
    state.csv.textColumnIndex = Number(el.textColumnSelect.value);
    const valid =
      Number.isInteger(state.csv.idColumnIndex) &&
      Number.isInteger(state.csv.textColumnIndex) &&
      state.csv.idColumnIndex !== state.csv.textColumnIndex;
    el.csvNextBtn.disabled = !valid;
    if (valid) {
      state.prefs.lastColumnMapping = {
        idColumn: state.csv.headers[state.csv.idColumnIndex],
        textColumn: state.csv.headers[state.csv.textColumnIndex],
      };
      persistPreferences();
    }
    setCsvError(valid ? '' : 'Choose two different columns.');
  }

  function renderColumnPicker() {
    const csv = state.csv;
    if (!csv) return;
    const options = csv.headers
      .map((header, index) => `<option value="${index}">${escapeHtml(header || `(column ${index + 1})`)}</option>`)
      .join('');
    el.idColumnSelect.innerHTML = options;
    el.textColumnSelect.innerHTML = options;
    el.idColumnSelect.value = String(csv.idColumnIndex);
    el.textColumnSelect.value = String(csv.textColumnIndex);
    el.columnPicker.style.display = csv.headers.length === 2 ? 'none' : 'grid';
    updateColumnMapping();
  }

  async function selectCsvFile(file) {
    setCsvError('');
    if (!file || !file.name.toLowerCase().endsWith('.csv')) {
      setCsvError('Select one .csv file.');
      return;
    }
    try {
      const rawBytes = new Uint8Array(await file.arrayBuffer());
      const batchId = await sha256Hex(rawBytes);
      const decoded = new TextDecoder('utf-8', { fatal: true }).decode(rawBytes);
      const text = decoded.replace(/^\uFEFF/, '');
      const parsed = parseCsv(text);
      if (parsed.headers.length < 2) throw new Error('CSV must have at least two columns.');
      const lastMapping = state.prefs.lastColumnMapping;
      const preferredIdIndex = lastMapping ? parsed.headers.indexOf(lastMapping.idColumn) : -1;
      const preferredTextIndex = lastMapping ? parsed.headers.indexOf(lastMapping.textColumn) : -1;
      const idColumnIndex = parsed.headers.length === 2 || preferredIdIndex < 0 ? 0 : preferredIdIndex;
      const textColumnIndex = parsed.headers.length === 2 || preferredTextIndex < 0 ? 1 : preferredTextIndex;
      state.csv = {
        filename: file.name,
        rawBytes,
        text,
        batchId,
        headers: parsed.headers,
        records: parsed.records,
        idColumnIndex,
        textColumnIndex,
      };
      state.localBatch = null;
      const savedEntry = state.batchIndex.find((entry) => entry.batchId === batchId);
      if (savedEntry) {
        const saved = await getSavedBatch(batchId).catch(() => null);
        if (saved) {
          if (window.confirm(`Resume the saved review for ${file.name}?`)) {
            restoreBatch(saved, { openReview: true });
            return;
          }
          state.savedBatchCandidate = saved;
        } else {
          state.batchIndex = state.batchIndex.filter((entry) => entry.batchId !== batchId);
          persistBatchIndex();
          renderSavedBatches();
        }
      } else {
        state.savedBatchCandidate = null;
      }
      el.csvSelection.style.display = 'block';
      el.csvSelection.textContent = `${file.name} · ${parsed.records.length} report row(s)`;
      renderColumnPicker();
    } catch (e) {
      state.csv = null;
      el.csvSelection.style.display = 'none';
      el.columnPicker.style.display = 'none';
      el.csvNextBtn.disabled = true;
      setCsvError(e.message || String(e));
    }
  }

  function sourceBannerHtml(file) {
    const labels = {
      staged: 'Staged report text',
      csv: 'Normalized CSV text',
      sibling: 'Paired report text',
      embedded: 'Embedded report text',
      reconstructed: 'Reconstructed text',
    };
    const label = labels[file.reportSourceKind] || 'Source text unavailable';
    return `<div class="source-banner"><strong>Source:</strong> ${escapeHtml(label)}${file.reportSourceName ? ` · ${escapeHtml(file.reportSourceName)}` : ''}</div>`;
  }

  function sourceReportHtml(file, { quote = '', textId = 'sourceReportText', captureHint = false } = {}) {
    if (!file.reportText) {
      return `<div class="missing-report missing-report-absent">
        <div class="section-title">Source report</div>
        <p class="hint" style="margin:0;">No source report text is available for this extraction.</p>
      </div>`;
    }
    const quoteIndex = quote ? file.reportText.indexOf(quote) : -1;
    const reportHtml =
      quoteIndex >= 0
        ? escapeHtml(file.reportText.slice(0, quoteIndex)) +
          `<mark class="current-quote">${escapeHtml(quote)}</mark>` +
          escapeHtml(file.reportText.slice(quoteIndex + quote.length))
        : escapeHtml(file.reportText);
    const warning = file.reportIsReconstructed
      ? '<div class="source-report-warning">This report was reconstructed from extraction snippets and may be incomplete.</div>'
      : quote && quoteIndex < 0
        ? '<div class="source-report-warning">The evidence quote was not found verbatim in this source report.</div>'
        : '';
    return `<div class="missing-report">
      <div class="missing-report-head">
        <div class="section-title">Source report</div>
        ${file.reportSourceName ? `<span class="report-source">${escapeHtml(file.reportSourceName)}</span>` : ''}
        ${file.reportIsReconstructed ? '<span class="report-reconstructed">reconstructed</span>' : ''}
      </div>
      ${sourceBannerHtml(file)}
      ${warning}
      <div class="missing-report-text" id="${textId}">${reportHtml}</div>
      ${captureHint ? '<div class="hint">Highlight any text above to capture it as the supporting quote. Re-highlight to replace.</div>' : ''}
    </div>`;
  }

  function resolveWizardJoin() {
    const csv = state.csv;
    const manifestBySafeId = new Map(state.manifest.map((entry) => [entry.safe_id, entry]));
    const rowsByNumber = new Map(csv.records.map((record) => [record.rowNumber, record]));
    const consumedRows = new Set();
    let matched = 0;
    let unmatchedExtractions = 0;
    let invalid = state.invalidResults.length;

    for (const file of state.files) {
      file.sourceId = null;
      file.csvRowNumber = null;
      file.joinStatus = 'unmatched';
      const entry = manifestBySafeId.get(file.safeId);
      if (!entry) {
        unmatchedExtractions++;
        continue;
      }
      const record = rowsByNumber.get(entry.row_number);
      if (!record) {
        unmatchedExtractions++;
        continue;
      }
      consumedRows.add(record.rowNumber);
      file.sourceId = entry.source_id;
      file.csvRowNumber = entry.row_number;
      const csvSourceId = String(csvValue(record, csv.idColumnIndex)).trim();
      if (csvSourceId !== entry.source_id) {
        file.joinStatus = 'invalid';
        file.joinError = `CSV row ${entry.row_number} identifier “${csvSourceId}” does not match manifest source_id “${entry.source_id}”.`;
        invalid++;
        continue;
      }
      file.joinStatus = 'matched';
      matched++;
      if (file.reportSourceKind !== 'staged') {
        file.reportText = normalizeCsvReportText(csvValue(record, csv.textColumnIndex));
        file.reportSourceName = `${csv.filename} · row ${record.rowNumber}`;
        file.reportSourceKind = 'csv';
        file.reportIsReconstructed = false;
      }
    }

    const unmatchedRows = csv.records.filter((record) => !consumedRows.has(record.rowNumber)).length;
    const summary = {
      matched,
      unmatched: unmatchedExtractions + unmatchedRows,
      invalid,
      unmatchedExtractions,
      unmatchedRows,
      quoteCheck: null,
    };
    const spotCheckFile = state.files.find(
      (file) =>
        file.joinStatus === 'matched' && file.data.findings.some((finding) => String(finding.report_text || '').length),
    );
    if (spotCheckFile) {
      const quote = String(spotCheckFile.data.findings.find((finding) => finding.report_text)?.report_text || '');
      summary.quoteCheck = {
        ok: Boolean(spotCheckFile.reportText && spotCheckFile.reportText.includes(quote)),
        filename: spotCheckFile.name,
        sourceKind: spotCheckFile.reportSourceKind,
      };
    }
    state.joinSummary = summary;
    return summary;
  }

  function renderJoinSummary() {
    const summary = state.joinSummary;
    if (!summary) return;
    el.joinSummary.innerHTML = `
      <div class="join-count matched"><strong>${summary.matched}</strong><span>Matched</span></div>
      <div class="join-count unmatched"><strong>${summary.unmatched}</strong><span>Unmatched</span></div>
      <div class="join-count invalid"><strong>${summary.invalid}</strong><span>Invalid</span></div>
    `;
    if (!summary.quoteCheck) {
      el.quoteCheck.className = 'quote-check';
      el.quoteCheck.textContent = 'Quote spot-check unavailable: no matched report contains an extraction quote.';
    } else if (summary.quoteCheck.ok) {
      el.quoteCheck.className = 'quote-check ok';
      el.quoteCheck.textContent = `Quote spot-check passed for ${summary.quoteCheck.filename} using ${summary.quoteCheck.sourceKind} text.`;
    } else {
      el.quoteCheck.className = 'quote-check warning';
      el.quoteCheck.textContent = `Warning: the first extraction quote in ${summary.quoteCheck.filename} was not found verbatim in the resolved source text. Check the selected text column or normalization.`;
    }
    el.startReviewBtn.disabled = !state.csv || !state.files.length;
  }

  async function selectResultsFiles(files) {
    const savedCandidate = state.savedBatchCandidate;
    const errors = await loadFileList(files, { replace: true });
    showLoadErrors(errors);
    if (!state.files.length) {
      el.resultsSelection.style.display = 'none';
      el.resultsNextBtn.disabled = true;
      return;
    }
    if (savedCandidate && !extractionSetsEqual(savedCandidate.extractionSet, state.extractionSet)) {
      const replace = window.confirm(
        'This extraction folder differs from the saved batch. Replace the saved extraction data? Existing responses will be preserved where finding identifiers still match.',
      );
      if (!replace) {
        restoreBatch(savedCandidate, { openReview: true });
        return;
      }
      preserveApplicableReviews(savedCandidate);
    }
    state.savedBatchCandidate = null;
    resolveWizardJoin();
    const folderName = relativePathFor(files[0]).split('/')[0] || 'selected folder';
    el.resultsSelection.style.display = 'block';
    el.resultsSelection.textContent = `${folderName} · ${state.files.length} valid extraction file(s)`;
    el.resultsNextBtn.disabled = false;
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
              f.reviewerRelativePath = entry.fullPath || f.name;
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
    scheduleBatchSave();
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
      unsure = 0,
      missingCount = 0;
    for (const file of state.files) {
      total += file.data.findings.length;
      const rev = ensureReview(file.sha1);
      for (const r of Object.values(rev.responses)) {
        if (r.status === 'approved') approved++;
        else if (r.status === 'flagged') flagged++;
        else if (r.status === 'unsure') unsure++;
      }
      missingCount += rev.missing.length;
    }
    return { total, approved, flagged, unsure, pending: total - approved - flagged - unsure, missingCount };
  }

  function fileCounts(file) {
    const rev = ensureReview(file.sha1);
    let approved = 0,
      flagged = 0,
      unsure = 0,
      draft = 0;
    for (let i = 0; i < file.data.findings.length; i++) {
      const r = rev.responses[i];
      if (!r) continue;
      if (r.status === 'approved') approved++;
      else if (r.status === 'flagged') flagged++;
      else if (r.status === 'unsure') unsure++;
      else if ((r.comment || '').trim()) draft++;
    }
    const total = file.data.findings.length;
    return {
      total,
      approved,
      flagged,
      unsure,
      draft,
      missing: rev.missing.length,
      done: approved + flagged + unsure,
    };
  }

  // ---------- Rendering ----------
  function render() {
    renderSidebar();
    renderMain();
  }

  function renderSidebar() {
    updateReviewerUi();
    const c = globalCounts();
    const icon = {
      pending: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>`,
      approved: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 12.5l5 5 10-11" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
      flagged: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3v18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/><path d="M6 4h12l-3 4.5 3 4.5H6z" fill="currentColor" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/></svg>`,
      unsure: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9.4 9.4a2.8 2.8 0 115 1.7c-.9.8-1.7 1.2-1.7 2.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12.2" cy="17" r="1.1" fill="currentColor"/></svg>`,
      missed: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v16M4 12h16" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>`,
    };
    el.counts.innerHTML = `
      <span class="pill" title="${c.pending} pending"><span class="pill-icon pending">${icon.pending}</span><strong>${c.pending}</strong></span>
      <span class="pill" title="${c.approved} approved"><span class="pill-icon approved">${icon.approved}</span><strong>${c.approved}</strong></span>
      <span class="pill" title="${c.flagged} flagged"><span class="pill-icon flagged">${icon.flagged}</span><strong>${c.flagged}</strong></span>
      <span class="pill" title="${c.unsure} unsure"><span class="pill-icon unsure">${icon.unsure}</span><strong>${c.unsure}</strong></span>
      <span class="pill" title="${c.missingCount} missed (logged by reviewer)"><span class="pill-icon missed">${icon.missed}</span><strong>${c.missingCount}</strong></span>
    `;
    el.exportBtn.disabled = !canExport();
    el.exportBtn.title = canExport()
      ? 'Download one combined review JSON'
      : 'Set a reviewer name before downloading review JSON.';
    el.exportMenuBtn.disabled = !canExportZip();
    el.exportZipBtn.disabled = !canExportZip();

    el.groupList.innerHTML = '';
    for (const file of state.files) {
      el.groupList.appendChild(renderGroup(file));
    }
  }

  function renderGroup(file) {
    const counts = fileCounts(file);
    const rev = ensureReview(file.sha1);
    const exam = file.data.exam_info || {};
    const group = document.createElement('div');
    group.className = 'group' + (file.collapsed ? ' collapsed' : '');

    const header = document.createElement('div');
    header.className = 'group-header';
    const metaBits = [
      exam.study_description || '',
      `${counts.done}/${counts.total}`,
      counts.flagged ? `${counts.flagged} flagged` : '',
      counts.unsure ? `${counts.unsure} unsure` : '',
      counts.missing ? `${counts.missing} missing` : '',
    ]
      .filter(Boolean)
      .join(' · ');
    header.innerHTML = `
      <span class="group-chevron">${file.collapsed ? '\u25B8' : '\u25BE'}</span>
      <div style="min-width:0; flex:1;">
        <div class="group-title" title="${escapeHtml(file.name)}">${rev.notes?.trim() ? '<span class="note-dot" title="Report note exists"></span>' : ''}${escapeHtml(file.name)}${file.joinStatus === 'invalid' ? '<span class="invalid-join-chip">Invalid join</span>' : ''}</div>
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
      status === 'unsure' ? 'status-unsure done-unsure' : '',
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
      el.toolbarJoinWarning.style.display = 'none';
      return;
    }
    el.toolbarJoinWarning.style.display = file.joinStatus === 'invalid' ? '' : 'none';
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

  function reportNoteHtml(file) {
    const notes = ensureReview(file.sha1).notes || '';
    return `
      <div class="report-note ${notes.trim() ? 'expanded' : ''}">
        <button type="button" id="reportNoteToggle" class="report-note-toggle">
          ${notes.trim() ? 'Edit report note' : '＋ Add report note'}
        </button>
        <textarea id="reportNoteBox" rows="2" placeholder="Notes that apply to this report" ${notes.trim() ? '' : 'hidden'}>${escapeHtml(notes)}</textarea>
      </div>
    `;
  }

  function wireReportNote(file) {
    const toggle = document.getElementById('reportNoteToggle');
    const box = document.getElementById('reportNoteBox');
    if (!toggle || !box) return;
    toggle.addEventListener('click', () => {
      box.hidden = false;
      box.focus();
    });
    box.addEventListener('input', () => {
      const rev = ensureReview(file.sha1);
      rev.notes = box.value;
      persistReviewForFile(file.sha1);
      renderSidebar();
      if (!box.value) {
        box.hidden = true;
        toggle.textContent = '＋ Add report note';
      } else {
        toggle.textContent = 'Edit report note';
      }
    });
  }

  function flagTargetsHtml(response) {
    if (!['flagged', 'unsure'].includes(response.status)) return '';
    const selected = new Set(response.flagTargets || []);
    return `
      <div class="flag-targets">
        <div class="flag-targets-label">What&rsquo;s in question</div>
        <div class="flag-target-chips">
          ${FLAG_TARGETS.map(
            ([token, label]) => `
              <button type="button" class="flag-target-chip ${selected.has(token) ? 'active' : ''}" data-flag-target="${token}" aria-pressed="${selected.has(token)}">${escapeHtml(label)}</button>
            `,
          ).join('')}
        </div>
      </div>
    `;
  }

  function renderFindingView(file, finding, idx) {
    const response = ensureResponse(file.sha1, idx);
    const draft = response.status === 'pending' && (response.comment || '').trim();
    const titleStatus =
      response.status === 'approved'
        ? 'approved'
        : response.status === 'flagged'
          ? 'flagged'
          : response.status === 'unsure'
            ? 'unsure'
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
                <div class="section-title">Evidence quote</div>
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
            ${reportNoteHtml(file)}
            ${sourceReportHtml(file, { quote: finding.report_text || '' })}
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
                <textarea id="commentBox" placeholder="Optional review notes. Drafts save automatically."></textarea>
              </div>
              <div style="display:flex; gap:8px; flex-wrap:wrap; justify-content:space-between;">
                <button type="button" id="clearBtn">Clear</button>
                <div style="display:flex; gap:8px;">
                  <button type="button" class="success ${draft ? '' : 'is-default'}" id="approveBtn">Approve (A)</button>
                  <button type="button" class="warning ${draft ? 'is-default' : ''}" id="flagBtn">Flag (F)</button>
                  <button type="button" class="unsure" id="unsureBtn">Unsure (U)</button>
                </div>
              </div>
              ${flagTargetsHtml(response)}
              <div class="hint">Arrow Up/Down moves between findings. A approves, F flags, U marks unsure. Shortcuts pause while typing.</div>
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
    document.getElementById('unsureBtn').addEventListener('click', markUnsureCurrent);
    el.content.querySelectorAll('[data-flag-target]').forEach((button) => {
      button.addEventListener('click', () => {
        const token = button.dataset.flagTarget;
        const targets = new Set(response.flagTargets || []);
        if (targets.has(token)) targets.delete(token);
        else targets.add(token);
        response.flagTargets = FLAG_TARGETS.map(([knownToken]) => knownToken).filter((knownToken) =>
          targets.has(knownToken),
        );
        response.updatedAt = nowIso();
        button.classList.toggle('active', targets.has(token));
        button.setAttribute('aria-pressed', String(targets.has(token)));
        persistReviewForFile(file.sha1);
      });
    });
    document.getElementById('clearBtn').addEventListener('click', () => {
      response.comment = '';
      response.updatedAt = nowIso();
      persistReviewForFile(file.sha1);
      render();
      const b = document.getElementById('commentBox');
      if (b) b.focus();
    });
    wireReportNote(file);
    const currentQuote = document.querySelector('#sourceReportText mark.current-quote');
    if (currentQuote) {
      window.requestAnimationFrame(() => {
        const report = document.getElementById('sourceReportText');
        if (report) report.scrollTop = currentQuote.offsetTop - report.clientHeight / 2;
      });
    }
  }

  function statusChipHtml(response, draft) {
    if (response.status === 'approved') return `<span class="status-chip approved">Approved</span>`;
    if (response.status === 'flagged') return `<span class="status-chip flagged">Flagged</span>`;
    if (response.status === 'unsure') return `<span class="status-chip unsure">Unsure</span>`;
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

    const reportBlock = sourceReportHtml(file, { textId: 'missReportText', captureHint: true });

    el.content.innerHTML = `
      <div class="missing-panel">
        <div class="missing-panel-header">
          <h2>Missing findings &mdash; ${escapeHtml(file.name)}</h2>
          <p class="hint" style="margin:0;">Log findings the extractor should have produced but didn&rsquo;t. Saved under <code>missing_findings</code> in this file&rsquo;s review JSON.</p>
        </div>
        ${reportNoteHtml(file)}
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
    wireReportNote(file);
  }

  // ---------- Actions ----------
  function setCurrentVerdict(status) {
    const sel = state.selection;
    if (sel.sha1 == null || sel.findingIndex == null) return;
    const r = ensureResponse(sel.sha1, sel.findingIndex);
    const now = nowIso();
    if (!r.firstReviewedAt) r.firstReviewedAt = now;
    r.status = status;
    if (status === 'approved') r.flagTargets = [];
    r.updatedAt = now;
    persistReviewForFile(sel.sha1);
    moveToNextPendingOrStay();
  }

  function approveCurrent() {
    setCurrentVerdict('approved');
  }

  function submitFlag() {
    setCurrentVerdict('flagged');
  }

  function markUnsureCurrent() {
    setCurrentVerdict('unsure');
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
    return Boolean((state.reviewer || '').trim() && state.files.length);
  }

  function canExportZip() {
    if (!canExport()) return false;
    return state.files.some((file) => {
      const rev = ensureReview(file.sha1);
      return Object.keys(rev.responses).length || rev.missing.length || (rev.notes || '').trim();
    });
  }

  function buildReviewJson(file) {
    const rev = ensureReview(file.sha1);
    const findings = file.data.findings || [];
    const responses = [];
    let approved = 0,
      flagged = 0,
      unsure = 0;
    for (let i = 0; i < findings.length; i++) {
      const r = rev.responses[i];
      const status = r ? r.status : 'pending';
      if (status === 'approved') approved++;
      else if (status === 'flagged') flagged++;
      else if (status === 'unsure') unsure++;
      responses.push({
        finding_index: i,
        finding_name: findings[i].finding_name || '',
        presence: findings[i].presence || null,
        status,
        comment: r ? r.comment || '' : '',
        flag_targets: r && Array.isArray(r.flagTargets) ? r.flagTargets : [],
        first_reviewed_at: r ? r.firstReviewedAt : null,
        updated_at: r ? r.updatedAt : null,
      });
    }
    const exam = file.data.exam_info || {};
    const joinInvalid = file.joinStatus === 'invalid';
    return {
      app_version: APP_VERSION,
      source_file: file.name,
      source_sha1: file.sha1,
      source_id: file.sourceId || null,
      csv_row_number: joinInvalid ? null : file.csvRowNumber || null,
      join_invalid: joinInvalid,
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
        unsure,
        pending: findings.length - approved - flagged - unsure,
        missing_findings_count: rev.missing.length,
      },
      responses,
      report_level_notes: rev.notes || '',
      missing_findings: rev.missing,
    };
  }

  function reportWasReviewed(file) {
    const rev = ensureReview(file.sha1);
    return (
      Object.values(rev.responses).some((response) => response.status !== 'pending') ||
      rev.missing.length > 0 ||
      Boolean((rev.notes || '').trim())
    );
  }

  function buildCombinedReviewJson() {
    const exportedAt = nowIso();
    const reports = state.files.map((file) => {
      const review = buildReviewJson(file);
      return {
        source_file: review.source_file,
        source_sha1: review.source_sha1,
        source_id: review.source_id,
        csv_row_number: review.csv_row_number,
        join_invalid: review.join_invalid,
        source_exam: review.source_exam,
        summary: review.summary,
        responses: review.responses,
        report_level_notes: review.report_level_notes,
        missing_findings: review.missing_findings,
      };
    });
    const counts = globalCounts();
    return {
      app_version: APP_VERSION,
      kind: 'extraction-review-batch',
      batch: {
        csv_filename: state.csv?.filename || null,
        csv_sha256: state.csv?.batchId || null,
        batch_id: state.csv?.batchId || null,
      },
      reviewer: { identifier: state.reviewer || '' },
      exported_at: exportedAt,
      batch_summary: {
        reports_total: state.files.length,
        reports_reviewed: state.files.filter(reportWasReviewed).length,
        findings_total: counts.total,
        approved: counts.approved,
        flagged: counts.flagged,
        unsure: counts.unsure,
        pending: counts.pending,
        missing_findings_count: counts.missingCount,
        invalid_joins: state.files.filter((file) => file.joinStatus === 'invalid').length,
      },
      reports,
    };
  }

  function downloadStamp() {
    const now = new Date();
    return (
      [now.getFullYear(), String(now.getMonth() + 1).padStart(2, '0'), String(now.getDate()).padStart(2, '0')].join(
        '',
      ) +
      '-' +
      [String(now.getHours()).padStart(2, '0'), String(now.getMinutes()).padStart(2, '0')].join('')
    );
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function exportCombinedJson() {
    if (!canExport()) return;
    const payload = buildCombinedReviewJson();
    const blob = new Blob([JSON.stringify(payload, null, 2) + '\n'], { type: 'application/json' });
    downloadBlob(blob, `review-${slugify(state.reviewer)}-${downloadStamp()}.json`);
  }

  function reviewFilenameFor(file) {
    const base = file.name.replace(/\.json$/i, '');
    return `${base}.review.json`;
  }

  function exportZip() {
    if (!canExportZip()) return;
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
    downloadBlob(blob, `reviews-${slugify(state.reviewer)}-${downloadStamp()}.zip`);
  }

  // ---------- Keyboard ----------
  function onGlobalKey(ev) {
    const t = ev.target;
    const editing = t && (t.tagName === 'TEXTAREA' || t.tagName === 'INPUT' || t.isContentEditable);
    if (editing || ev.ctrlKey || ev.metaKey || ev.altKey || el.reviewerDialog?.open) return;
    if (!isInApp()) return;
    const k = ev.key.toLowerCase();
    if (k === 'a') {
      ev.preventDefault();
      approveCurrent();
      return;
    }
    if (k === 'f') {
      ev.preventDefault();
      submitFlag();
      return;
    }
    if (k === 'u') {
      ev.preventDefault();
      markUnsureCurrent();
      return;
    }
    if (k === 'arrowup') {
      ev.preventDefault();
      const s = stepFinding(state.selection, -1);
      if (s) {
        setSelection(s);
        render();
      }
      return;
    }
    if (k === 'arrowdown') {
      ev.preventDefault();
      const s = stepFinding(state.selection, 1);
      if (s) {
        setSelection(s);
        render();
      }
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
    state.prefs.guideSeen = true;
    persistPreferences();
  }
  function closeHelp() {
    if (el.helpDialog && el.helpDialog.open) el.helpDialog.close();
  }
  function hasSeenGuide() {
    return Boolean(state.prefs.guideSeen);
  }
  function maybeShowGuideOnFirstVisit() {
    if (hasSeenGuide() || el.reviewerDialog?.open) return;
    openHelp();
  }

  // ---------- Wiring ----------
  loadPreferences();
  loadBatchIndex();
  updateReviewerUi();
  renderSavedBatches();
  if (!state.reviewer) window.setTimeout(openReviewerDialog, 0);

  function bindDropzone(dropzone, onDrop) {
    ['dragenter', 'dragover'].forEach((eventName) =>
      dropzone.addEventListener(eventName, (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        dropzone.classList.add('drag');
      }),
    );
    ['dragleave', 'drop'].forEach((eventName) =>
      dropzone.addEventListener(eventName, (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        dropzone.classList.remove('drag');
      }),
    );
    dropzone.addEventListener('drop', onDrop);
  }

  el.pickCsvBtn.addEventListener('click', () => el.csvInput.click());
  el.csvInput.addEventListener('change', async (ev) => {
    await selectCsvFile(ev.target.files?.[0]);
    ev.target.value = '';
  });
  bindDropzone(el.csvDropzone, async (ev) => {
    const files = await readFilesFromDataTransfer(ev.dataTransfer);
    await selectCsvFile(files.find((file) => file.name.toLowerCase().endsWith('.csv')));
  });
  el.idColumnSelect.addEventListener('change', updateColumnMapping);
  el.textColumnSelect.addEventListener('change', updateColumnMapping);
  el.csvNextBtn.addEventListener('click', () => {
    updateColumnMapping();
    if (!el.csvNextBtn.disabled) setWizardStep(2);
  });

  el.pickResultsBtn.addEventListener('click', () => el.folderInput.click());
  el.pickFilesBtn.addEventListener('click', () => el.filesInput.click());
  el.pickCompatFolderBtn.addEventListener('click', () => el.compatFolderInput.click());
  el.folderInput.addEventListener('change', async (ev) => {
    const files = Array.from(ev.target.files || []);
    ev.target.value = '';
    await selectResultsFiles(files);
  });
  bindDropzone(el.resultsDropzone, async (ev) => {
    const files = await readFilesFromDataTransfer(ev.dataTransfer);
    await selectResultsFiles(files);
  });
  el.resultsBackBtn.addEventListener('click', () => setWizardStep(1));
  el.resultsNextBtn.addEventListener('click', () => {
    resolveWizardJoin();
    renderJoinSummary();
    setWizardStep(3);
  });
  el.confirmBackBtn.addEventListener('click', () => setWizardStep(2));
  el.startReviewBtn.addEventListener('click', enterReview);

  el.filesInput.addEventListener('change', async (ev) => {
    const files = Array.from(ev.target.files || []);
    ev.target.value = '';
    await handleLoadedFiles(files);
  });
  if (el.compatFolderInput) {
    el.compatFolderInput.addEventListener('change', async (ev) => {
      const files = Array.from(ev.target.files || []);
      ev.target.value = '';
      const label = relativePathFor(files[0]).split('/')[0] || 'Direct folder';
      await handleLoadedFiles(files, { label, kind: 'direct' });
    });
  }

  el.landingReviewerChange.addEventListener('click', openReviewerDialog);
  el.reviewerChipChange.addEventListener('click', openReviewerDialog);
  el.reviewerChip.addEventListener('click', (ev) => {
    if (ev.target !== el.reviewerChipChange) openReviewerDialog();
  });
  el.reviewerForm.addEventListener('submit', (ev) => {
    ev.preventDefault();
    saveReviewerName();
  });
  el.reviewerCancelBtn.addEventListener('click', () => el.reviewerDialog.close());
  el.reviewerDialog.addEventListener('click', (ev) => {
    if (ev.target === el.reviewerDialog) el.reviewerDialog.close();
  });
  el.reviewerDialog.addEventListener('close', () => {
    updateReviewerUi();
    if (isInApp()) maybeShowGuideOnFirstVisit();
  });

  el.addFilesBtn.addEventListener('click', () => el.filesInput.click());
  el.exportBtn.addEventListener('click', exportCombinedJson);
  el.exportMenuBtn.addEventListener('click', () => {
    const opening = el.exportMenu.hidden;
    el.exportMenu.hidden = !opening;
    el.exportMenuBtn.setAttribute('aria-expanded', String(opening));
  });
  el.exportZipBtn.addEventListener('click', () => {
    el.exportMenu.hidden = true;
    el.exportMenuBtn.setAttribute('aria-expanded', 'false');
    exportZip();
  });
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
          reviewerRelativePath: path,
          async text() {
            return text;
          },
        });
      }
      if (files.length) {
        await handleLoadedFiles(files, {
          label: 'Embedded review bundle',
          kind: 'embedded',
          offerResume: true,
        });
      }
    } catch (e) {
      showLoadErrors([`embedded bundle failed to load: ${e.message || e}`]);
    }
  }
  loadEmbeddedBundle();
})();
