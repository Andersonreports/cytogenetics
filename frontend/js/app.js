const $ = id => document.getElementById(id);
const $$ = sel => [...document.querySelectorAll(sel)];
const STATE_KEY = 'cyto_form_state';
const G = { variants: [], current: -1, init: null, previewSeq: 0, timer: null };

function toast(msg, ms = 3000) {
  const t = $('toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), ms);
}

// ---------------- data ----------------
function collectData() {
  const patient = {};
  $$('[data-p]').forEach(el => patient[el.dataset.p] = el.value.trim());
  const data = { patient, variants: G.variants };
  $$('[data-f]').forEach(el => data[el.dataset.f] = el.value.trim());
  return data;
}

function applyData(d) {
  d = d || {};
  const p = d.patient || {};
  $$('[data-p]').forEach(el => el.value = p[el.dataset.p] || '');
  $$('[data-f]').forEach(el => el.value = d[el.dataset.f] || '');
  if (!$('p-report_date').value && G.init) $('p-report_date').value = G.init.today;
  G.variants = d.variants || [];
  G.current = -1;
  renderVariants();
}

function saveState() {
  try { localStorage.setItem(STATE_KEY, JSON.stringify(collectData())); } catch (e) {}
}
function loadState() {
  try { const raw = localStorage.getItem(STATE_KEY); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
}

// ---------------- variants ----------------
function classKind(c) {
  c = (c || '').toLowerCase();
  if (c.includes('uncertain') || c.startsWith('vus')) return 'vus';
  if (c.startsWith('likely pathogenic')) return 'lp';
  if (c.startsWith('pathogenic')) return 'p';
  return '';
}
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

const FINDING_LABEL = { secondary: 'Secondary', incidental: 'Incidental' };
const KIND_LABEL = { cnv: 'CNV', mito: 'mtDNA' };
function geneCell(v) {
  const f = v.kind === 'mito' ? '' : FINDING_LABEL[v.finding];
  const k = KIND_LABEL[v.kind];
  return `<span class="gene">${esc(v.gene || '—')}</span>` + (k ? ` <span class="tag">${k}</span>` : '')
    + (f ? ` <span class="tag">${f}</span>` : '');
}

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

function suggestedStatement(v) {
  const c = (v.classification || '').trim();
  if (!c) return '';
  const what = /uncertain/i.test(c) ? 'a variant of uncertain significance' : c.toLowerCase();
  if (v.kind === 'cnv') return `Based on the available evidence, this variant is classified as ${what}.`;
  if (v.kind === 'mito') return `Based on the ACMG/AMP guidelines for mitochondrial DNA variants, this variant is classified as ${what}.`;
  return `Based on ACMG criteria, this variant is classified as ${what}.`;
}

function variantText(v) {
  if (v.kind === 'cnv') return v.variant || '—';
  return [v.variant, v.protein].filter(Boolean).join(' / ') || '—';
}

function renderVariants() {
  const box = $('vlist'), body = box.querySelector('tbody');
  box.style.display = G.variants.length ? 'block' : 'none';
  body.innerHTML = G.variants.map((v, i) => `
    <tr class="row${v.selected ? ' ticked' : ''}${i === G.current ? ' current' : ''}" data-i="${i}">
      <td><input type="checkbox" data-tick="${i}" ${v.selected ? 'checked' : ''}></td>
      <td>${geneCell(v)}</td>
      <td>${esc(variantText(v))}</td>
      <td>${esc(v.zygosity || '')}</td>
      <td><span class="tag ${classKind(v.classification)}">${esc(v.classification || '—')}</span></td>
    </tr>`).join('');
  showEditor();
}

function showEditor() {
  const ed = $('veditor'), v = G.variants[G.current];
  if (!v) { ed.style.display = 'none'; return; }
  ed.style.display = 'block';
  $('ve-title').innerHTML = `<span class="gene">${esc(v.gene || 'New variant')}</span> ${esc(v.variant || '')}`;
  $$('[data-v]').forEach(el => {
    el.value = v[el.dataset.v] || '';
    if (el.dataset.v === 'region') el.placeholder = v.region_default || 'Intron 14/22';
    if (el.dataset.v === 'consequence') el.placeholder = v.consequence_default || 'Splice Donor Variant';
  });
  applyKind(v.kind);
  $('ve-selected').checked = !!v.selected;
  const opts = [...new Set([...(v.class_options || []), ...(G.init ? G.init.classes : [])])];
  $('class-list').innerHTML = opts.map(o => `<option value="${esc(o)}">`).join('');
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
    G.variants = j.variants; G.current = -1;
    renderVariants(); changed();
    toast(`${j.variants.length} variant(s) listed — tick the ones to report.`);
  } catch (e) { toast(`Could not read the Excel: ${e.message}`, 6000); }
}

// ---------------- preview ----------------
function changed() {
  saveState();
  clearTimeout(G.timer);
  G.timer = setTimeout(preview, 900);
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
  $('sample-list').innerHTML = G.init.samples.map(s => `<option value="${esc(s)}">`).join('');
  $('f-mito').placeholder = G.init.mito_default || '';
  $('f-summary').placeholder = 'Blank = built from the ticked variants. With none ticked: "' + (G.init.no_variant_summary || '') + '"';
  applyData(loadState() || {});

  $('form').addEventListener('input', e => {
    const el = e.target;
    if (el.dataset.v !== undefined && G.variants[G.current]) {
      G.variants[G.current][el.dataset.v] = el.value;
      const row = $('vlist').querySelector(`tr[data-i="${G.current}"]`);
      if (row) {
        const v = G.variants[G.current];
        row.children[1].innerHTML = geneCell(v);
        row.children[2].textContent = variantText(v);
        row.children[3].textContent = v.zygosity || '';
        row.children[4].innerHTML = `<span class="tag ${classKind(v.classification)}">${esc(v.classification || '—')}</span>`;
      }
    }
    if (el.dataset.v === 'kind') showEditor();
    if (el.type !== 'file') changed();
  });
  $('ve-statement').addEventListener('click', () => {
    const v = G.variants[G.current];
    if (!v) return;
    const s = suggestedStatement(v);
    if (!s) { toast('Fill in the classification first.'); return; }
    v.statement = s; showEditor(); changed();
  });

  $('vlist').addEventListener('click', e => {
    const tick = e.target.dataset.tick;
    if (tick !== undefined) {
      G.variants[+tick].selected = e.target.checked;
      if (+tick === G.current) $('ve-selected').checked = e.target.checked;
      e.target.closest('tr').classList.toggle('ticked', e.target.checked);
      changed(); return;
    }
    const row = e.target.closest('tr.row');
    if (row) { G.current = +row.dataset.i; renderVariants(); $('veditor').scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  });
  $('ve-selected').addEventListener('change', e => { G.variants[G.current].selected = e.target.checked; renderVariants(); changed(); });
  $('ve-close').addEventListener('click', () => { G.current = -1; renderVariants(); });
  $('ve-delete').addEventListener('click', () => {
    if (!confirm('Remove this variant from the list?')) return;
    G.variants.splice(G.current, 1); G.current = -1; renderVariants(); changed();
  });
  $('add-variant').addEventListener('click', () => {
    G.variants.push({ gene: '', variant: '', protein: '', nm_id: '', zygosity: 'Heterozygous', classification: '',
      disease: '', inheritance: '', omim_phenotype: '', evidence: '', genomic_position: '', region: '',
      consequence: '', gene_name: '', hgnc: '', criteria: '', finding: '', kind: '', statement: '', size: '',
      cnv_type: '', segment_genes: '', heteroplasmy: '', dna_source: '', selected: true, manual: true });
    G.current = G.variants.length - 1; renderVariants(); changed();
  });

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
  $('new-btn').addEventListener('click', () => {
    if (!confirm('Clear the whole form for a new report?')) return;
    applyData({}); changed();
  });
  preview();
}
start();
