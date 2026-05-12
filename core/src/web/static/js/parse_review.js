/**
 * parse_review.js — 3-pane parse review interactivity.
 *
 * Exposes:
 *   window.initParseReview(docId, rootPath)  called after _view.html is injected
 *   prAccept(idx), prReject(idx), prShowAddMenu(event, idx)  — onclick targets
 *   prSave(), prReport(), prAddMissedAcr()   — toolbar buttons
 */
(function () {
    'use strict';

    /* -----------------------------------------------------------------------
     * Module-level state (reset on each initParseReview call)
     * --------------------------------------------------------------------- */
    let _docId   = null;
    let _root    = '';
    // blockIdx -> 'accepted' | 'rejected' | 'added'
    let _status  = {};
    // idx -> {reason: string}  for user-added annotations
    let _added   = {};

    /* -----------------------------------------------------------------------
     * Init — called once _view.html is in the DOM
     * --------------------------------------------------------------------- */
    window.initParseReview = function (docId, rootPath) {
        _docId  = docId;
        _root   = rootPath || '';
        _status = {};
        _added  = {};

        // Restore any existing review state from <script type="application/json">
        // nodes embedded by _view.html. We use textContent + JSON.parse because
        // inline <script> tags don't execute when injected via innerHTML.
        const _readJson = function (elId, fallback) {
            const el = document.getElementById(elId);
            if (!el) return fallback;
            try {
                return JSON.parse(el.textContent || 'null') ?? fallback;
            } catch (e) {
                console.error('Failed to parse ' + elId + ':', e);
                return fallback;
            }
        };
        window._prDocId  = _readJson('pr-state-docid',  docId);
        window._prReview = _readJson('pr-state-review', {});
        window._prLog    = _readJson('pr-state-log',    {});
        _restoreFromReview(window._prReview);

        _bindSyncScroll();
        _bindContextMenu();
        _renderStats();
    };

    /* -----------------------------------------------------------------------
     * Restore status from previously saved corrections
     * --------------------------------------------------------------------- */
    function _restoreFromReview(review) {
        const corr = (review.corrections) || {};

        // False-positive drops were rejected
        for (const fp of (corr.false_positive_drops || [])) {
            const idx = _findBlockIdxByPage(fp.pages);
            if (idx !== null) _setStatus(idx, 'rejected');
        }

        // User-added drops — apply the full visual treatment (badge,
        // superseded-strikethrough on parser badges, 💬 marker for
        // comments) so reload-after-save matches the just-clicked
        // experience. Previously only set ``_status``/``_added``, which
        // left the badge invisible on reload.
        for (const md of (corr.missed_drops || [])) {
            const idx = _findBlockIdxByPage(md.pages);
            if (idx !== null) {
                _applyAddedAnnotation(
                    idx, md.expected_reason, md.comment || "",
                );
            }
        }
    }

    /** Find first block on a given page string ("5" or "5-7"). Returns idx or null. */
    function _findBlockIdxByPage(pageStr) {
        if (!pageStr) return null;
        const startPage = parseInt(String(pageStr).split('-')[0], 10);
        const el = document.querySelector(`#pane-3-body [data-page="${startPage}"]`);
        return el ? parseInt(el.dataset.idx, 10) : null;
    }

    /* -----------------------------------------------------------------------
     * Accept / Reject / Add
     * --------------------------------------------------------------------- */
    window.prAccept = function (idx) {
        _setStatus(idx, 'accepted');
        _renderStats();
    };

    window.prReject = function (idx) {
        _setStatus(idx, 'rejected');
        _renderStats();
    };

    function _setStatus(idx, status) {
        _status[idx] = status;
        const el = document.getElementById('rv-' + idx);
        if (!el) return;
        el.classList.remove('rev-accepted', 'rev-rejected', 'rev-added');
        if (status === 'accepted') el.classList.add('rev-accepted');
        if (status === 'rejected') el.classList.add('rev-rejected');
        if (status === 'added')    el.classList.add('rev-added');
    }

    /* -----------------------------------------------------------------------
     * Context menu — right-click to add annotation on any pane-3 block
     * --------------------------------------------------------------------- */
    let _ctxTargetIdx = null;

    window.prShowAddMenu = function (event, idx) {
        event.preventDefault();
        event.stopPropagation();
        _ctxTargetIdx = idx;
        _showCtxMenu(event.clientX, event.clientY);
    };

    function _bindContextMenu() {
        const body = document.getElementById('pane-3-body');
        if (!body) return;

        body.addEventListener('contextmenu', function (e) {
            e.preventDefault();
            // Find the closest review-block
            const blk = e.target.closest('.review-block');
            if (!blk) return;
            _ctxTargetIdx = parseInt(blk.dataset.idx, 10);
            _showCtxMenu(e.clientX, e.clientY);
        });

        // Close on outside click
        document.addEventListener('click', _hideCtxMenu, true);
    }

    function _showCtxMenu(x, y) {
        const menu = document.getElementById('pr-ctx-menu');
        if (!menu) return;
        menu.classList.remove('d-none');
        // Clamp to viewport
        const vw = window.innerWidth, vh = window.innerHeight;
        const mw = 220, mh = 180;
        menu.style.left = Math.min(x, vw - mw) + 'px';
        menu.style.top  = Math.min(y, vh - mh) + 'px';

        // Wire items (remove old listeners first by replacing nodes)
        menu.querySelectorAll('.ctx-menu-item').forEach(function (item) {
            const clone = item.cloneNode(true);
            item.parentNode.replaceChild(clone, item);
            clone.addEventListener('click', function (ev) {
                const reason = clone.dataset.reason;
                _hideCtxMenu();
                if (reason === '__clear') {
                    _clearAnnotation(_ctxTargetIdx);
                } else if (reason && reason !== '__cancel') {
                    // Promote into the comment prompt before committing.
                    // Existing comment (if user is re-editing) prefills
                    // the textarea so they can refine instead of retype.
                    const existing = _added[_ctxTargetIdx];
                    _showCommentPrompt(
                        ev.clientX, ev.clientY,
                        _ctxTargetIdx, reason,
                        existing && existing.reason === reason ? existing.comment : "",
                    );
                }
            });
        });
    }

    function _hideCtxMenu() {
        const menu = document.getElementById('pr-ctx-menu');
        if (menu) menu.classList.add('d-none');
    }

    /* -----------------------------------------------------------------------
     * Optional comment prompt — runs between context-menu click and the
     * actual annotation apply. User can save with text, skip (empty
     * comment), or Esc out (cancel entirely).
     * --------------------------------------------------------------------- */
    function _showCommentPrompt(x, y, idx, reason, prefill) {
        const panel = document.getElementById('pr-comment-prompt');
        const text  = document.getElementById('pr-comment-text');
        const kind  = document.getElementById('pr-comment-kind');
        const save  = document.getElementById('pr-comment-save');
        const skip  = document.getElementById('pr-comment-skip');
        if (!panel || !text || !kind || !save || !skip) return;

        kind.textContent =
            'Kind: ' + reason.replace(/_/g, '-').toUpperCase();
        text.value = prefill || '';
        panel.classList.remove('d-none');
        // Position near the click; clamp to viewport. Reuses the
        // context-menu style so it visually belongs to the same flow.
        const vw = window.innerWidth, vh = window.innerHeight;
        const pw = 340, ph = 180;
        panel.style.left = Math.min(x, vw - pw) + 'px';
        panel.style.top  = Math.min(y, vh - ph) + 'px';
        text.focus();

        // Replace old listeners to avoid duplicate dispatch.
        const newSave = save.cloneNode(true);
        const newSkip = skip.cloneNode(true);
        save.parentNode.replaceChild(newSave, save);
        skip.parentNode.replaceChild(newSkip, skip);

        function _commit(comment) {
            panel.classList.add('d-none');
            text.removeEventListener('keydown', _onKey);
            _applyAddedAnnotation(idx, reason, comment);
        }
        function _bail() {
            panel.classList.add('d-none');
            text.removeEventListener('keydown', _onKey);
        }
        function _onKey(e) {
            if (e.key === 'Escape') { _bail(); }
            // Ctrl+Enter saves; plain Enter inserts a newline so users
            // can write multi-line notes without committing accidentally.
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                _commit(text.value.trim());
            }
        }
        text.addEventListener('keydown', _onKey);
        newSave.addEventListener('click', function () {
            _commit(text.value.trim());
        });
        newSkip.addEventListener('click', function () {
            _commit("");
        });
    }

    function _applyAddedAnnotation(idx, reason, comment) {
        if (idx === null || idx === undefined) return;
        _added[idx] = { reason, comment: comment || "" };
        _setStatus(idx, 'added');

        // Insert a small badge into the block if it doesn't already
        // show one. The badge class encodes the reason so
        // ``_clearAnnotation`` can remove the right element when the
        // user later changes their mind.
        const el = document.getElementById('rv-' + idx);
        if (el) {
            const cls = 'ann-badge-added-' + reason;
            let badge = el.querySelector('.' + cls);
            if (!badge) {
                badge = document.createElement('span');
                badge.className = 'ann-badge ann-badge-added me-1 ' + cls;
                badge.style.background = '#f59e0b';
                badge.style.color = '#fff';
                badge.textContent = '+' + reason.replace(/_/g, '-').toUpperCase();
                // Insert before the block content (after page badge and existing badges)
                const ref = el.querySelector('p, .table-responsive, span.text-muted');
                el.insertBefore(badge, ref || null);
            }
            // Append a 💬 marker when the user supplied a comment;
            // hover-tooltip surfaces the comment text. The marker is
            // a child of the badge so it sticks together visually and
            // gets removed with the badge on clear.
            const oldNote = badge.querySelector('.ann-comment-marker');
            if (oldNote) oldNote.remove();
            if (comment) {
                const note = document.createElement('span');
                note.className = 'ann-comment-marker ms-1';
                note.textContent = '💬';
                note.title = comment;
                note.style.cursor = 'help';
                badge.appendChild(note);
            }
            // Strike through the parser's original ``ann-badge-*``
            // labels on this block to signal "the parser said X, but
            // user is correcting it to Y". The original badge stays
            // visible (audit trail) but is visually subdued.
            el.querySelectorAll('.ann-badge').forEach(function (b) {
                if (!b.classList.contains('ann-badge-added')) {
                    b.classList.add('ann-badge-superseded');
                }
            });
        }
        _renderStats();
    }

    function _clearAnnotation(idx) {
        if (idx === null || idx === undefined) return;
        // Drop internal state — both the user-added pending change AND
        // any accepted/rejected status the user toggled on the
        // pipeline-detected drop. ``__clear`` is the single revert
        // verb regardless of how the block got into its current state.
        delete _added[idx];
        delete _status[idx];

        const el = document.getElementById('rv-' + idx);
        if (el) {
            // Remove status CSS classes painted by ``_setStatus``.
            el.classList.remove('rev-accepted', 'rev-rejected', 'rev-added');
            // Remove any user-added badges previously inserted by
            // ``_applyAddedAnnotation``. The original parse-stage badges
            // (page number, drop reason, etc.) carry different class
            // names and are intentionally preserved.
            el.querySelectorAll('.ann-badge-added').forEach(function (b) {
                b.remove();
            });
            // Restore parser-emitted badges to full opacity (undo the
            // ``ann-badge-superseded`` strike-through applied by
            // ``_applyAddedAnnotation``).
            el.querySelectorAll('.ann-badge-superseded').forEach(function (b) {
                b.classList.remove('ann-badge-superseded');
            });
        }
        _renderStats();
    }

    /* -----------------------------------------------------------------------
     * Sync scroll
     * --------------------------------------------------------------------- */
    function _bindSyncScroll() {
        const toggle = document.getElementById('sync-scroll-toggle');
        if (!toggle) return;

        const bodies = [
            document.getElementById('pane-1-body'),
            document.getElementById('pane-2-body'),
            document.getElementById('pane-3-body'),
        ].filter(Boolean);

        let syncing = false;

        bodies.forEach(function (src) {
            src.addEventListener('scroll', function () {
                if (!toggle.checked || syncing) return;
                syncing = true;
                const ratio = src.scrollTop / Math.max(1, src.scrollHeight - src.clientHeight);
                bodies.forEach(function (tgt) {
                    if (tgt !== src) {
                        tgt.scrollTop = ratio * (tgt.scrollHeight - tgt.clientHeight);
                    }
                });
                syncing = false;
            });
        });
    }

    /* -----------------------------------------------------------------------
     * Stats display
     * --------------------------------------------------------------------- */
    function _renderStats() {
        const el = document.getElementById('rv-stats');
        if (!el) return;
        const accepted = Object.values(_status).filter(s => s === 'accepted').length;
        const rejected = Object.values(_status).filter(s => s === 'rejected').length;
        const added    = Object.values(_status).filter(s => s === 'added').length;
        el.textContent =
            (accepted ? accepted + ' accepted  ' : '') +
            (rejected ? rejected + ' rejected  ' : '') +
            (added    ? added    + ' added'       : '');
    }

    /* -----------------------------------------------------------------------
     * Build corrections JSON from current UI state
     * --------------------------------------------------------------------- */
    function _buildCorrections() {
        const fpDrops = [];
        const missedDrops = [];

        // Walk pane-3 blocks
        document.querySelectorAll('#pane-3-body .review-block').forEach(function (el) {
            const idx  = parseInt(el.dataset.idx, 10);
            const page = el.dataset.page;
            const status = _status[idx];
            const anns = JSON.parse(el.dataset.anns || '[]');

            if (status === 'rejected' && anns.length > 0) {
                // Each annotation on this block is a false positive
                anns.forEach(function (ann) {
                    if (ann.type.startsWith('dropped_')) {
                        fpDrops.push({ pages: page, reason: ann.reason || ann.type.replace('dropped_', '') });
                    }
                });
            }

            if (status === 'added' && _added[idx]) {
                const entry = {
                    pages: page,
                    expected_reason: _added[idx].reason,
                };
                // Carry the user comment when present so the
                // correction→regex CLI can read the rationale per
                // entry. Empty string is omitted to keep the saved
                // JSON small for the common-case (no-comment) flow.
                if (_added[idx].comment) {
                    entry.comment = _added[idx].comment;
                }
                missedDrops.push(entry);
            }
        });

        // Acronym corrections
        const acrWrong = [], acrExtra = [], acrMissed = [];
        document.querySelectorAll('.acr-correction').forEach(function (input) {
            const acr      = input.dataset.acronym;
            const original = input.dataset.original;
            const corrected = input.value.trim();
            const statusSel = input.closest('.d-flex')?.querySelector('.acr-status');
            const statusVal = statusSel ? statusSel.value : 'ok';

            if (statusVal === 'wrong' && corrected && corrected !== original) {
                acrWrong.push({ acronym: acr, correct: corrected });
            } else if (statusVal === 'extra') {
                acrExtra.push({ acronym: acr });
            }
        });

        document.querySelectorAll('.missed-acr-row').forEach(function (row) {
            const inputs = row.querySelectorAll('input');
            const acr  = inputs[0]?.value.trim() || '';
            const exp  = inputs[1]?.value.trim() || '';
            if (acr) acrMissed.push({ acronym: acr, expansion: exp });
        });

        return {
            false_positive_drops: fpDrops,
            missed_drops: missedDrops,
            toc_error: null,
            revhist_error: null,
            glossary_error: null,
            acronym_wrong_expansion: acrWrong,
            acronym_missed: acrMissed,
            acronym_extra: acrExtra,
        };
    }

    function _buildReviewPayload() {
        return {
            doc_id:          _docId,
            reviewer:        (document.getElementById('rv-reviewer')?.value || '').trim(),
            review_date:     (document.getElementById('rv-date')?.value     || '').trim(),
            overall_verdict: (document.getElementById('rv-verdict')?.value  || '').trim(),
            corrections:     _buildCorrections(),
            notes:           (document.getElementById('rv-notes')?.value    || '').trim(),
        };
    }

    /* -----------------------------------------------------------------------
     * Save
     * --------------------------------------------------------------------- */
    window.prSave = function () {
        const payload = _buildReviewPayload();
        const btn = document.getElementById('btn-save');
        const indicator = document.getElementById('save-indicator');

        const setBtnState = function (cls, label) {
            if (!btn) return;
            btn.classList.remove('btn-primary', 'btn-success', 'btn-danger', 'btn-warning');
            btn.classList.add(cls);
            btn.innerHTML = label;
        };
        const setIndicator = function (text, cls) {
            if (!indicator) return;
            indicator.className = 'small ' + (cls || 'text-muted');
            indicator.textContent = text || '';
        };

        setBtnState('btn-warning', '<i class="bi bi-hourglass-split me-1"></i>Saving…');
        setIndicator('Saving…', 'text-warning');

        fetch(_root + '/parse-review/' + encodeURIComponent(_docId) + '/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        .then(r => r.json())
        .then(function (data) {
            if (data.ok) {
                setBtnState('btn-success', '<i class="bi bi-check-lg me-1"></i>Saved');
                const corrPath = data.corrections_path || '';
                setIndicator(
                    '✓ Saved · corrections → ' + corrPath,
                    'text-success',
                );
            } else {
                setBtnState('btn-danger', '<i class="bi bi-x-lg me-1"></i>Failed');
                setIndicator('✗ ' + (data.error || 'save failed'), 'text-danger');
            }
            setTimeout(function () {
                setBtnState('btn-primary', '<i class="bi bi-save me-1"></i>Save');
            }, 3000);
        })
        .catch(function (err) {
            setBtnState('btn-danger', '<i class="bi bi-x-lg me-1"></i>Failed');
            setIndicator('✗ ' + err, 'text-danger');
            setTimeout(function () {
                setBtnState('btn-primary', '<i class="bi bi-save me-1"></i>Save');
            }, 3000);
        });
    };

    /* -----------------------------------------------------------------------
     * Report
     * --------------------------------------------------------------------- */
    window.prReport = function () {
        const payload = _buildReviewPayload();
        const out = document.getElementById('report-output');
        if (out) out.innerHTML = '<div class="text-muted small py-1">Generating…</div>';

        fetch(_root + '/parse-review/' + encodeURIComponent(_docId) + '/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        .then(r => r.text())
        .then(function (html) {
            if (out) out.innerHTML = html;
        })
        .catch(function (err) {
            if (out) out.innerHTML = '<div class="alert alert-danger small">Report failed: ' + err + '</div>';
        });
    };

    /* -----------------------------------------------------------------------
     * Add missed acronym row
     * --------------------------------------------------------------------- */
    window.prAddMissedAcr = function () {
        const container = document.getElementById('missed-acr-rows');
        if (!container) return;
        const row = document.createElement('div');
        row.className = 'd-flex gap-1 mb-1 missed-acr-row';
        row.innerHTML =
            '<input type="text" class="form-control form-control-sm" placeholder="Acronym" style="max-width:90px">' +
            '<input type="text" class="form-control form-control-sm" placeholder="Expansion">' +
            '<button class="btn btn-xs btn-outline-danger" onclick="this.closest(\'.missed-acr-row\').remove()">✕</button>';
        container.appendChild(row);
    };

}());
