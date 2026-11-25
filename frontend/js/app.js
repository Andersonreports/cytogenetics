const $ = id => document.getElementById(id);
const $$ = sel => [...document.querySelectorAll(sel)];
// The unfinished report is kept in this browser per signed-in user, so on a shared
// computer one person's form is not shown to the next.
const STATE_KEY = 'cyto_form_state:' + (document.body.dataset.user || '');

// Signed out (the 5-hour sign-in ended, or the password was changed): to the sign-in
// page. The form is already saved in the browser and comes back after signing in.
const _fetch = window.fetch.bind(window);
window.fetch = async (...args) => {
  const r = await _fetch(...args);
  if (r.status === 401) {
    saveState();
    location.href = '/login?expired=1&next=/';
    throw new Error('Signed out');
  }
  return r;
};
const G = { variants: [], current: -1, init: null, previewSeq: 0, timer: null, edited: new Set(), defaults: {} };
// Boxes filled with the text built from the ticked variants (the server's /api/defaults)
// until the user edits them; emptying a box hands it back to the generated text.
const AUTO_FIELDS = ['summary', 'secondary_summary', 'incidental_summary', 'mito'];

document.addEventListener('click', e => {          // the user menu closes on a click elsewhere
  const m = document.querySelector('.user-menu');
  if (m && m.open && !m.contains(e.target)) m.open = false;
});

function toast(msg, ms = 3000) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), ms);
}

// ---------------- data ----------------
function collectData() {
  const patient = {};
  $$('[data-p]').forEach(el => patient[el.dataset.p] = el.value.trim());
  const data = { patient, variants: G.variants, edited: [...G.edited] };
  $$('[data-f]').forEach(el => data[el.dataset.f] = el.value.trim());
  return data;
}

function applyData(d) {
  d = d || {};
  const p = d.patient || {};
  $$('[data-p]').forEach(el => el.value = p[el.dataset.p] || '');
  $$('[data-f]').forEach(el => el.value = d[el.dataset.f] || '');
  syncRichFields();
  // Which generated boxes the user has changed (kept as typed). A draft saved before
  // this existed: a box with text in it counts as the user's.
  G.edited = new Set(Array.isArray(d.edited) ? d.edited : AUTO_FIELDS.filter(f => (d[f] || '').trim()));
  G.defaults = {};
  if (!$('p-report_date').value && G.init) $('p-report_date').value = G.init.today;
  G.variants = d.variants || [];
  G.current = G.variants.length ? 0 : -1;
  renderVariants();
}

