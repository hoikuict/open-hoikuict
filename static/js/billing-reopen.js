(() => {
  'use strict';
  const dialog = document.getElementById('billing-reopen-dialog');
  const form = document.getElementById('billing-reopen-form');
  const dirty = new Set();
  document.querySelectorAll('form[data-billing-edit]').forEach(edit => {
    edit.addEventListener('input', () => dirty.add(edit));
    edit.addEventListener('change', () => dirty.add(edit));
  });
  const allowLeave = () => !dirty.size || window.confirm('まだ保存していない入力があります。入力を破棄して移動しますか？');
  function open(data) {
    if (!dialog || !/^\d+$/.test(String(data.id))) return;
    form.action = `/billing/zengin/exports/${data.id}/cancel-ui`;
    document.getElementById('billing-reopen-summary').textContent =
      `${data.month} ／ 出力 #${data.id} ／ ${data.count}件 ／ ${Number(data.amount).toLocaleString('ja-JP')}円`;
    form.elements.reason.value = data.reason || '';
    form.elements.confirmed_unsubmitted.checked = Boolean(data.checked);
    const error = document.getElementById('billing-reopen-error');
    error.textContent = data.error || ''; error.hidden = !data.error;
    form.querySelector('button[type=submit]').disabled = false;
    dialog.showModal();
  }
  document.querySelectorAll('[data-reopen-export]').forEach(button => button.addEventListener('click', () => open({
    id: button.dataset.reopenExport, month: button.dataset.reopenMonth,
    count: button.dataset.reopenCount, amount: button.dataset.reopenAmount,
  })));
  document.querySelector('[data-reopen-close]')?.addEventListener('click', () => dialog.close());
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link.target === '_blank' || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const target = new URL(link.href, location.href);
    if (target.pathname === location.pathname && target.search === location.search && target.hash) return;
    if (!allowLeave()) event.preventDefault(); else dirty.clear();
  });
  document.addEventListener('submit', event => {
    const otherEdits = [...dirty].some(edit => edit !== event.target);
    if (otherEdits && !window.confirm('ほかの欄に保存していない入力があります。破棄してこの操作を続けますか？')) {
      event.preventDefault(); return;
    }
    if (event.target === form) {
      const reason = form.elements.reason;
      if (!reason.value.trim()) { event.preventDefault(); reason.setCustomValidity('取消理由を入力してください。'); reason.reportValidity(); return; }
      form.querySelector('button[type=submit]').disabled = true;
    }
    dirty.clear();
  });
  form?.elements.reason.addEventListener('input', () => form.elements.reason.setCustomValidity(''));
  window.addEventListener('beforeunload', event => { if (dirty.size) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('pageshow', () => { const submit = form?.querySelector('button[type=submit]'); if (submit) submit.disabled = false; });
  const initial = document.getElementById('billing-reopen-initial');
  if (initial) { const data = JSON.parse(initial.textContent); if (data) open(data); }
})();
