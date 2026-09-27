(() => {
  const form = document.querySelector('[data-record-form]');
  if (!form) return;
  let dirty = false;
  let saving = false;
  let leaving = false;
  let pendingAction = null;
  const dialog = document.getElementById('record-action-dialog');
  const confirmAction = (message, label, action) => {
    document.getElementById('record-action-message').textContent = message;
    dialog.querySelector('[data-record-proceed]').textContent = label;
    pendingAction = action;
    dialog.showModal();
    dialog.querySelector('[data-record-stay]').focus();
  };
  dialog.querySelector('[data-record-stay]').addEventListener('click', () => dialog.close());
  dialog.querySelector('[data-record-proceed]').addEventListener('click', () => {
    const action = pendingAction;
    dialog.close();
    action?.();
  });
  dialog.addEventListener('close', () => { pendingAction = null; });
  const refreshSharing = () => {
    const recipients = form.querySelector('[data-restricted-recipients]');
    if (recipients) recipients.hidden = !(form.elements.visibility.value === 'shared' && form.elements.sensitivity?.value === 'restricted');
  };
  form.addEventListener('input', () => { dirty = true; });
  form.addEventListener('change', () => { dirty = true; refreshSharing(); });
  window.addEventListener('beforeunload', event => {
    if (!leaving && (dirty || saving)) { event.preventDefault(); event.returnValue = ''; }
  });
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || link.target === '_blank' || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    if (saving) { event.preventDefault(); return; }
    if (dirty) {
      event.preventDefault();
      confirmAction('保存していない内容があります。破棄して移動しますか？', '破棄して移動', () => {
        leaving = true;
        location.assign(link.href);
      });
      return;
    }
    leaving = true;
  });
  async function save(target) {
    if (saving) return;
    saving = true;
    const error = document.getElementById('record-form-error');
    error.hidden = true;
    const data = new FormData(target);
    const controls = document.querySelectorAll('form button, form input, form select, form textarea');
    const disabled = [...controls].map(control => control.disabled);
    controls.forEach(control => { control.disabled = true; });
    try {
      const response = await fetch(target.action, {method: 'POST', body: data, headers: {'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''}});
      const url = new URL(response.url);
      if (response.ok && response.redirected && url.pathname === `/children/${target.action.split('/children/')[1].split('/')[0]}/records`) {
        leaving = true;
        location.assign(url.href);
        return;
      }
      let message = '保存できませんでした。入力は残っています。ログイン状態を確認して、もう一度お試しください。';
      if (response.headers.get('content-type')?.includes('application/json')) {
        const result = await response.json();
        if (typeof result.detail === 'string') message = result.detail;
      } else if (response.status === 422) {
        const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
        message = parsed.getElementById('record-form-error')?.textContent.trim() || message;
      }
      throw new Error(message);
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
      error.scrollIntoView({block: 'center'});
    } finally {
      saving = false;
      controls.forEach((control, index) => { control.disabled = disabled[index]; });
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); save(form); });
  document.querySelector('[data-void-form]')?.addEventListener('submit', event => {
    event.preventDefault();
    const target = event.currentTarget;
    confirmAction('この記録を無効化しますか？理由と履歴は残ります。', '無効化する', () => save(target));
  });
  refreshSharing();
})();