function saveState() {
  try { localStorage.setItem(STATE_KEY, JSON.stringify(collectData())); } catch (e) {}
}
function loadState() {
  try {
    let raw = localStorage.getItem(STATE_KEY);
    const old = localStorage.getItem('cyto_form_state');     // saved before sign-in existed
    if (old !== null) {
      if (!raw) { raw = old; localStorage.setItem(STATE_KEY, old); }
      localStorage.removeItem('cyto_form_state');
    }
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}

// ---------------- variants ----------------
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

const FINDING_LABEL = { secondary: 'Secondary', incidental: 'Incidental' };
const KIND_LABEL = { cnv: 'CNV', mito: 'mtDNA' };

// The editor shows the fields of the variant's type (sequence / CNV / mitochondrial),
// with that type's labels and examples (data-l-<kind>, data-ph-<kind>).
const cap = s => s[0].toUpperCase() + s.slice(1);
function applyKind(kind) {
  const k = kind || 'snv';
  $$('#veditor [data-for]').forEach(el => el.style.display = el.dataset.for.split(' ').includes(k) ? '' : 'none');
  $$('#veditor label[data-l-cnv], #veditor label[data-l-mito]').forEach(el => {
    if (el.dataset.l0 === undefined) el.dataset.l0 = el.innerHTML;
    const alt = el.dataset['l' + cap(k)];
    el.innerHTML = alt ? esc(alt) : el.dataset.l0;
  });
  $$('#veditor [data-v]').forEach(el => {
    if (el.dataset.ph0 === undefined) el.dataset.ph0 = el.placeholder || '';
    const alt = el.dataset['ph' + cap(k)];
    if (alt) el.placeholder = alt;
    else if (!['region', 'consequence'].includes(el.dataset.v)) el.placeholder = el.dataset.ph0;
  });
}


// A CNV's genomic HGVS and size, built like the report does (backend renderer.cnv_hgvs /
// cnv_size) from Chromosome, Start, End and Loss / Gain unless typed in.
const NC38 = { 1: 'NC_000001.11', 2: 'NC_000002.12', 3: 'NC_000003.12', 4: 'NC_000004.12', 5: 'NC_000005.10',
  6: 'NC_000006.12', 7: 'NC_000007.14', 8: 'NC_000008.11', 9: 'NC_000009.12', 10: 'NC_000010.11',
  11: 'NC_000011.10', 12: 'NC_000012.12', 13: 'NC_000013.11', 14: 'NC_000014.9', 15: 'NC_000015.10',
  16: 'NC_000016.10', 17: 'NC_000017.11', 18: 'NC_000018.10', 19: 'NC_000019.10', 20: 'NC_000020.11',
  21: 'NC_000021.9', 22: 'NC_000022.11', X: 'NC_000023.11', Y: 'NC_000024.10' };
const cnvInt = s => { const t = String(s || '').replace(/[,\s]/g, ''); return /^\d+$/.test(t) ? +t : 0; };
function cnvChange(v) {
  const t = (v.cnv_type || '').trim().toLowerCase();
  if (/^(loss|del)/.test(t)) return 'Loss';
  if (/^(gain|dup)/.test(t)) return 'Gain';
  return '';
}
function cnvBuilt(v) {
  const c = String(v.cnv_chrom || (v.chrom_pos || '').split(':')[0] || '').trim().replace(/^chr/i, '').toUpperCase();
  const nc = NC38[{ 23: 'X', 24: 'Y' }[c] || c], a = cnvInt(v.cnv_start), b = cnvInt(v.cnv_end), ch = cnvChange(v);
  return nc && a && b && ch ? `${nc}:g.(?_${a})_(${b}_?)${ch === 'Loss' ? 'del' : 'dup'}` : '';
}
function cnvHgvs(v) {
  if ((v.cnv_hgvs || '').trim()) return v.cnv_hgvs.trim();
  if (/^(NC_|chr|g\.)/i.test((v.variant || '').trim())) return v.variant.trim();
  return cnvBuilt(v);
}
function cnvSize(v) {
  const a = cnvInt(v.cnv_start), b = cnvInt(v.cnv_end);
  if (!a || !b || b < a) return '';
  const n = b - a + 1;
  return n >= 1e6 ? `${(n / 1e6).toFixed(2)} Mb` : n >= 1000 ? `${(n / 1e3).toFixed(2)} kb` : `${n} bp`;
}
function showCnvAuto(v) {
  if (!v || v.kind !== 'cnv') return;
  const hasOld = !(v.cnv_hgvs || '').trim() && /^(NC_|chr|g\.)/i.test((v.variant || '').trim());
  $('cnv-hgvs').placeholder = cnvBuilt(v) || (hasOld ? v.variant.trim()
    : 'fill Chromosome, Loss / Gain, Start and End');
  $('cnv-size').placeholder = cnvSize(v) || 'e.g. 93.73 kb';
  // A typed HGVS replaces the built one in the report: warn when it is not a genomic HGVS.
  const own = (v.cnv_hgvs || '').trim(), w = $('cnv-hgvs-warn');
  const bad = own && !/(^|:)g\./.test(own);
  w.style.display = bad ? '' : 'none';
  w.textContent = bad ? `"${own}" is not a genomic HGVS (NC_…:g.…), but the report prints it as typed. `
    + 'Clear this box to use the one built from Chromosome, Loss / Gain, Start and End.' : '';
  const xc = (v.chrom_pos || '').split(':')[0].replace(/^chr/i, '').trim();
  $('cnv-chrom').placeholder = xc ? `${xc} (from the Excel)` : 'e.g. X';
}

// Zygosity dropdown: the states for the variant's type; the Excel's HET / HOM / HEMI
// shown as the full word, and any other value kept as an extra option.
const ZYG_SHORT = { HET: 'Heterozygous', HOM: 'Homozygous', HEMI: 'Hemizygous' };
function fillZygosity(v) {
  const opts = v.kind === 'mito' ? ['Heteroplasmy', 'Homoplasmy'] : ['Heterozygous', 'Homozygous', 'Hemizygous'];
  const raw = (v.zygosity || '').trim(), cur = ZYG_SHORT[raw.toUpperCase()] || raw;
  if (cur !== raw) v.zygosity = cur;
  if (cur && !opts.includes(cur)) opts.push(cur);
  $('zyg-select').innerHTML = (cur ? '' : '<option value="">— Select —</option>')
    + opts.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  $('zyg-select').value = cur;
}

function variantText(v) {
  if (v.kind === 'cnv') return cnvHgvs(v) || 'CNV';
  return [v.variant, v.protein].filter(Boolean).join(' / ') || '—';
}

// The list shows "GENE c.change" per variant (search filters it), with tags for a
// CNV / mtDNA variant and a Secondary / Incidental block.
function itemHtml(v) {
  const k = KIND_LABEL[v.kind];
  const f = v.kind === 'mito' ? '' : FINDING_LABEL[v.finding];
  return `<span class="vitem-label"><span class="gene">${esc(v.gene || '—')}</span>${esc(v.kind === 'cnv' ? cnvHgvs(v) : (v.variant || ''))}</span>`
    + (k ? `<span class="tag">${k}</span>` : '') + (f ? `<span class="tag">${f}</span>` : '');
}

function renderVariants() {
  const has = G.variants.length > 0;
  $('vbody').classList.toggle('show', has);
  const hint = $('vhint');
  hint.classList.toggle('loaded', has);
  hint.firstChild.textContent = has ? `Loaded ${G.variants.length} variant${G.variants.length === 1 ? '' : 's'}. `
    : 'Upload the listed-variants Excel, then tick the variants to show in the report. ';
  hint.querySelector('.add-variant').style.display = has ? 'none' : '';
  const q = $('vsearch').value.trim().toLowerCase();
  let shown = 0;
  $('vlist').innerHTML = G.variants.map((v, i) => {
    const text = `${v.gene || ''} ${v.variant || ''} ${v.protein || ''}`.toLowerCase();
    if (q && !text.includes(q)) return '';
    shown++;
    return `<div class="vitem${i === G.current ? ' active' : ''}" data-i="${i}" title="${esc(v.classification || '')}">
      <input type="checkbox" data-tick="${i}" ${v.selected ? 'checked' : ''}>${itemHtml(v)}</div>`;
  }).join('');
  const total = G.variants.length;
  $('vall-label').textContent = `Select all (${shown === total ? total : `${shown} of ${total}`} variants)`;
  updateSelectAll();
  showEditor();
}

function updateSelectAll() {
  const n = G.variants.filter(v => v.selected).length;
  $('vall').checked = G.variants.length > 0 && n === G.variants.length;
  $('vall').indeterminate = n > 0 && n < G.variants.length;
}

function refreshItem(i) {
  const item = $('vlist').querySelector(`.vitem[data-i="${i}"]`);
  if (item) item.innerHTML = `<input type="checkbox" data-tick="${i}" ${G.variants[i].selected ? 'checked' : ''}>${itemHtml(G.variants[i])}`;
}

function editorStatus(v) {
  return `<span class="gene">${esc(v.gene || 'New variant')}</span> ${esc(variantText(v))} — `
    + (v.selected ? 'ticked: in the report.' : 'not ticked: tick it in the list to include it.');
}

function showEditor() {
  const ed = $('veditor'), v = G.variants[G.current];
  $('vempty').style.display = v ? 'none' : '';
  if (!v) { ed.style.display = 'none'; return; }
  ed.style.display = 'block';
  $('ve-title').innerHTML = editorStatus(v);
  // Classification dropdown: the lab's classifications, plus the variant's own value
  // (e.g. from the Excel) when it is none of them.
  const cur = (v.classification || '').trim();
  const opts = [...new Set([...(G.init ? G.init.classes : []), ...(v.class_options || [])])];
  if (cur && !opts.includes(cur)) opts.unshift(cur);
  $('class-select').innerHTML = (cur ? '' : '<option value="">— Select —</option>')
    + opts.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('');
  $$('[data-v]').forEach(el => {
    el.value = v[el.dataset.v] || '';
    if (el.dataset.v === 'region') el.placeholder = v.region_default || 'Intron 14/22';
    if (el.dataset.v === 'consequence') el.placeholder = v.consequence_default || 'Splice Donor Variant';
  });
  v.cnv_type = cnvChange(v) || (v.cnv_type || '');
  $$('[data-v="cnv_type"]').forEach(el => el.value = cnvChange(v));
  fillZygosity(v);
  applyKind(v.kind);
  showCnvAuto(v);
  vEdited(v);
  $('rich').innerHTML = textToRich(v.description);
  showVAutoState();
}

async function uploadExcel(file) {
  if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  toast('Reading the Excel…');
  try {
    const r = await fetch('/api/upload-variants', { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    if (G.variants.some(v => v.selected) && !confirm('Replace the current variant list (ticked variants included)?')) return;
    G.variants = j.variants; G.current = j.variants.length ? 0 : -1;
    $('vsearch').value = '';
    let msg = `${j.variants.length} variant(s) listed — tick the ones to report.`;
    const lab = labNoFromFileName(file.name);
    if (lab) {
      const box = $('p-lab_no'), had = box.value.trim();
      if (!had || had === lab || confirm(`Set Lab No to "${lab}" (from the file name) instead of "${had}"?`)) {
        box.value = lab;
        msg += ` Lab No: ${lab}.`;
      }
    }
    renderVariants(); changed();
    toast(msg, 4500);
  } catch (e) { toast(`Could not read the Excel: ${e.message}`, 6000); }
}

// The Lab No in the variants Excel's file name, as the report prints it:
// "WES 02.2026 ….xlsx" / "WES_02-26.xlsx" / "wes 102 2026" -> "WES 02/26". "" if none.
function labNoFromFileName(name) {
  const m = (name || '').match(/(?:^|[^A-Za-z])WES[\s_-]*(\d{1,4})\s*[.\/_\- ]\s*(\d{4}|\d{2})(?!\d)/i);
  return m ? `WES ${m[1]}/${m[2].slice(-2)}` : '';
}

// ---------------- preview ----------------
// ---------------- steps (tabs) ----------------
const TAB_KEY = 'cyto_active_tab';
const STEP_NAMES = { patient: 'Patient & sample', variants: 'Variants', result: 'Result text' };

function switchTab(tab) {
  if (!STEP_NAMES[tab]) tab = 'patient';
  $$('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `tab-${tab}`));
  $('step-title').textContent = STEP_NAMES[tab];
  try { localStorage.setItem(TAB_KEY, tab); } catch (e) {}
}

function stepState(tab) {
  if (tab === 'patient') {
    const els = [...$$('[data-p]'), $('f-indication')];
    const total = els.length, left = els.filter(el => !el.value.trim()).length;
    return { done: !left, sub: !left ? 'Complete' : left === total ? 'Not started' : `${left} of ${total} left` };
  }
  if (tab === 'variants') {
    const n = G.variants.filter(v => v.selected).length;
    return { done: n > 0, sub: G.variants.length ? `${n} of ${G.variants.length} ticked` : 'Not started' };
  }
  const shown = el => { const box = el.closest('[data-box]'); return !box || box.style.display !== 'none'; };
  const n = $$('#tab-result [data-f]').filter(el => el.value.trim() && shown(el)).length;
  return { done: !!$('f-signatory').value.trim(), sub: n ? `${n} filled` : 'Optional' };
}

function updateSteps() {
  $$('.tab-btn').forEach((b, i) => {
    const st = stepState(b.dataset.tab);
    b.classList.toggle('done', st.done);
    b.querySelector('.step-num').textContent = st.done ? '✓' : String(i + 1);
    const sub = b.querySelector('.step-sub');
    sub.textContent = st.sub;
    sub.classList.toggle('partial', !st.done && !['Not started', 'Optional'].includes(st.sub));
  });
}

function changed() {
  showAutoState();
  updateSteps();
  saveState();
  clearTimeout(G.timer);
  G.timer = setTimeout(async () => { await refreshDefaults(); preview(); }, 900);
}

// Fill the generated boxes the user hasn't edited with the text built from the ticked
// variants, so the form shows what the report prints.
async function refreshDefaults() {
  const sent = G.variants.slice();
  let j;
  try {
    const data = collectData();
    const r = await fetch('/api/defaults', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data }) });
    if (!r.ok) return;
    j = await r.json();
  } catch (e) { return; }
  G.defaults = j;
  AUTO_FIELDS.forEach(f => {
    const el = $(`f-${f}`);
    if (!G.edited.has(f) && document.activeElement !== el._rich) el.value = G.defaults[f] || '';
  });
  syncRichFields();
  // Each variant's Description box (built text until the user edits it).
  (j.variants || []).forEach((texts, i) => {
    const v = sent[i];
    if (!v || !G.variants.includes(v)) return;       // list changed meanwhile: next refresh
    v.auto = texts;
    if (vEdited(v).includes('description')) return;
    const isCur = v === G.variants[G.current];
    if (isCur && document.activeElement === $('rich')) return;
    if (v.description !== (texts.description || '')) {
      v.description = texts.description || '';
      if (isCur) $('rich').innerHTML = textToRich(v.description);
    }
  });
  showVAutoState();
  showAutoState();
  saveState();
}

// The variant boxes filled from the server's text (until edited). A variant saved before
// this existed: a box with text in it counts as the user's.
const VAUTO = ['description'];
function vEdited(v) {
  migrateDescription(v);
  if (!Array.isArray(v.edited)) v.edited = (v.description || '').trim() ? ['description'] : [];
  return v.edited;
}

// Variants saved when the Description was three boxes (Description, Variant evidence,
// bold Classification statement): joined into the one box, in print order. All three
// empty -> the box starts from the built text again.
function migrateDescription(v) {
  if (v.description !== undefined) return;
  let phen = (v.omim_phenotype || '').trim();
  if (phen && phen === (v.omim_phenotype_prefix || '').trim()) phen = '';
  const st = (v.statement || '').trim();
  v.description = [phen, (v.evidence || '').trim(), st ? `**${st}**` : ''].filter(Boolean).join('\n\n');
  v.edited = v.description ? ['description'] : [];
}

// ---- the Description rich-text box: paragraphs (Enter), bold and italic, stored as text
// with blank lines between paragraphs, **bold** and <i>italic</i> spans (what the report
// renderer reads).
function richToText(root) {
  const paras = [];
  let cur = [];
  const flush = () => { paras.push(cur); cur = []; };
  const walk = (node, bold, ital) => node.childNodes.forEach(n => {
    if (n.nodeType === 3) {
      n.textContent.split('\n').forEach((t, k) => { if (k) flush(); if (t) cur.push([t, bold, ital]); });
    } else if (n.nodeName === 'BR') {
      flush();
    } else if (n.nodeType === 1) {
      const st = n.style || {}, fw = st.fontWeight || '';
      const b = bold || n.nodeName === 'B' || n.nodeName === 'STRONG' || fw === 'bold' || +fw >= 600;
      const i = ital || n.nodeName === 'I' || n.nodeName === 'EM' || st.fontStyle === 'italic';
      const block = /^(DIV|P|LI|H\d)$/.test(n.nodeName);
      if (block && cur.length) flush();
      walk(n, b, i);
      if (block) flush();
    }
  });
  walk(root, false, false);
  flush();
  const wrap = (t, open, close) => {
    if (!t.trim()) return t;
    const lead = t.match(/^\s*/)[0], tail = t.match(/\s*$/)[0];
    return `${lead}${open}${t.trim()}${close}${tail}`;
  };
  return paras.map(segs => {
    const groups = [];                  // merge neighbours of the same style
    segs.forEach(([t, b, i]) => {
      const last = groups[groups.length - 1];
      if (last && last[1] === b && last[2] === i) last[0] += t; else groups.push([t, b, i]);
    });
    return groups.map(([t, b, i]) => {
      if (i) t = wrap(t, '<i>', '</i>');
      if (b) t = wrap(t, '**', '**');
      return t;
    }).join('').replace(/\s+/g, ' ').trim();
  }).filter(Boolean).join('\n\n');
}

function textToRich(text) {
  return (text || '').split(/\n\s*\n/).map(p => p.trim().replace(/\s*\n\s*/g, ' ')).filter(Boolean)
    .map(p => '<div>' + esc(p).replace(/\*\*([\s\S]+?)\*\*/g, '<b>$1</b>')
      .replace(/&lt;i&gt;/g, '<i>').replace(/&lt;\/i&gt;/g, '</i>') + '</div>').join('');
}

// ---- the Result-text boxes: the same B / I editor over each textarea, which stays (hidden)
// as the field's value in that text form, so saving, drafts and the generated-text
// logic work on it as before.
function setupRichFields() {
  $$('#tab-result textarea[data-f]').filter(ta => ta.id !== 'f-signatory').forEach(ta => {
    const wrap = document.createElement('div');
    wrap.className = 'rich-wrap';
    wrap.innerHTML = '<div class="rich-bar">'
      + '<button class="rich-btn" type="button" data-cmd="bold" title="Bold (Ctrl+B)"><b>B</b></button>'
      + '<button class="rich-btn" type="button" data-cmd="italic" title="Italic (Ctrl+I)"><i>I</i></button></div>'
      + '<div class="rich rich-field" contenteditable="true" spellcheck="true"></div>';
    const box = wrap.querySelector('.rich');
    box.dataset.placeholder = ta.placeholder || '';
    box.style.minHeight = ta.style.minHeight || '70px';
    ta.style.display = 'none';
    ta.after(wrap);
    ta._rich = box;
    box.addEventListener('input', () => {
      ta.value = richToText(box);
      ta.dispatchEvent(new Event('input', { bubbles: true }));
    });
  });
}

function syncRichFields() {
  $$('textarea[data-f]').forEach(ta => {
    if (ta._rich && document.activeElement !== ta._rich) ta._rich.innerHTML = textToRich(ta.value);
  });
}

function showVAutoState() {
  const v = G.variants[G.current];
  $$('[data-vrebuild]').forEach(b => {
    const f = b.dataset.vrebuild;
    b.style.display = v && vEdited(v).includes(f) && v.auto && (v.auto[f] || '') !== (v[f] || '') ? '' : 'none';
  });
  if (v) $('rich-hint').textContent = vEdited(v).includes('description')
    ? 'Edited by you: printed as typed here. Rebuild brings back the text built from the variant.'
    : "Built from the variant's values (Excel / OMIM); it follows them until you edit it.";
}

function showAutoState() {
  AUTO_FIELDS.forEach(f => {
    const el = $(`f-${f}`), edited = G.edited.has(f);
    const def = (G.defaults[f] || '').trim();
    $$(`[data-rebuild="${f}"]`).forEach(b => b.style.display = edited && def && el.value.trim() !== def ? '' : 'none');
    const hint = document.querySelector(`[data-auto-hint="${f}"]`);
    if (hint) hint.textContent = edited ? 'Edited by you: kept as typed.'
      : 'Built from the ticked variants (follows them until you edit it).';
    // The Secondary / Incidental boxes only while a ticked gene is reported in that
    // finding (text typed earlier is kept, hidden, and not printed without one).
    const box = document.querySelector(`[data-box="${f}"]`);
    if (box && f !== 'summary' && f !== 'mito') {
      const block = f.replace('_summary', '');
      box.style.display = G.variants.some(v => v.selected && v.kind !== 'mito' && v.finding === block) ? '' : 'none';
    }
  });
}

async function preview() {
  const seq = ++G.previewSeq;
  const st = $('preview-status');
  st.className = ''; st.textContent = 'Rendering preview…';
  try {
    const width = Math.round(Math.min($('pages').clientWidth - 36, 820) * (window.devicePixelRatio || 1));
    const r = await fetch('/api/preview', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: collectData(), width }) });
    const j = await r.json();
    if (seq !== G.previewSeq) return;            // a newer preview is on its way
    if (!r.ok) throw new Error(j.error || r.statusText);
    const top = $('pages').scrollTop;
    $('pages').innerHTML = j.pages.map((b, i) => `<img alt="Page ${i + 1}" src="data:image/png;base64,${b}">`).join('');
    $('pages').scrollTop = top;
    st.textContent = `Updated ${new Date().toLocaleTimeString()} — ${j.pages.length} page(s)`;
  } catch (e) {
    if (seq !== G.previewSeq) return;
    st.className = 'err'; st.textContent = `Preview failed: ${e.message}`;
  }
}

