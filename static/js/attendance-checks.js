let pendingVerification = null;
let verificationSaving = false;
document.addEventListener('htmx:afterSwap', () => {
  const day = document.getElementById('attendance-checks-board')?.dataset.targetDate;
  const link = document.querySelector('[data-roster-link]');
  if (day && link) link.href = `/attendance-checks/roster?date=${encodeURIComponent(day)}`;
});
function openVerificationDialog(button) {
  if (verificationSaving || button.getAttribute('aria-pressed') === 'true') return;
  if (button.dataset.requiresReason !== 'true') {
    saveVerification(button.form, '', false, false);
    return;
  }
  pendingVerification = button.form;
  const dialog = document.getElementById('verification-dialog');
  document.getElementById('verification-confirm').reset();
  document.getElementById('verification-title').textContent = `${button.dataset.childName}：${button.textContent.trim()}`;
  const reason = document.getElementById('verification-reason');
  reason.required = true;
  document.getElementById('verification-required').textContent = '（必須）';
  document.getElementById('verification-notify-label').hidden = button.dataset.statusKey !== 'unknown';
  document.getElementById('verification-error').textContent = '';
  dialog.showModal();
  reason.focus();
}
async function saveVerification(form, reason, notify, fromDialog) {
  if (verificationSaving) return;
  verificationSaving = true;
  const errorBox = document.getElementById(fromDialog ? 'verification-error' : 'verification-inline-error');
  errorBox.textContent = '';
  const controls = document.querySelectorAll('[data-verification-form] button, #verification-confirm button, .compact-toolbar button');
  controls.forEach(button => { button.disabled = true; });
  const data = new FormData(form);
  data.set('reason', reason);
  data.set('notify_parent', String(notify));
  try {
    const response = await fetch(form.action, {method: 'POST', body: data, headers: {
      'HX-Request': 'true', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
    }});
    if (!response.ok || response.redirected) {
      let message = '保存できませんでした。入力は残っています。ログイン状態を確認して、もう一度お試しください。';
      if (response.headers.get('content-type')?.includes('application/json')) message = (await response.json()).detail || message;
      throw new Error(message);
    }
    const html = await response.text();
    const parsed = new DOMParser().parseFromString(html, 'text/html');
    const board = parsed.getElementById('attendance-checks-board');
    if (!board) throw new Error('保存結果を確認できませんでした。画面を再読み込みしてください。');
    const scroll = window.scrollY;
    document.getElementById('attendance-checks-board').replaceWith(board);
    window.htmx?.process(board);
    document.getElementById('verification-dialog').close();
    pendingVerification = null;
    window.scrollTo(0, scroll);
  } catch (error) { errorBox.textContent = error.message; }
  finally {
    verificationSaving = false;
    controls.forEach(button => { button.disabled = false; });
  }
}
document.getElementById('verification-confirm')?.addEventListener('submit', event => {
  event.preventDefault();
  if (!pendingVerification) return;
  saveVerification(pendingVerification, document.getElementById('verification-reason').value.trim(), document.getElementById('verification-notify').checked, true);
});
document.querySelectorAll('[data-reason-preset]').forEach(button => button.addEventListener('click', () => {
  const reason = document.getElementById('verification-reason');
  reason.value = button.dataset.reasonPreset;
  reason.focus();
}));
document.getElementById('verification-dialog')?.addEventListener('cancel', event => {
  if (verificationSaving) event.preventDefault();
});
