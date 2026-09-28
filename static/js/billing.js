/**
 * Cart logic, mandatory disambiguation (keyboard + filters), carton qty chips.
 */
(function () {
  const PREF_KEY = 'billing_preferred_models';

  function loadPreferredModels() {
    try {
      const raw = sessionStorage.getItem(PREF_KEY);
      if (!raw) return [];
      const arr = JSON.parse(raw);
      return Array.isArray(arr) ? arr.filter((m) => typeof m === 'string' && m.trim()) : [];
    } catch (_) {
      return [];
    }
  }

  const state = {
    cart: [], // {item_id, item_code, model, name, cp, foc_qty, foc_units, ctn_qty, qty}
    pending: [], // parsed groups awaiting resolution
    focus: { groupIndex: 0, matchIndex: 0 },
    preferredModels: loadPreferredModels(),
  };

  window.__billingCart = state;

  function money(n) {
    return Number(n || 0).toFixed(2);
  }

  function persistPreferred() {
    sessionStorage.setItem(PREF_KEY, JSON.stringify(state.preferredModels));
  }

  function rememberModel(model) {
    const m = (model || '').trim();
    if (!m) return;
    const exists = state.preferredModels.some((x) => x.toLowerCase() === m.toLowerCase());
    if (!exists) {
      state.preferredModels.push(m);
      persistPreferred();
      renderModelLock();
    }
  }

  function clearPreferredModels() {
    state.preferredModels = [];
    sessionStorage.removeItem(PREF_KEY);
    // also clear legacy single-key if present
    sessionStorage.removeItem('billing_locked_model');
    renderModelLock();
  }

  window.clearPreferredModels = clearPreferredModels;

  function renderModelLock() {
    const bar = document.getElementById('model-lock-bar');
    const nameEl = document.getElementById('model-lock-name');
    if (!bar || !nameEl) return;
    if (state.preferredModels.length) {
      nameEl.textContent = state.preferredModels.join(', ');
      bar.classList.remove('hidden');
      bar.classList.add('flex');
    } else {
      bar.classList.add('hidden');
      bar.classList.remove('flex');
    }
  }

  function sortMatchesByPreference(matches) {
    if (!state.preferredModels.length || !matches || !matches.length) return matches || [];
    const prefs = state.preferredModels.map((p) => p.toLowerCase());
    function rank(m) {
      const model = (m.model || '').toLowerCase();
      for (let i = 0; i < prefs.length; i++) {
        const p = prefs[i];
        if (model.includes(p) || p.includes(model)) return i;
      }
      return prefs.length;
    }
    const yes = [];
    const no = [];
    matches.forEach((m) => {
      if (rank(m) < prefs.length) yes.push(m);
      else no.push(m);
    });
    yes.sort((a, b) => rank(a) - rank(b));
    return yes.concat(no);
  }

  function focPreview(item) {
    if (item.foc_qty && item.foc_units) {
      return `Buy ${item.foc_qty} get ${item.foc_units} FOC`;
    }
    return 'No FOC';
  }

  function lineTotal(item) {
    return Number(item.cp) * Number(item.qty);
  }

  function cartGrandTotal() {
    return state.cart.reduce((s, it) => s + lineTotal(it), 0);
  }

  function ctnLabel(ctn) {
    const n = Number(ctn);
    if (!n || n < 1) return null;
    return n;
  }

  function qtyChipsHtml(attrs, ctnQty, currentQty) {
    const ctn = ctnLabel(ctnQty);
    let html = `
      <button type="button" class="qty-chip" data-qty-delta="1" ${attrs}>+1</button>
      <button type="button" class="qty-chip" data-qty-delta="10" ${attrs}>+10</button>`;
    if (ctn) {
      html += `<button type="button" class="qty-chip" data-qty-set="${ctn}" ${attrs} title="1 carton">+${ctn} ctn</button>`;
      html += `<button type="button" class="qty-chip" data-qty-add-ctn="${ctn}" ${attrs} title="Add one carton">+1 ctn</button>`;
    }
    return html;
  }

  function renderCart() {
    const list = document.getElementById('cart-list');
    const totalEl = document.getElementById('cart-total');
    const previewBtn = document.getElementById('preview-bill-btn');
    if (!list) return;

    if (!state.cart.length) {
      list.innerHTML = '<p class="text-slate-500">Cart is empty</p>';
    } else {
      list.innerHTML = state.cart
        .map((it, idx) => {
          const focNote =
            it.foc_qty && it.qty >= it.foc_qty
              ? `<div class="text-xs text-green-700">FOC will apply (+${it.foc_units} free)</div>`
              : '';
          const ctn = ctnLabel(it.ctn_qty);
          return `
          <div class="border border-slate-200 rounded-lg p-2 bg-white/80">
            <div class="flex justify-between gap-2">
              <div>
                <div class="font-medium">${it.name}</div>
                <div class="text-xs text-slate-500 font-mono">${it.item_code || ''} · ${it.model || '—'}${ctn ? ' · ctn ' + ctn : ''}</div>
                ${focNote}
              </div>
              <button data-remove="${idx}" class="text-slate-400 hover:text-red-600 text-xs">Remove</button>
            </div>
            <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
              <div class="flex flex-wrap items-center gap-1">
                <label class="text-xs">Qty
                  <input data-qty="${idx}" type="number" min="1" value="${it.qty}"
                    class="ml-1 w-16 border rounded px-1 py-0.5" />
                </label>
                ${qtyChipsHtml(`data-cart-idx="${idx}"`, it.ctn_qty)}
              </div>
              <span>${money(lineTotal(it))} PKR</span>
            </div>
          </div>`;
        })
        .join('');
    }

    totalEl.textContent = money(cartGrandTotal());
    if (previewBtn) previewBtn.disabled = state.cart.length === 0;

    list.querySelectorAll('[data-remove]').forEach((btn) => {
      btn.addEventListener('click', () => {
        state.cart.splice(Number(btn.getAttribute('data-remove')), 1);
        renderCart();
      });
    });
    list.querySelectorAll('[data-qty]').forEach((input) => {
      input.addEventListener('change', () => {
        const idx = Number(input.getAttribute('data-qty'));
        const v = Math.max(1, parseInt(input.value, 10) || 1);
        state.cart[idx].qty = v;
        input.value = v;
        renderCart();
      });
    });
    list.querySelectorAll('[data-cart-idx][data-qty-delta]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.getAttribute('data-cart-idx'));
        const delta = Number(btn.getAttribute('data-qty-delta'));
        state.cart[idx].qty = Math.max(1, state.cart[idx].qty + delta);
        renderCart();
      });
    });
    list.querySelectorAll('[data-cart-idx][data-qty-set]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.getAttribute('data-cart-idx'));
        state.cart[idx].qty = Math.max(1, Number(btn.getAttribute('data-qty-set')));
        renderCart();
      });
    });
    list.querySelectorAll('[data-cart-idx][data-qty-add-ctn]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const idx = Number(btn.getAttribute('data-cart-idx'));
        const ctn = Number(btn.getAttribute('data-qty-add-ctn'));
        state.cart[idx].qty = Math.max(1, state.cart[idx].qty + ctn);
        renderCart();
      });
    });
  }

  function addToCart(item, qty) {
    const id = item.id ?? item.item_id;
    const existing = state.cart.find((c) => c.item_id === id);
    if (existing) {
      existing.qty += qty;
      if (!existing.ctn_qty && item.ctn_qty) existing.ctn_qty = item.ctn_qty;
    } else {
      state.cart.push({
        item_id: id,
        item_code: item.item_code,
        model: item.model,
        name: item.name,
        cp: item.cp,
        foc_qty: item.foc_qty,
        foc_units: item.foc_units,
        ctn_qty: item.ctn_qty || null,
        qty,
      });
    }
    // Remember every selected model for this bill (additive — does not replace others)
    rememberModel(item.model);
    renderCart();
  }

  function needsDisambiguation(group) {
    if (!group.matches || group.matches.length === 0) return true;
    if (group.matches.length > 1) return true;
    if (group.confidence === 'ambiguous') return true;
    return false;
  }

  function uniqueModels(matches) {
    const set = new Set();
    (matches || []).forEach((m) => {
      const model = (m.model || '').trim();
      if (model) set.add(model);
    });
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }

  function filteredMatches(group) {
    let matches = sortMatchesByPreference(group.matches || []);
    const filter = (group.modelFilter || '').trim().toLowerCase();
    if (!filter) return matches;
    const filtered = matches.filter((m) => (m.model || '').toLowerCase().includes(filter));
    // If filter hides everything (e.g. preferred model has no such part), show all
    if (!filtered.length && matches.length) {
      return matches;
    }
    return filtered;
  }

  function isPreferredModel(model) {
    if (!state.preferredModels.length || !model) return false;
    const m = String(model).toLowerCase();
    return state.preferredModels.some((p) => m.includes(p.toLowerCase()) || p.toLowerCase().includes(m));
  }

  function visibleMatchCards() {
    return Array.from(document.querySelectorAll('#disambiguation-list .match-card[data-nav="1"]'));
  }

  function applyFocusStyles() {
    const cards = visibleMatchCards();
    cards.forEach((c) => c.classList.remove('focused'));
    // Flatten focus across groups by walking visible cards
    let idx = 0;
    let target = null;
    for (const group of state.pending.filter((g) => !g.resolved)) {
      const matches = filteredMatches(group);
      for (let mi = 0; mi < matches.length; mi++) {
        if (
          state.focus.groupIndex === state.pending.indexOf(group) &&
          state.focus.matchIndex === mi
        ) {
          target = idx;
        }
        idx++;
      }
    }
    if (cards.length && target != null && cards[target]) {
      cards[target].classList.add('focused');
      cards[target].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    } else if (cards.length) {
      // fallback first card
      cards[0].classList.add('focused');
    }
  }

  function moveFocus(delta) {
    const pending = state.pending.filter((g) => !g.resolved);
    if (!pending.length) return;

    // Build flat list of (groupIndex, matchIndex)
    const flat = [];
    pending.forEach((g) => {
      const gi = state.pending.indexOf(g);
      filteredMatches(g).forEach((_, mi) => flat.push({ gi, mi }));
    });
    if (!flat.length) return;

    let cur = flat.findIndex(
      (f) => f.gi === state.focus.groupIndex && f.mi === state.focus.matchIndex
    );
    if (cur < 0) cur = 0;
    cur = (cur + delta + flat.length) % flat.length;
    state.focus.groupIndex = flat[cur].gi;
    state.focus.matchIndex = flat[cur].mi;
    applyFocusStyles();
  }

  function toggleFocusedSelection() {
    const group = state.pending[state.focus.groupIndex];
    if (!group || group.resolved) return;
    const matches = filteredMatches(group);
    const m = matches[state.focus.matchIndex];
    if (!m) return;
    group.selected = group.selected || {};
    if (group.selected[m.id]) {
      delete group.selected[m.id];
    } else {
      group.selected[m.id] = { qty: group.qty || 1 };
    }
    renderDisambiguation();
  }

  function renderDisambiguation() {
    const panel = document.getElementById('disambiguation');
    const list = document.getElementById('disambiguation-list');
    if (!panel || !list) return;

    const pending = state.pending.filter((g) => !g.resolved);
    if (!pending.length) {
      panel.classList.add('hidden');
      return;
    }
    panel.classList.remove('hidden');

    // Ensure focus points at a valid pending group
    if (!pending.includes(state.pending[state.focus.groupIndex])) {
      state.focus.groupIndex = state.pending.indexOf(pending[0]);
      state.focus.matchIndex = 0;
    }

    list.innerHTML = pending
      .map((group) => {
        const realIndex = state.pending.indexOf(group);
        const models = uniqueModels(group.matches);
        const filter = group.modelFilter || '';
        const matches = filteredMatches(group);
        const filterEmptyFallback =
          filter &&
          (group.matches || []).length > 0 &&
          !(group.matches || []).some((m) =>
            (m.model || '').toLowerCase().includes(filter.toLowerCase())
          );

        const chips =
          models.length > 1
            ? `<div class="flex flex-wrap gap-1 mb-2">
                <button type="button" class="model-chip ${!filter || filterEmptyFallback ? 'active' : ''}" data-filter-group="${realIndex}" data-filter="">All</button>
                ${models
                  .map(
                    (mod) =>
                      `<button type="button" class="model-chip ${!filterEmptyFallback && filter.toLowerCase() === mod.toLowerCase() ? 'active' : ''}"
                        data-filter-group="${realIndex}" data-filter="${mod.replace(/"/g, '&quot;')}">${mod}</button>`
                  )
                  .join('')}
              </div>
              ${
                filterEmptyFallback
                  ? `<p class="text-xs text-amber-800 mb-2">No “${filter}” variant for this part — showing all models.</p>`
                  : `<input type="search" placeholder="Filter model…" value="${filter.replace(/"/g, '&quot;')}"
                data-filter-input="${realIndex}"
                class="mb-2 w-full max-w-xs rounded border border-slate-300 px-2 py-1 text-sm" />`
              }`
            : '';

        const cards = matches.length
          ? matches
              .map((m, mi) => {
                const key = `${realIndex}:${m.id}`;
                const selected = group.selected && group.selected[m.id];
                const focused =
                  state.focus.groupIndex === realIndex && state.focus.matchIndex === mi;
                const ctn = ctnLabel(m.ctn_qty);
                const preferred = isPreferredModel(m.model);
                return `
              <div class="match-card block border rounded-lg p-2 ${selected ? 'selected' : ''} ${focused ? 'focused' : ''} ${preferred ? 'border-teal-300 bg-teal-50/40' : ''}"
                   data-nav="1" data-group="${realIndex}" data-match-idx="${mi}" data-id="${m.id}" tabindex="-1">
                <div class="flex items-start gap-2">
                  <input type="checkbox" data-group="${realIndex}" data-id="${m.id}"
                    ${selected ? 'checked' : ''} class="mt-1" />
                  <div class="flex-1 text-sm">
                    <div class="font-mono text-xs text-slate-500">${m.item_code || ''}${preferred ? ' · <span class="text-teal-700">preferred</span>' : ''}</div>
                    <div class="font-medium">${m.model || '—'} · ${m.name}</div>
                    <div class="text-xs text-slate-600">CP ${money(m.cp)} PKR · ${focPreview(m)}${ctn ? ' · ctn ' + ctn : ''}</div>
                    <div class="mt-1 ${selected ? '' : 'hidden'}" data-qty-wrap="${key}">
                      <div class="flex flex-wrap items-center gap-1">
                        Qty <input type="number" min="1" value="${selected ? selected.qty : group.qty || 1}"
                          data-qty-for="${realIndex}" data-qty-id="${m.id}"
                          class="w-16 border rounded px-1 py-0.5" />
                        ${qtyChipsHtml(`data-disambig-g="${realIndex}" data-disambig-id="${m.id}"`, m.ctn_qty)}
                      </div>
                    </div>
                  </div>
                </div>
              </div>`;
              })
              .join('')
          : `<p class="text-sm text-amber-700">No catalog matches. Search manually below.</p>`;

        return `
        <div class="border border-amber-200 bg-amber-50/50 rounded-xl p-3" data-pending-group="${realIndex}">
          <div class="text-sm mb-2">
            <span class="font-medium">“${group.spoken || group.item}”</span>
            <span class="text-slate-500"> · qty ${group.qty || 1}
            ${group.model ? ' · said model ' + group.model : ''}
            · ${group.confidence || 'ambiguous'}
            · ${matches.length}/${(group.matches || []).length} shown</span>
          </div>
          ${chips}
          <div class="grid sm:grid-cols-2 gap-2">${cards}</div>
        </div>`;
      })
      .join('');

    list.querySelectorAll('input[type=checkbox][data-group]').forEach((cb) => {
      cb.addEventListener('change', () => {
        const gi = Number(cb.getAttribute('data-group'));
        const id = Number(cb.getAttribute('data-id'));
        const group = state.pending[gi];
        group.selected = group.selected || {};
        if (cb.checked) {
          const qtyInput = list.querySelector(`[data-qty-for="${gi}"][data-qty-id="${id}"]`);
          group.selected[id] = {
            qty: qtyInput ? Math.max(1, parseInt(qtyInput.value, 10) || group.qty || 1) : group.qty || 1,
          };
        } else {
          delete group.selected[id];
        }
        // keep keyboard focus on this card
        const matches = filteredMatches(group);
        const mi = matches.findIndex((m) => m.id === id);
        if (mi >= 0) {
          state.focus.groupIndex = gi;
          state.focus.matchIndex = mi;
        }
        renderDisambiguation();
      });
    });

    list.querySelectorAll('input[data-qty-for]').forEach((input) => {
      input.addEventListener('change', () => {
        const gi = Number(input.getAttribute('data-qty-for'));
        const id = Number(input.getAttribute('data-qty-id'));
        const group = state.pending[gi];
        if (group.selected && group.selected[id]) {
          group.selected[id].qty = Math.max(1, parseInt(input.value, 10) || 1);
        }
      });
      input.addEventListener('keydown', (e) => e.stopPropagation());
    });

    list.querySelectorAll('[data-filter-group]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const gi = Number(btn.getAttribute('data-filter-group'));
        state.pending[gi].modelFilter = btn.getAttribute('data-filter') || '';
        state.focus.groupIndex = gi;
        state.focus.matchIndex = 0;
        renderDisambiguation();
      });
    });

    list.querySelectorAll('[data-filter-input]').forEach((input) => {
      input.addEventListener('input', () => {
        const gi = Number(input.getAttribute('data-filter-input'));
        state.pending[gi].modelFilter = input.value;
        state.focus.groupIndex = gi;
        state.focus.matchIndex = 0;
        // Debounce-ish: re-render but restore focus to input
        const pos = input.selectionStart;
        renderDisambiguation();
        const again = document.querySelector(`[data-filter-input="${gi}"]`);
        if (again) {
          again.focus();
          try {
            again.setSelectionRange(pos, pos);
          } catch (_) {}
        }
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          moveFocus(e.key === 'ArrowDown' ? 1 : -1);
        } else {
          e.stopPropagation();
        }
      });
    });

    // Disambiguation qty chips
    list.querySelectorAll('[data-disambig-g][data-qty-delta]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        bumpDisambigQty(
          Number(btn.getAttribute('data-disambig-g')),
          Number(btn.getAttribute('data-disambig-id')),
          Number(btn.getAttribute('data-qty-delta')),
          null
        );
      });
    });
    list.querySelectorAll('[data-disambig-g][data-qty-set]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        bumpDisambigQty(
          Number(btn.getAttribute('data-disambig-g')),
          Number(btn.getAttribute('data-disambig-id')),
          null,
          Number(btn.getAttribute('data-qty-set'))
        );
      });
    });
    list.querySelectorAll('[data-disambig-g][data-qty-add-ctn]').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const gi = Number(btn.getAttribute('data-disambig-g'));
        const id = Number(btn.getAttribute('data-disambig-id'));
        const ctn = Number(btn.getAttribute('data-qty-add-ctn'));
        const group = state.pending[gi];
        group.selected = group.selected || {};
        const cur = (group.selected[id] && group.selected[id].qty) || group.qty || 1;
        group.selected[id] = { qty: cur + ctn };
        renderDisambiguation();
      });
    });

    // Click card to focus
    list.querySelectorAll('.match-card[data-nav]').forEach((card) => {
      card.addEventListener('click', (e) => {
        if (e.target.closest('input, button')) return;
        state.focus.groupIndex = Number(card.getAttribute('data-group'));
        state.focus.matchIndex = Number(card.getAttribute('data-match-idx'));
        applyFocusStyles();
      });
    });

    updateConfirmEnabled();
    applyFocusStyles();
  }

  function bumpDisambigQty(gi, id, delta, setTo) {
    const group = state.pending[gi];
    group.selected = group.selected || {};
    if (!group.selected[id]) {
      group.selected[id] = { qty: group.qty || 1 };
    }
    if (setTo != null) {
      group.selected[id].qty = Math.max(1, setTo);
    } else {
      group.selected[id].qty = Math.max(1, group.selected[id].qty + delta);
    }
    renderDisambiguation();
  }

  function updateConfirmEnabled() {
    const confirmBtn = document.getElementById('confirm-resolved');
    if (!confirmBtn) return;
    const pending = state.pending.filter((g) => !g.resolved);
    const resolvable = pending.filter((g) => (g.matches || []).length > 0);
    const allResolvablePicked = resolvable.every(
      (g) => g.selected && Object.keys(g.selected).length > 0
    );
    confirmBtn.disabled = !(resolvable.length && allResolvablePicked);
  }

  function confirmResolved() {
    state.pending.forEach((group) => {
      if (group.resolved) return;
      if (!group.selected || !Object.keys(group.selected).length) return;
      if (!(group.matches || []).length) return;
      Object.entries(group.selected).forEach(([idStr, meta]) => {
        const id = Number(idStr);
        const match = group.matches.find((m) => m.id === id);
        if (match) addToCart(match, meta.qty || group.qty || 1);
      });
      group.resolved = true;
    });
    renderDisambiguation();
  }

  async function parseOrder(text) {
    const body = { text };
    if (state.preferredModels.length) {
      body.preferred_models = state.preferredModels.slice();
    }
    const res = await fetch('/api/parse-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    const banner = document.getElementById('mode-banner');
    if (banner && data.mode) {
      banner.className =
        'max-w-7xl mx-auto px-4 mt-3 text-sm border rounded-md px-3 py-2 ' + data.mode;
      const labels = {
        groq: 'AI mode: Groq',
        gemini: 'AI mode: Gemini',
        fuzzy: 'AI unavailable — using manual search mode',
      };
      banner.textContent = (labels[data.mode] || data.mode) + ' (last parse)';
    }

    // Replace previous unresolved list so re-parse / accidental Space on Parse won't duplicate panels
    state.pending = [];
    state.focus = { groupIndex: 0, matchIndex: 0 };

    (data.items || []).forEach((group) => {
      group.selected = {};
      group.resolved = false;
      group.matches = sortMatchesByPreference(group.matches || []);
      // Only auto-filter when the spoken order named a model — never hard-filter by preference
      group.modelFilter = group.model || '';
      if (!needsDisambiguation(group) && group.matches && group.matches.length === 1) {
        addToCart(group.matches[0], group.qty || 1);
        group.resolved = true;
      } else {
        state.pending.push(group);
      }
    });
    const firstPending = state.pending.find((g) => !g.resolved);
    if (firstPending) {
      state.focus.groupIndex = state.pending.indexOf(firstPending);
      state.focus.matchIndex = 0;
    }
    renderDisambiguation();
  }

  window.parseOrder = parseOrder;

  const parseBtn = document.getElementById('parse-btn');
  if (parseBtn) {
    parseBtn.addEventListener('click', () => {
      const text = (document.getElementById('transcript').value || '').trim();
      if (text) {
        parseBtn.blur();
        parseOrder(text);
      }
    });
  }

  const confirmBtn = document.getElementById('confirm-resolved');
  if (confirmBtn) confirmBtn.addEventListener('click', confirmResolved);

  const clearBtn = document.getElementById('clear-cart');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      state.cart = [];
      clearPreferredModels();
      renderCart();
    });
  }

  // Global keyboard for disambiguation (skip when typing in text fields)
  document.addEventListener(
    'keydown',
    (e) => {
      const panel = document.getElementById('disambiguation');
      if (!panel || panel.classList.contains('hidden')) return;

      const el = e.target;
      const tag = (el && el.tagName) || '';
      const isTextField =
        tag === 'TEXTAREA' ||
        (tag === 'INPUT' &&
          el.type !== 'checkbox' &&
          el.type !== 'button' &&
          el.type !== 'submit');

      // Allow normal typing in filter / qty / transcript
      if (isTextField) return;

      const isSpace = e.code === 'Space' || e.key === ' ' || e.key === 'Spacebar';

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        moveFocus(1);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        moveFocus(-1);
      } else if (isSpace) {
        // Always handle Space ourselves while resolving — otherwise focused
        // buttons (Parse / model chips) get activated and re-parse / duplicate UI
        e.preventDefault();
        e.stopPropagation();
        if (tag === 'INPUT' && el.type === 'checkbox') {
          // Sync from focused card instead of fighting the checkbox default
          const card = el.closest('.match-card[data-nav]');
          if (card) {
            state.focus.groupIndex = Number(card.getAttribute('data-group'));
            state.focus.matchIndex = Number(card.getAttribute('data-match-idx'));
          }
        }
        toggleFocusedSelection();
      } else if (e.key === 'Enter') {
        // Don't let Enter click Parse / random buttons; only confirm selection
        if (tag === 'TEXTAREA') return;
        e.preventDefault();
        e.stopPropagation();
        const btn = document.getElementById('confirm-resolved');
        if (btn && !btn.disabled) confirmResolved();
      }
    },
    true // capture so we beat button default Space/Enter behavior
  );

  async function manualSearch() {
    const q = (document.getElementById('manual-search').value || '').trim();
    const box = document.getElementById('manual-results');
    if (!q || !box) return;
    const params = new URLSearchParams({ q });
    if (state.preferredModels.length) {
      params.set('models', state.preferredModels.join(','));
    }
    const res = await fetch('/api/search?' + params.toString());
    const data = await res.json();
    const items = data.items || [];
    box.innerHTML = items
      .map((m, i) => {
        const ctn = ctnLabel(m.ctn_qty);
        const lockedHit = isPreferredModel(m.model);
        return `
      <div class="flex items-center justify-between gap-2 border rounded-lg px-2 py-1.5 bg-white ${lockedHit ? 'border-teal-300' : ''}">
        <div>
          <div class="font-medium">${m.name}${lockedHit ? ' <span class="text-xs text-teal-700">(preferred)</span>' : ''}</div>
          <div class="text-xs text-slate-500">${m.item_code || ''} · ${m.model || '—'} · ${money(m.cp)} PKR${ctn ? ' · ctn ' + ctn : ''}</div>
        </div>
        <div class="flex gap-1">
          <button type="button" data-add-idx="${i}" class="text-xs px-2 py-1 rounded bg-accent text-white">Add</button>
          ${ctn ? `<button type="button" data-add-ctn-idx="${i}" class="text-xs px-2 py-1 rounded border bg-white">+${ctn} ctn</button>` : ''}
        </div>
      </div>`;
      })
      .join('') || '<p class="text-slate-500">No results</p>';

    box.querySelectorAll('[data-add-idx]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item = items[Number(btn.getAttribute('data-add-idx'))];
        if (item) addToCart(item, 1);
      });
    });
    box.querySelectorAll('[data-add-ctn-idx]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item = items[Number(btn.getAttribute('data-add-ctn-idx'))];
        const ctn = ctnLabel(item && item.ctn_qty);
        if (item && ctn) addToCart(item, ctn);
      });
    });
  }

  const manualBtn = document.getElementById('manual-search-btn');
  if (manualBtn) manualBtn.addEventListener('click', manualSearch);
  const manualInput = document.getElementById('manual-search');
  if (manualInput) {
    manualInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') manualSearch();
    });
  }

  const clearLockBtn = document.getElementById('model-lock-clear');
  if (clearLockBtn) clearLockBtn.addEventListener('click', clearPreferredModels);

  renderModelLock();
  renderCart();
})();