// ---------------- export / drafts ----------------
async function exportReport(kind) {
  const btn = $(`export-${kind}`); btn.disabled = true;
  toast(kind === 'pdf' ? 'Making the PDF…' : 'Making the DOCX…');
  try {
    const r = await fetch('/api/export', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ data: collectData(), kind }) });
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.error || r.statusText); }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="?([^";]+)"?/);
    download(blob, m ? decodeURIComponent(m[1]) : `report.${kind}`);
    toast('Saved to your Downloads folder.');
  } catch (e) { toast(`Export failed: ${e.message}`, 6000); }
  finally { btn.disabled = false; }
}

function download(blob, name) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

function saveDraft() {
  const d = collectData();
  const name = (d.patient.name || 'report').replace(/[^A-Za-z0-9-]+/g, '_').replace(/^_|_$/g, '');
  download(new Blob([JSON.stringify(d, null, 1)], { type: 'application/json' }), `${name}_cyto_draft.json`);
}

async function loadDraft(file) {
  if (!file) return;
  try { applyData(JSON.parse(await file.text())); changed(); toast('Draft loaded.'); }
  catch (e) { toast(`Could not load the draft: ${e.message}`, 5000); }
}

// ---------------- wiring ----------------
async function start() {
  try { G.init = await (await fetch('/api/init')).json(); } catch (e) { G.init = { today: '', samples: [], classes: [] }; }
  setupRichFields();
  applyData(loadState() || {});
  await refreshDefaults();
  $$('[data-rebuild]').forEach(b => b.addEventListener('click', e => {
    e.preventDefault();
    const f = b.dataset.rebuild;
    G.edited.delete(f);
    $(`f-${f}`).value = G.defaults[f] || '';
    syncRichFields();
    showAutoState(); changed();
  }));
  updateSteps();
  let tab = 'patient';
  try { tab = localStorage.getItem(TAB_KEY) || 'patient'; } catch (e) {}
  switchTab(tab);
  $$('.tab-btn').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

  $('form').addEventListener('input', e => {
    const el = e.target;
    if (el.id === 'vsearch' || el.type === 'checkbox' || el.type === 'file') return;   // handled below
    if (el.dataset.v !== undefined && G.variants[G.current]) {
      const v = G.variants[G.current];
      v[el.dataset.v] = el.value;
      refreshItem(G.current);
      $('ve-title').innerHTML = editorStatus(v);
      showCnvAuto(v);
    }
    if (el.dataset.v === 'kind') showEditor();
    const f = el.dataset.f;
    if (AUTO_FIELDS.includes(f)) {         // typed in a generated box: the user's text from now on
      const v = el.value.trim();
      if (v && v !== (G.defaults[f] || '').trim()) G.edited.add(f); else G.edited.delete(f);
      showAutoState();
    }
    changed();
  });
  $('vsearch').addEventListener('input', renderVariants);
  // Date boxes: the calendar button opens the browser's date picker (starting at the
  // box's date) and writes the pick back as dd/mm/yyyy; typing still works.
  $$('.date-btn').forEach(btn => {
    const box = $(btn.dataset.dateFor), pick = btn.nextElementSibling;
    btn.addEventListener('click', () => {
      const m = box.value.trim().match(/^(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})$/);
      pick.value = m ? `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}` : '';
      try { pick.showPicker(); } catch (e) { pick.focus(); pick.click(); }
    });
    pick.addEventListener('change', () => {
      const m = pick.value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!m) return;
      box.value = `${m[3]}/${m[2]}/${m[1]}`;
      box.dispatchEvent(new Event('input', { bubbles: true }));     // save + preview
    });
  });

  // The Description box (fires before the form's input handler, which saves / previews).
  $('rich').addEventListener('input', () => {
    const v = G.variants[G.current];
    if (!v) return;
    v.description = richToText($('rich'));
    v.edited = v.auto && v.description === (v.auto.description || '') ? [] : ['description'];
    showVAutoState();
  });
  $$('.rich').forEach(box => box.addEventListener('paste', e => {   // pasted text keeps its paragraphs, not its styles
    e.preventDefault();
    const t = (e.clipboardData || window.clipboardData).getData('text/plain');
    document.execCommand('insertText', false, t);
  }));
  $$('.rich-btn[data-cmd]').forEach(b => {
    b.addEventListener('mousedown', e => e.preventDefault());   // keep the selection
    b.addEventListener('click', () => {
      b.closest('.rich-wrap').querySelector('.rich').focus();
      document.execCommand(b.dataset.cmd);
    });
  });
  document.addEventListener('selectionchange', () => {
    const box = document.activeElement;
    if (!box || !box.classList.contains('rich')) return;
    box.closest('.rich-wrap').querySelectorAll('.rich-btn[data-cmd]')
      .forEach(b => b.classList.toggle('on', document.queryCommandState(b.dataset.cmd)));
  });

  $$('[data-vrebuild]').forEach(b => b.addEventListener('click', e => {
    e.preventDefault();
    const v = G.variants[G.current], f = b.dataset.vrebuild;
    if (!v) return;
    v.edited = vEdited(v).filter(x => x !== f);
    v[f] = (v.auto && v.auto[f]) || '';
    showEditor(); changed();
  }));

  $('vlist').addEventListener('click', e => {
    const tick = e.target.dataset.tick;
    if (tick !== undefined) {           // the tick box: report / leave out, editor stays
      G.variants[+tick].selected = e.target.checked;
      if (+tick === G.current) $('ve-title').innerHTML = editorStatus(G.variants[+tick]);
      updateSelectAll(); changed(); return;
    }
    const item = e.target.closest('.vitem');
    if (item) { G.current = +item.dataset.i; renderVariants(); }
  });
  $('vall').addEventListener('change', e => {      // ticks / unticks the variants shown (search)
    const shown = [...$('vlist').querySelectorAll('.vitem')].map(el => +el.dataset.i);
    shown.forEach(i => G.variants[i].selected = e.target.checked);
    renderVariants(); changed();
  });
  $('vlist-toggle').addEventListener('click', () => {
    const col = $('vlist-col'), hide = !col.classList.contains('collapsed');
    col.classList.toggle('collapsed', hide);
    $('vlist-toggle').innerHTML = hide ? '&#8250;' : '&#8249;';
    $('vlist-toggle').title = hide ? 'Show list' : 'Hide list';
  });
  $('ve-delete').addEventListener('click', () => {
    if (!confirm('Remove this variant from the list?')) return;
    G.variants.splice(G.current, 1);
    G.current = Math.min(G.current, G.variants.length - 1);
    renderVariants(); changed();
  });
  $$('.add-variant').forEach(b => b.addEventListener('click', () => {
    G.variants.push({ gene: '', variant: '', protein: '', nm_id: '', zygosity: 'Heterozygous', classification: '',
      disease: '', inheritance: '', omim_phenotype: '', evidence: '', genomic_position: '', region: '',
      consequence: '', gene_name: '', hgnc: '', criteria: '', finding: '', kind: '', statement: '', size: '',
      cnv_type: '', cnv_chrom: '', cnv_start: '', cnv_end: '', cnv_hgvs: '', segment_genes: '', heteroplasmy: '', dna_source: '', selected: true, manual: true });
    G.current = G.variants.length - 1; $('vsearch').value = ''; renderVariants(); changed();
  }));

  const drop = $('drop');
  drop.addEventListener('click', () => $('xlsx').click());
  $('xlsx').addEventListener('change', e => { uploadExcel(e.target.files[0]); e.target.value = ''; });
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); uploadExcel(e.dataTransfer.files[0]); });

  $('refresh').addEventListener('click', preview);
  $('export-docx').addEventListener('click', () => exportReport('docx'));
  $('export-pdf').addEventListener('click', () => exportReport('pdf'));
  $('save-draft').addEventListener('click', saveDraft);
  $('load-draft').addEventListener('change', e => { loadDraft(e.target.files[0]); e.target.value = ''; });
  $('clear-btn').addEventListener('click', () => {      // as the CMC tool's Clear: everything
    if (!confirm('Clear all form data and start a new report?')) return;
    $('vsearch').value = '';
    applyData({});
    switchTab('patient');
    changed();
  });
  preview();
}
start();
