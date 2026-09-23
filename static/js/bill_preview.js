/**
 * Bill preview and save/PDF export.
 */
(function () {
  const previewPanel = document.getElementById('bill-preview');
  const previewBody = document.getElementById('preview-body');
  const previewBtn = document.getElementById('preview-bill-btn');
  const saveBtn = document.getElementById('save-bill-btn');
  const closeBtn = document.getElementById('close-preview-btn');

  let lastPreview = null;

  function money(n) {
    return Number(n || 0).toFixed(2);
  }

  function payloadFromCart() {
    const cart = (window.__billingCart && window.__billingCart.cart) || [];
    return {
      customer: (document.getElementById('customer') || {}).value || '',
      lines: cart.map((c) => ({ item_id: c.item_id, qty: c.qty })),
    };
  }

  function renderPreview(data) {
    lastPreview = data;
    const rows = (data.lines || [])
      .map((l) => {
        const cls = l.is_foc ? 'foc-row' : '';
        return `<tr class="${cls}">
          <td class="px-2 py-1 font-mono text-xs">${l.item_code || ''}</td>
          <td class="px-2 py-1">${l.model || ''}</td>
          <td class="px-2 py-1">${l.name || ''}${l.is_foc ? ' <em>FOC (Free)</em>' : ''}</td>
          <td class="px-2 py-1 text-right">${l.qty}</td>
          <td class="px-2 py-1 text-right">${money(l.unit_price)}</td>
          <td class="px-2 py-1 text-right">${money(l.line_total)}</td>
        </tr>`;
      })
      .join('');

    previewBody.innerHTML = `
      <div class="mb-2 text-slate-600">${data.customer ? 'Customer: ' + data.customer : 'No customer name'}</div>
      <table class="min-w-full text-xs">
        <thead class="bg-slate-800 text-white">
          <tr>
            <th class="text-left px-2 py-1">Code</th>
            <th class="text-left px-2 py-1">Model</th>
            <th class="text-left px-2 py-1">Name</th>
            <th class="text-right px-2 py-1">Qty</th>
            <th class="text-right px-2 py-1">Unit</th>
            <th class="text-right px-2 py-1">Total</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
        <tfoot>
          <tr class="font-semibold border-t">
            <td colspan="5" class="px-2 py-2 text-right">Grand Total (PKR)</td>
            <td class="px-2 py-2 text-right">${money(data.total)}</td>
          </tr>
        </tfoot>
      </table>`;
    previewPanel.classList.remove('hidden');
  }

  if (previewBtn) {
    previewBtn.addEventListener('click', async () => {
      const payload = payloadFromCart();
      if (!payload.lines.length) return;
      const res = await fetch('/api/bill/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        alert('Preview failed');
        return;
      }
      renderPreview(await res.json());
    });
  }

  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      previewPanel.classList.add('hidden');
    });
  }

  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      const payload = payloadFromCart();
      if (!payload.lines.length) return;
      const res = await fetch('/api/bill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        alert('Save failed');
        return;
      }
      const data = await res.json();
      // clear cart after save
      if (window.__billingCart) {
        window.__billingCart.cart = [];
        // re-render via custom event-ish: reload page cart section
        const clearBtn = document.getElementById('clear-cart');
        if (clearBtn) clearBtn.click();
      }
      previewPanel.classList.add('hidden');
      window.open(data.pdf_url, '_blank');
      alert('Bill #' + data.id + ' saved. Total: ' + money(data.total) + ' PKR');
    });
  }
})();
