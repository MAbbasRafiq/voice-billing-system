/**
 * Catalog name display: EN | اردو | Both.
 * Input/parse stay English; this only controls how names are shown for verify.
 */
(function (global) {
  const STORAGE_KEY = 'catalog_display_lang';
  const MODES = ['en', 'ur', 'both'];
  const DEFAULT_MODE = 'both';

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function cleanUrdu(urdu) {
    const u = String(urdu == null ? '' : urdu).trim();
    if (!u || u === '-' || u === '—') return '';
    return u;
  }

  function getCatalogDisplayMode() {
    try {
      const v = (localStorage.getItem(STORAGE_KEY) || '').trim().toLowerCase();
      if (MODES.includes(v)) return v;
    } catch (_) {}
    return DEFAULT_MODE;
  }

  function setCatalogDisplayMode(mode) {
    const m = MODES.includes(mode) ? mode : DEFAULT_MODE;
    try {
      localStorage.setItem(STORAGE_KEY, m);
    } catch (_) {}
    global.dispatchEvent(
      new CustomEvent('catalog-display-lang', { detail: { mode: m } })
    );
    return m;
  }

  /** Qty field label: Urdu when display mode is ur (or both). */
  function qtyLabel() {
    return uiText('qty');
  }

  const UI_STRINGS = {
    parse_text: { en: 'Parse Text', ur: 'متن پارس کریں' },
    new_bill: { en: 'New bill', ur: 'نیا بل' },
    add_from_catalog: { en: 'Add from catalog', ur: 'کیٹلاگ سے شامل کریں' },
    start_listening: { en: 'Start Listening', ur: 'سننا شروع کریں' },
    stop_listening: { en: 'Stop Listening', ur: 'سننا بند کریں' },
    confirm_selected: { en: 'Confirm selected', ur: 'منتخب تصدیق کریں' },
    search: { en: 'Search', ur: 'تلاش' },
    cart: { en: 'Cart', ur: 'کارٹ' },
    cart_empty: { en: 'Cart is empty', ur: 'کارٹ خالی ہے' },
    qty: { en: 'Qty', ur: 'مقدار' },
    speak_order: { en: 'Speak the order', ur: 'آرڈر بولیں' },
    resolve_ambiguous: { en: 'Resolve ambiguous items', ur: 'ملتے جلتے آئٹمز حل کریں' },
    preview_bill: { en: 'Preview Bill', ur: 'بل دیکھیں' },
    clear: { en: 'Clear', ur: 'صاف کریں' },
    undo: { en: 'Undo', ur: 'واپس' },
    repeat_last: { en: 'Repeat last', ur: 'آخری دہرائیں' },
  };

  function uiText(key) {
    const row = UI_STRINGS[key];
    if (!row) return key;
    const mode = getCatalogDisplayMode();
    if (mode === 'ur') return row.ur;
    if (mode === 'both') return row.en + ' / ' + row.ur;
    return row.en;
  }

  function applyUiI18n(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach((el) => {
      const key = el.getAttribute('data-i18n');
      if (!key || !UI_STRINGS[key]) return;
      // Don't clobber live mic / parse busy states with the idle label.
      if (el.id === 'mic-btn' && el.classList.contains('bg-red-600')) {
        el.textContent = uiText('stop_listening');
        return;
      }
      if (el.id === 'parse-btn' && el.disabled) return;
      const text = uiText(key);
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.hasAttribute('data-i18n-placeholder')) el.placeholder = text;
        else el.value = text;
      } else {
        el.textContent = text;
      }
    });
  }

  /**
   * @param {{name?: string, urdu_name?: string}|string} itemOrName
   * @param {{plain?: boolean, urduClass?: string}} opts
   * @returns {string} HTML (or plain text if opts.plain)
   */
  function formatCatalogName(itemOrName, opts) {
    opts = opts || {};
    let en = '';
    let ur = '';
    if (itemOrName && typeof itemOrName === 'object') {
      en = String(itemOrName.name || '').trim();
      ur = cleanUrdu(itemOrName.urdu_name);
    } else {
      en = String(itemOrName || '').trim();
    }
    const mode = getCatalogDisplayMode();

    if (mode === 'ur') {
      if (opts.plain) return ur || en;
      // Only real Urdu gets large/bold; English fallback stays normal weight.
      if (ur) {
        return (
          '<span class="catalog-name-ur catalog-name-ur-style" dir="auto">' +
          escapeHtml(ur) +
          '</span>'
        );
      }
      return (
        '<span class="catalog-name-en catalog-name-en-fallback">' +
        escapeHtml(en) +
        '</span>'
      );
    }
    if (mode === 'en' || !ur) {
      return opts.plain ? en : escapeHtml(en);
    }
    // both
    if (opts.plain) {
      return en + (ur ? ' / ' + ur : '');
    }
    const urClass = opts.urduClass || 'catalog-name-ur-style';
    return (
      '<span class="catalog-name-en">' +
      escapeHtml(en) +
      '</span>' +
      '<span class="catalog-name-ur ' +
      urClass +
      '" dir="auto">' +
      escapeHtml(ur) +
      '</span>'
    );
  }

  function wireCatalogDisplayToggle(root) {
    const el = typeof root === 'string' ? document.querySelector(root) : root;
    if (!el) return;
    const sync = (mode) => {
      el.querySelectorAll('[data-catalog-lang]').forEach((btn) => {
        const on = btn.getAttribute('data-catalog-lang') === mode;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    };
    sync(getCatalogDisplayMode());
    if (el.dataset.catalogLangWired === '1') return;
    el.dataset.catalogLangWired = '1';
    el.addEventListener('click', (e) => {
      const btn = e.target && e.target.closest
        ? e.target.closest('[data-catalog-lang]')
        : null;
      if (!btn || !el.contains(btn)) return;
      const m = setCatalogDisplayMode(btn.getAttribute('data-catalog-lang'));
      // Sync every toggle on the page (header + settings).
      document.querySelectorAll('.catalog-lang-toggle').forEach((box) => {
        box.querySelectorAll('[data-catalog-lang]').forEach((b) => {
          const on = b.getAttribute('data-catalog-lang') === m;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
      });
    });
  }

  global.getCatalogDisplayMode = getCatalogDisplayMode;
  global.setCatalogDisplayMode = setCatalogDisplayMode;
  global.formatCatalogName = formatCatalogName;
  global.qtyLabel = qtyLabel;
  global.uiText = uiText;
  global.applyUiI18n = applyUiI18n;
  global.wireCatalogDisplayToggle = wireCatalogDisplayToggle;
  global.CATALOG_DISPLAY_MODES = MODES;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => applyUiI18n());
  } else {
    applyUiI18n();
  }
  global.addEventListener('catalog-display-lang', () => applyUiI18n());
})(window);
