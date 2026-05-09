// Bootstrap (annotation) tab — click-to-annotate, multi-block range,
// table-row range, kind-specific forms, save to <env_dir>/annotations/.

(function () {
    'use strict';

    const KIND_FIELDS = {
        section_heading: [
            { key: 'depth', label: 'depth', type: 'int', min: 1, max: 9 },
            { key: 'section_number', label: 'section_number', type: 'string', placeholder: '1.2.3' },
            { key: 'is_numbered', label: 'is_numbered', type: 'bool' },
        ],
        req_id: [
            { key: 'placement', label: 'placement', type: 'enum', choices: ['', 'leading', 'trailing'] },
            { key: 'format_hint', label: 'format_hint', type: 'string', placeholder: '<MNO>_REQ_<PLAN>_<DIGITS>' },
        ],
        toc: [
            { key: 'pattern_hint', label: 'pattern_hint', type: 'enum', choices: ['', 'leader-dot-page', 'indented-leveled', 'plain-list'] },
        ],
        strikethrough: [
            { key: 'subkind', label: 'subkind', type: 'enum', choices: ['', 'full_paragraph', 'table_row', 'partial_cell', 'section_heading'] },
            { key: 'visual', label: 'visual', type: 'enum', choices: ['', 'line', 'font_flag', 'both'] },
        ],
        version_history: [
            { key: 'kind_subtype', label: 'kind_subtype', type: 'enum', choices: ['', 'heading_only', 'full_block'] },
        ],
        definitions: [
            { key: 'layout', label: 'layout', type: 'enum', choices: ['', 'paragraph_list', 'two_col_table', 'three_col_table', 'inline_glossary'] },
        ],
        applicability: [
            { key: 'position', label: 'position', type: 'enum', choices: ['', 'after_heading', 'inline_in_para', 'separate_block'] },
        ],
        priority: [
            { key: 'position', label: 'position', type: 'enum', choices: ['', 'after_heading', 'inline_in_para', 'separate_block'] },
        ],
        reference_intra_doc: [
            { key: 'inline', label: 'inline', type: 'bool' },
            { key: 'target.section_number', label: 'target.section_number', type: 'string', placeholder: '1.2.3' },
            { key: 'target.req_id', label: 'target.req_id', type: 'string', placeholder: '<MNO>_REQ_<PLAN>_<NUM>' },
        ],
        reference_cross_doc: [
            { key: 'inline', label: 'inline', type: 'bool' },
            { key: 'target.plan_id', label: 'target.plan_id', type: 'string', placeholder: '<PLAN>' },
            { key: 'target.section_number', label: 'target.section_number', type: 'string' },
            { key: 'target.req_id', label: 'target.req_id', type: 'string' },
        ],
        reference_spec: [
            { key: 'style', label: 'style*', type: 'enum', choices: ['direct', 'indirect'], required: true },
            { key: 'inline', label: 'inline', type: 'bool' },
            { key: 'target.spec', label: 'target.spec', type: 'string', placeholder: '3GPP TS 24.301' },
            { key: 'target.section', label: 'target.section', type: 'string', placeholder: '5.5.1.2.6' },
            { key: 'target.ref_number', label: 'target.ref_number', type: 'int', min: 1 },
        ],
        reference_list: [
            { key: 'numbering_style', label: 'numbering_style', type: 'enum', choices: ['', 'bracketed', 'plain', 'parenthesized'] },
            { key: 'layout', label: 'layout', type: 'enum', choices: ['', 'paragraph_list', 'two_col_table', 'three_col_table'] },
        ],
        reference_list_entry: [
            { key: 'number', label: 'number', type: 'int', min: 0 },
            { key: 'title_hint_chars', label: 'title_hint_chars', type: 'int', min: 0 },
            { key: 'target.spec', label: 'target.spec', type: 'string', placeholder: '3GPP TS 24.301' },
            { key: 'target.section', label: 'target.section', type: 'string' },
        ],
    };

    const KIND_ORDER = [
        'section_heading', 'req_id', 'toc', 'strikethrough', 'version_history',
        'definitions', 'applicability', 'priority',
        'reference_intra_doc', 'reference_cross_doc', 'reference_spec',
        'reference_list', 'reference_list_entry',
    ];

    let ROOT = '';
    let modal = null;
    let selectedBlocks = [];      // {idx, anchor: bool}
    let anchorRowIdx = null;      // when single-block + table: anchor row for row_range
    let selectedRows = null;      // { blockIdx, range: [start, end] } | null
    let pendingKind = null;
    let editingAnnId = null;      // when set, save updates this annotation

    // -----------------------------------------------------------------
    // Init
    // -----------------------------------------------------------------

    window.initParseBootstrap = function (root) {
        ROOT = root || '';
        const sel = document.getElementById('bs-doc-select');
        if (!sel) return;
        loadDocs();
        sel.addEventListener('change', () => {
            const docId = sel.value;
            if (!docId) {
                document.getElementById('bs-area').innerHTML =
                    '<p class="text-muted small">No document selected.</p>';
                return;
            }
            loadDocView(docId);
        });
    };

    function loadDocs() {
        fetch(ROOT + '/parse-review/bootstrap/docs')
            .then(r => r.json())
            .then(data => {
                const sel = document.getElementById('bs-doc-select');
                sel.innerHTML = '<option value="">— select DOCX —</option>';
                if (!data.docs || data.docs.length === 0) {
                    sel.innerHTML = '<option value="">— no DOCX inputs found —</option>';
                    return;
                }
                data.docs.forEach(d => {
                    const opt = document.createElement('option');
                    opt.value = d.doc_id;
                    let label = d.doc_id;
                    if (!d.ir_exists) label += '  (no IR — run extract first)';
                    else if (d.annotation_exists) label += `  (${d.annotation_count} annotations)`;
                    opt.textContent = label;
                    opt.disabled = !d.ir_exists;
                    sel.appendChild(opt);
                });
                document.getElementById('bs-doc-info').textContent =
                    `${data.docs.length} DOCX file(s) · annotations dir: ${data.annotations_dir}`;
            });
    }

    function loadDocView(docId) {
        const area = document.getElementById('bs-area');
        area.innerHTML = '<div class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm me-2"></div>Loading…</div>';
        fetch(ROOT + '/parse-review/bootstrap/' + encodeURIComponent(docId) + '/view')
            .then(r => r.text())
            .then(html => {
                area.innerHTML = html;
                wireDocView();
            })
            .catch(err => {
                area.innerHTML = '<div class="alert alert-danger">Failed to load: ' + err + '</div>';
            });
    }

    // -----------------------------------------------------------------
    // Wiring once a doc is loaded
    // -----------------------------------------------------------------

    function wireDocView() {
        selectedBlocks = [];
        selectedRows = null;
        anchorRowIdx = null;
        pendingKind = null;
        editingAnnId = null;

        renderAnnotations();

        // Block click handlers
        document.querySelectorAll('#bs-ir-body .bs-block').forEach(el => {
            const idx = parseInt(el.dataset.idx, 10);
            el.addEventListener('click', (ev) => {
                if (ev.target.closest('.bs-row-pick')) return;     // row clicks handled separately
                if (ev.target.closest('.bs-add-btn')) return;       // add-btn handled below
                onBlockClick(idx, ev);
            });
            const addBtn = el.querySelector('.bs-add-btn');
            if (addBtn) {
                addBtn.addEventListener('click', (ev) => {
                    ev.stopPropagation();
                    onAddClick(idx, ev);
                });
            }
            el.querySelectorAll('.bs-row-pick').forEach(rowEl => {
                rowEl.addEventListener('click', (ev) => {
                    ev.stopPropagation();
                    onRowClick(idx, parseInt(rowEl.dataset.rowIdx, 10), ev);
                });
            });
        });

        document.getElementById('bs-save-btn').addEventListener('click', saveAll);

        // Sync-scroll IR ↔ DOCX (best-effort: matched by data-block-idx)
        const ir = document.getElementById('bs-ir-body');
        const docx = document.getElementById('bs-docx-body');
        if (ir && docx) {
            ir.addEventListener('scroll', () => syncScroll(ir, docx, '.bs-block', '[data-block-idx]'));
        }

        // Kind menu
        const menu = document.getElementById('bs-kind-menu');
        menu.querySelectorAll('.ctx-menu-item').forEach(item => {
            item.addEventListener('click', () => {
                const kind = item.dataset.kind;
                hideKindMenu();
                if (!kind || kind === '__cancel') return;
                pendingKind = kind;
                openForm(kind, null);
            });
        });
        document.addEventListener('click', (ev) => {
            const menu = document.getElementById('bs-kind-menu');
            if (menu && !menu.contains(ev.target)) hideKindMenu();
        });

        // Form save
        modal = new bootstrap.Modal(document.getElementById('bs-form-modal'));
        document.getElementById('bs-form-save').addEventListener('click', onFormSave);
    }

    // -----------------------------------------------------------------
    // Block + row selection
    // -----------------------------------------------------------------

    function onBlockClick(idx, ev) {
        const block = document.querySelector(`#bs-ir-body .bs-block[data-idx="${idx}"]`);
        const isTable = block && block.dataset.type === 'table';
        if (isTable && !ev.shiftKey) {
            // Single-block tables only — clicking the cell area outside a row
            // sets anchor to the block; row clicks build row-range.
            setSingleAnchor(idx);
            return;
        }
        if (!ev.shiftKey || selectedBlocks.length === 0) {
            setSingleAnchor(idx);
        } else {
            // Extend range from anchor to idx
            const anchor = selectedBlocks[0].idx;
            const lo = Math.min(anchor, idx), hi = Math.max(anchor, idx);
            selectedBlocks = [];
            for (let i = lo; i <= hi; i++) {
                selectedBlocks.push({ idx: i, anchor: i === anchor });
            }
            selectedRows = null;
            paintSelection();
        }
    }

    function onRowClick(blockIdx, rowIdx, ev) {
        // Always restrict row picking to a single block annotation.
        if (selectedBlocks.length === 0 || selectedBlocks[0].idx !== blockIdx) {
            setSingleAnchor(blockIdx);
        }
        if (!selectedRows || selectedRows.blockIdx !== blockIdx) {
            selectedRows = { blockIdx, range: [rowIdx, rowIdx], anchor: rowIdx };
        } else if (ev.shiftKey) {
            const a = selectedRows.anchor;
            selectedRows.range = [Math.min(a, rowIdx), Math.max(a, rowIdx)];
        } else {
            selectedRows = { blockIdx, range: [rowIdx, rowIdx], anchor: rowIdx };
        }
        paintSelection();
    }

    function setSingleAnchor(idx) {
        selectedBlocks = [{ idx, anchor: true }];
        selectedRows = null;
        paintSelection();
    }

    function paintSelection() {
        document.querySelectorAll('.bs-block.bs-selected, .bs-block.bs-anchor').forEach(el => {
            el.classList.remove('bs-selected', 'bs-anchor');
        });
        document.querySelectorAll('.docx-block.bs-selected, .docx-block.bs-anchor').forEach(el => {
            el.classList.remove('bs-selected', 'bs-anchor');
        });
        document.querySelectorAll('.bs-row-pick.bs-row-selected, .bs-row-pick.bs-row-anchor').forEach(el => {
            el.classList.remove('bs-row-selected', 'bs-row-anchor');
        });
        selectedBlocks.forEach(b => {
            const el = document.querySelector(`#bs-ir-body .bs-block[data-idx="${b.idx}"]`);
            const docxEl = document.querySelector(`#bs-docx-body [data-block-idx="${b.idx}"]`);
            if (el) el.classList.add(b.anchor ? 'bs-anchor' : 'bs-selected');
            if (docxEl) docxEl.classList.add(b.anchor ? 'bs-anchor' : 'bs-selected');
        });
        if (selectedRows) {
            const blockEl = document.querySelector(`#bs-ir-body .bs-block[data-idx="${selectedRows.blockIdx}"]`);
            if (blockEl) {
                blockEl.querySelectorAll('.bs-row-pick').forEach(rowEl => {
                    const r = parseInt(rowEl.dataset.rowIdx, 10);
                    if (r === selectedRows.anchor) rowEl.classList.add('bs-row-anchor');
                    else if (r >= selectedRows.range[0] && r <= selectedRows.range[1]) rowEl.classList.add('bs-row-selected');
                });
            }
        }
    }

    // -----------------------------------------------------------------
    // Add → kind menu → form
    // -----------------------------------------------------------------

    function onAddClick(idx, ev) {
        if (selectedBlocks.length === 0 || selectedBlocks[0].idx !== idx) {
            // Use the clicked block as a fresh single-block anchor unless the
            // user has built a multi-block range that includes idx.
            const inRange = selectedBlocks.some(b => b.idx === idx);
            if (!inRange) setSingleAnchor(idx);
        }
        showKindMenu(ev.clientX, ev.clientY);
    }

    function showKindMenu(x, y) {
        const menu = document.getElementById('bs-kind-menu');
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';
        menu.classList.remove('d-none');
    }

    function hideKindMenu() {
        document.getElementById('bs-kind-menu').classList.add('d-none');
    }

    // -----------------------------------------------------------------
    // Form
    // -----------------------------------------------------------------

    function openForm(kind, existing) {
        document.getElementById('bs-form-title').textContent =
            (existing ? 'Edit' : 'Add') + ' annotation — ' + kind;
        document.getElementById('bs-form-region').innerHTML = describeRegion();
        const fields = KIND_FIELDS[kind] || [];
        const wrap = document.getElementById('bs-form-fields');
        wrap.innerHTML = '';
        fields.forEach(f => {
            const lbl = document.createElement('label');
            lbl.textContent = f.label;
            // For target.<sub> keys, pull from existing.target.<sub>
            let value;
            if (existing) {
                if (f.key.startsWith('target.')) {
                    const sub = f.key.slice(7);
                    value = existing.target ? existing.target[sub] : undefined;
                } else {
                    value = existing[f.key];
                }
            }
            const inp = buildInput(f, value);
            inp.dataset.key = f.key;
            inp.dataset.type = f.type;
            inp.dataset.required = f.required ? '1' : '0';
            wrap.appendChild(lbl);
            wrap.appendChild(inp);
        });
        document.getElementById('bs-form-notes').value =
            (existing && existing.notes) ? existing.notes : '';
        editingAnnId = existing ? existing.id : null;
        modal.show();
    }

    function buildInput(field, value) {
        if (field.type === 'enum') {
            const sel = document.createElement('select');
            sel.className = 'form-select form-select-sm';
            field.choices.forEach(c => {
                const o = document.createElement('option');
                o.value = c;
                o.textContent = c || '— none —';
                if (value !== undefined && c === value) o.selected = true;
                sel.appendChild(o);
            });
            return sel;
        }
        if (field.type === 'bool') {
            const sel = document.createElement('select');
            sel.className = 'form-select form-select-sm';
            ['', 'true', 'false'].forEach(c => {
                const o = document.createElement('option');
                o.value = c;
                o.textContent = c || '— none —';
                if (value !== undefined && c === String(value)) o.selected = true;
                sel.appendChild(o);
            });
            return sel;
        }
        if (field.type === 'int') {
            const inp = document.createElement('input');
            inp.type = 'number';
            inp.className = 'form-control form-control-sm';
            if (field.min !== undefined) inp.min = field.min;
            if (field.max !== undefined) inp.max = field.max;
            if (value !== undefined && value !== null) inp.value = value;
            return inp;
        }
        // string
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.className = 'form-control form-control-sm';
        if (field.placeholder) inp.placeholder = field.placeholder;
        if (value !== undefined) inp.value = value;
        return inp;
    }

    function describeRegion() {
        if (selectedRows) {
            const r = selectedRows.range;
            return `Region: block #${selectedRows.blockIdx}, rows ${r[0]}–${r[1]}`;
        }
        const ids = selectedBlocks.map(b => b.idx);
        if (ids.length === 1) return `Region: block #${ids[0]}`;
        return `Region: blocks ${ids[0]}–${ids[ids.length - 1]} (${ids.length} blocks)`;
    }

    function onFormSave() {
        const fields = document.getElementById('bs-form-fields').querySelectorAll('[data-key]');
        const payload = {
            kind: pendingKind,
            region: buildRegion(),
        };
        const target = {};
        let invalid = false;
        fields.forEach(inp => {
            const key = inp.dataset.key;
            const type = inp.dataset.type;
            const required = inp.dataset.required === '1';
            const raw = (inp.value || '').trim();
            if (!raw) {
                if (required) invalid = key;
                return;
            }
            let parsed;
            if (type === 'int') parsed = parseInt(raw, 10);
            else if (type === 'bool') parsed = (raw === 'true');
            else parsed = raw;
            if (key.startsWith('target.')) {
                target[key.slice(7)] = parsed;
            } else {
                payload[key] = parsed;
            }
        });
        if (invalid) {
            alert(`Field "${invalid}" is required for kind "${pendingKind}".`);
            return;
        }
        if (Object.keys(target).length) payload.target = target;
        const notes = document.getElementById('bs-form-notes').value.trim();
        if (notes) payload.notes = notes;

        const state = window._bsState;
        if (editingAnnId) {
            const i = state.annotations.findIndex(a => a.id === editingAnnId);
            if (i >= 0) {
                payload.id = editingAnnId;
                state.annotations[i] = payload;
            }
        } else {
            payload.id = nextAnnId(state.annotations);
            state.annotations.push(payload);
        }
        editingAnnId = null;
        renderAnnotations();
        modal.hide();
    }

    function buildRegion() {
        if (selectedRows) {
            return { block_index: selectedRows.blockIdx, row_range: selectedRows.range };
        }
        const ids = selectedBlocks.map(b => b.idx).sort((a, b) => a - b);
        return { block_indices: ids };
    }

    function nextAnnId(anns) {
        let max = 0;
        anns.forEach(a => {
            const m = /^ann_(\d+)$/.exec(a.id || '');
            if (m) max = Math.max(max, parseInt(m[1], 10));
        });
        return 'ann_' + String(max + 1).padStart(3, '0');
    }

    // -----------------------------------------------------------------
    // Annotation list rendering
    // -----------------------------------------------------------------

    function renderAnnotations() {
        const state = window._bsState || { annotations: [] };
        const list = document.getElementById('bs-ann-list');
        if (!list) return;
        document.getElementById('bs-ann-count').textContent =
            state.annotations.length + ' annotations';
        if (state.annotations.length === 0) {
            list.innerHTML = '<p class="text-muted small p-2">No annotations yet.</p>';
            return;
        }
        const grouped = {};
        state.annotations.forEach(a => {
            (grouped[a.kind] = grouped[a.kind] || []).push(a);
        });
        const parts = [];
        KIND_ORDER.forEach(kind => {
            const items = grouped[kind];
            if (!items) return;
            parts.push(`<div class="bs-ann-group">`);
            parts.push(`<div class="px-2 py-1 fw-semibold small bg-light border-bottom">${kind} (${items.length})</div>`);
            items.forEach(ann => {
                parts.push(renderAnnItem(ann));
            });
            parts.push(`</div>`);
        });
        list.innerHTML = parts.join('');
        list.querySelectorAll('.bs-ann-item').forEach(el => {
            const id = el.dataset.id;
            el.addEventListener('click', (ev) => {
                if (ev.target.closest('.bs-ann-del')) return;
                const ann = state.annotations.find(a => a.id === id);
                if (ann) {
                    scrollToRegion(ann.region);
                    pendingKind = ann.kind;
                    openForm(ann.kind, ann);
                }
            });
            const del = el.querySelector('.bs-ann-del');
            if (del) {
                del.addEventListener('click', (ev) => {
                    ev.stopPropagation();
                    state.annotations = state.annotations.filter(a => a.id !== id);
                    renderAnnotations();
                });
            }
        });
    }

    function renderAnnItem(ann) {
        const region = ann.region.block_indices
            ? '#' + (ann.region.block_indices.length === 1
                ? ann.region.block_indices[0]
                : `${ann.region.block_indices[0]}–${ann.region.block_indices[ann.region.block_indices.length - 1]}`)
            : `#${ann.region.block_index}` + (ann.region.row_range ? ` r${ann.region.row_range[0]}–${ann.region.row_range[1]}` : '');
        const meta = Object.entries(ann)
            .filter(([k]) => !['id', 'kind', 'region', 'notes', 'target'].includes(k))
            .map(([k, v]) => `${k}=${v}`)
            .join(' ');
        const targetMeta = ann.target
            ? '→ ' + Object.entries(ann.target).map(([k, v]) => `${k}=${v}`).join(' ')
            : '';
        return `<div class="bs-ann-item" data-id="${escapeAttr(ann.id)}">
          <span class="bs-ann-kind bs-ann-kind-${ann.kind}">${ann.kind}</span>
          <div class="flex-grow-1" style="min-width:0;">
            <div class="bs-ann-region">${escapeHtml(region)}</div>
            ${meta ? `<div class="bs-ann-meta">${escapeHtml(meta)}</div>` : ''}
            ${targetMeta ? `<div class="bs-ann-meta text-primary">${escapeHtml(targetMeta)}</div>` : ''}
            ${ann.notes ? `<div class="text-muted small fst-italic">${escapeHtml(ann.notes)}</div>` : ''}
          </div>
          <button class="btn btn-xs btn-outline-danger bs-ann-del ms-auto" title="Delete">✗</button>
        </div>`;
    }

    function scrollToRegion(region) {
        let idx = null;
        if (region.block_indices && region.block_indices.length) idx = region.block_indices[0];
        else if (region.block_index !== undefined) idx = region.block_index;
        if (idx == null) return;
        const el = document.querySelector(`#bs-ir-body .bs-block[data-idx="${idx}"]`);
        if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        const docxEl = document.querySelector(`#bs-docx-body [data-block-idx="${idx}"]`);
        if (docxEl) docxEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }

    // -----------------------------------------------------------------
    // Save
    // -----------------------------------------------------------------

    function saveAll() {
        const state = window._bsState;
        const ind = document.getElementById('bs-save-indicator');
        ind.textContent = 'Saving…';
        ind.className = 'small text-muted';
        const payload = {
            version: 1,
            doc_path: state.docPath,
            annotations: state.annotations,
        };
        fetch(ROOT + '/parse-review/bootstrap/' + encodeURIComponent(state.docId) + '/annotations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
            .then(r => r.json().then(j => ({ status: r.status, body: j })))
            .then(({ status, body }) => {
                if (status === 200 && body.ok) {
                    ind.textContent = `Saved · ${body.count} annotations · ${body.path}`;
                    ind.className = 'small text-success';
                } else {
                    const errs = (body && body.errors) ? body.errors.join(' · ') : (body && body.detail) || `HTTP ${status}`;
                    ind.textContent = 'Save failed: ' + errs;
                    ind.className = 'small text-danger';
                }
            })
            .catch(err => {
                ind.textContent = 'Save failed: ' + err;
                ind.className = 'small text-danger';
            });
    }

    // -----------------------------------------------------------------
    // Sync-scroll
    // -----------------------------------------------------------------

    let _syncing = false;
    function syncScroll(src, dst, srcSel, dstSel) {
        if (_syncing) return;
        _syncing = true;
        try {
            const srcRect = src.getBoundingClientRect();
            const midY = srcRect.top + srcRect.height / 2;
            const els = src.querySelectorAll(srcSel);
            let bestIdx = null, bestDist = Infinity;
            els.forEach(el => {
                const r = el.getBoundingClientRect();
                const d = Math.abs((r.top + r.bottom) / 2 - midY);
                if (d < bestDist) { bestDist = d; bestIdx = el.dataset.idx; }
            });
            if (bestIdx == null) return;
            const target = dst.querySelector(`${dstSel}[data-block-idx="${bestIdx}"]`);
            if (target) {
                const dstRect = dst.getBoundingClientRect();
                const tRect = target.getBoundingClientRect();
                dst.scrollTop += (tRect.top + tRect.height / 2) - (dstRect.top + dstRect.height / 2);
            }
        } finally {
            setTimeout(() => { _syncing = false; }, 50);
        }
    }

    // -----------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }
    function escapeAttr(s) { return escapeHtml(s); }
})();
