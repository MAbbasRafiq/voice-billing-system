/**
 * Cart logic and mandatory disambiguation UI.
 */
(function () {
  const state = {
    cart: [], // {item_id, item_code, model, name, cp, foc_qty, foc_units, qty}
    pending: [], // parsed groups awaiting resolution
  };

  window.__billingCart = state;

  function money(n) {
    return Number(n || 0).toFixed(2);
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
          return `
          <div class="border border-slate-200 rounded-lg p-2 bg-white/80">
            <div class="flex justify-between gap-2">
              <div>
                <div class="font-medium">${it.name}</div>
                <div class="text-xs text-slate-500 font-mono">${it.item_code || ''} · ${it.model || '—'}</div>
                ${focNote}
              </div>
              <button data-remove="${idx}" class="text-slate-400 hover:text-red-600 text-xs">Remove</button>
            </div>
            <div class="mt-2 flex items-center justify-between gap-2">
              <label class="text-xs">Qty
                <input data-qty="${idx}" type="number" min="1" value="${it.qty}"
                  class="ml-1 w-16 border rounded px-1 py-0.5" />
              </label>
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
  }

  function addToCart(item, qty) {
    const existing = state.cart.find((c) => c.item_id === item.id || c.item_id === item.item_id);
    const id = item.id ?? item.item_id;
    if (existing) {
      existing.qty += qty;
    } else {
      state.cart.push({
        item_id: id,
        item_code: item.item_code,
        model: item.model,
        name: item.name,
        cp: item.cp,
        foc_qty: item.foc_qty,
        foc_units: item.foc_units,
        qty,
      });
    }
    renderCart();
  }

  function needsDisambiguation(group) {
    if (!group.matches || group.matches.length === 0) return true;
    if (group.matches.length > 1) return true;
    if (group.confidence === 'ambiguous') return true;
    return false;
  }

  function renderDisambiguation() {
    const panel = document.getElementById('disambiguation');
    const list = document.getElementById('disambiguation-list');
    const confirmBtn = document.getElementById('confirm-resolved');
    if (!panel || !list) return;

    const pending = state.pending.filter((g) => !g.resolved);
    if (!pending.length) {
      panel.classList.add('hidden');
      return;
    }
    panel.classList.remove('hidden');

    list.innerHTML = pending
      .map((group, gi) => {
        const realIndex = state.pending.indexOf(group);
        const matches = group.matches || [];
        const cards = matches.length
          ? matches
              .map((m) => {
                const key = `${realIndex}:${m.id}`;
                const selected = group.selected && group.selected[m.id];
                return `
              <label class="match-card block border rounded-lg p-2 cursor-pointer ${selected ? 'selected' : ''}">
                <div class="flex items-start gap-2">
                  <input type="checkbox" data-group="${realIndex}" data-id="${m.id}"
                    ${selected ? 'checked' : ''} class="mt-1" />
                  <div class="flex-1 text-sm">
                    <div class="font-mono text-xs text-slate-500">${m.item_code || ''}</div>
                    <div class="font-medium">${m.model || '—'} · ${m.name}</div>
                    <div class="text-xs text-slate-600">CP ${money(m.cp)} PKR · ${focPreview(m)}</div>
                    <div class="mt-1 ${selected ? '' : 'hidden'}" data-qty-wrap="${key}">
                      Qty <input type="number" min="1" value="${selected ? selected.qty : group.qty || 1}"
                        data-qty-for="${realIndex}" data-qty-id="${m.id}"
                        class="w-16 border rounded px-1 py-0.5" />
                    </div>
                  </div>
                </div>
              </label>`;
              })
              .join('')
          : `<p class="text-sm text-amber-700">No catalog matches. Search manually below.</p>`;

        return `
        <div class="border border-amber-200 bg-amber-50/50 rounded-xl p-3">
          <div class="text-sm mb-2">
            <span class="font-medium">“${group.spoken || group.item}”</span>
            <span class="text-slate-500"> · qty ${group.qty || 1}
            ${group.model ? ' · said model ' + group.model : ''}
            · ${group.confidence || 'ambiguous'}</span>
          </div>
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
        renderDisambiguation();
        updateConfirmEnabled();
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
    });

    updateConfirmEnabled();
  }

  function updateConfirmEnabled() {
    const confirmBtn = document.getElementById('confirm-resolved');
    if (!confirmBtn) return;
    const pending = state.pending.filter((g) => !g.resolved);
    const anySelected = pending.some((g) => g.selected && Object.keys(g.selected).length);
    // Allow confirm if every pending group with matches has ≥1 selection,
    // OR at least one selection exists (groups with zero matches stay until manual add)
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
    const res = await fetch('/api/parse-order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    const data = await res.json();
    if (window.refreshModeBanner) {
      // reflect mode from response quickly
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
    }

    (data.items || []).forEach((group) => {
      group.selected = {};
      group.resolved = false;
      if (!needsDisambiguation(group) && group.matches && group.matches.length === 1) {
        // Still show panel rule: NEVER auto-select when multiple;
        // single exact match can go to cart directly per usability,
        // BUT brief says if ANY ambiguous OR multiple matches show panel.
        // Single exact → add to cart.
        addToCart(group.matches[0], group.qty || 1);
        group.resolved = true;
      } else {
        // Pre-check nothing — admin must choose. If exactly one match but ambiguous confidence, still show.
        state.pending.push(group);
      }
    });
    renderDisambiguation();
  }

  window.parseOrder = parseOrder;

  const parseBtn = document.getElementById('parse-btn');
  if (parseBtn) {
    parseBtn.addEventListener('click', () => {
      const text = (document.getElementById('transcript').value || '').trim();
      if (text) parseOrder(text);
    });
  }

  const confirmBtn = document.getElementById('confirm-resolved');
  if (confirmBtn) confirmBtn.addEventListener('click', confirmResolved);

  const clearBtn = document.getElementById('clear-cart');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      state.cart = [];
      renderCart();
    });
  }

  async function manualSearch() {
    const q = (document.getElementById('manual-search').value || '').trim();
    const box = document.getElementById('manual-results');
    if (!q || !box) return;
    const res = await fetch('/api/search?q=' + encodeURIComponent(q));
    const data = await res.json();
    const items = data.items || [];
    box.innerHTML = items
      .map(
        (m, i) => `
      <div class="flex items-center justify-between gap-2 border rounded-lg px-2 py-1.5 bg-white">
        <div>
          <div class="font-medium">${m.name}</div>
          <div class="text-xs text-slate-500">${m.item_code || ''} · ${m.model || '—'} · ${money(m.cp)} PKR</div>
        </div>
        <button type="button" data-add-idx="${i}"
          class="text-xs px-2 py-1 rounded bg-accent text-white">Add</button>
      </div>`
      )
      .join('') || '<p class="text-slate-500">No results</p>';

    box.querySelectorAll('[data-add-idx]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const item = items[Number(btn.getAttribute('data-add-idx'))];
        if (item) addToCart(item, 1);
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

  renderCart();
})();
