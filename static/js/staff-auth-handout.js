(() => {
  const page = document.getElementById('staff-action-page');
  if (!page) return;
  const printButton = document.getElementById('print-staff-handout');
  const copyButton = document.getElementById('copy-action-code');
  const status = document.getElementById('staff-code-status');
  const unavailableNotice = document.getElementById('staff-code-expired');
  const remaining = Number(page.dataset.remainingMs);
  const started = performance.now();
  const wallStarted = Date.now();
  let leftPage = false;
  let leaving = false;
  function checkExpiry() {
    // Server-derived duration avoids relying on the workstation's clock/timezone.
    // Token validity is independently enforced by the server on submission.
    const elapsed = Math.max(performance.now() - started, Date.now() - wallStarted);
    const unavailable = leftPage || !Number.isFinite(remaining) || elapsed >= remaining;
    printButton.disabled = unavailable;
    copyButton.disabled = unavailable;
    unavailableNotice.hidden = !unavailable;
    return !unavailable;
  }
  printButton.addEventListener('click', () => { if (checkExpiry()) window.print(); });
  window.addEventListener('beforeprint', checkExpiry);
  document.addEventListener('visibilitychange', checkExpiry);
  const timer = window.setInterval(checkExpiry, 1000);
  copyButton.addEventListener('click', async () => {
    if (!checkExpiry()) return;
    try {
      await navigator.clipboard.writeText(document.getElementById('credential-action-code').textContent.trim());
      status.textContent = 'コードをコピーしました。';
    } catch {
      status.textContent = 'コピーできませんでした。表示されたコードを選択してコピーしてください。';
    }
  });
  document.getElementById('staff-code-back').addEventListener('click', event => {
    if (!window.confirm('この画面を離れると同じコードは再表示できません。職員管理へ戻りますか？')) event.preventDefault();
    else leaving = true;
  });
  window.addEventListener('beforeunload', event => {
    if (leaving || leftPage) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('pagehide', () => {
    leftPage = true;
    window.clearInterval(timer);
    document.getElementById('credential-action-code').textContent = '';
    document.getElementById('staff-handout').hidden = true;
    document.getElementById('staff-handout-qr').removeAttribute('src');
  });
  window.addEventListener('pageshow', () => {
    if (leftPage) unavailableNotice.textContent = '画面を離れたため、同じコードは再表示できません。必要なら認証管理から再発行してください。';
    checkExpiry();
  });
  checkExpiry();
})();
