(() => {
  const form = document.getElementById('daily-reply-form');
  if (!form) return;
  const fields = [...form.elements].filter(e => e.name.startsWith('reply_'));
  const snapshot = () => JSON.stringify(fields.map(e => [e.name, e.value]));
  let saved = snapshot(), pendingUrl = '', busy = false;
  const leave = document.getElementById('reply-leave-dialog');
  const publish = document.getElementById('reply-publish-dialog');
  const error = document.getElementById('reply-save-error');
  const dirty = () => saved !== snapshot();
  const update = () => {
    document.getElementById('reply-edit-state').textContent = dirty() ? '未送信・編集中（変更はまだ保存されていません）' : '';
    document.getElementById('reply-reset').hidden = !dirty();
    form.querySelectorAll('[data-choice-group]').forEach(group => group.querySelectorAll('button').forEach(button => {
      button.setAttribute('aria-pressed', String(form.elements[group.dataset.choiceGroup].value === button.dataset.replyChoice));
    }));
    const [whole = '', fraction = ''] = form.elements.reply_temperature.value.split('.');
    form.querySelectorAll('[data-temperature-whole]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.temperatureWhole === whole)));
    form.querySelectorAll('[data-temperature-fraction]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.temperatureFraction === fraction)));
  };
  form.querySelectorAll('[data-choice-group]').forEach(group => {
    group.hidden = false;
    form.elements[group.dataset.choiceGroup].hidden = true;
    group.addEventListener('click', event => {
      const button = event.target.closest('[data-reply-choice]');
      if (!button) return;
      form.elements[group.dataset.choiceGroup].value = button.dataset.replyChoice;
      update();
    });
  });
  form.querySelector('.reply-temperature').hidden = false;
  form.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const input = form.elements.reply_temperature;
    const [whole = '', fraction = ''] = input.value.split('.');
    if (button.hasAttribute('data-temperature-whole')) input.value = `${button.dataset.temperatureWhole}.${fraction}`;
    if (button.hasAttribute('data-temperature-fraction')) input.value = `${whole}.${button.dataset.temperatureFraction}`;
    if (button.hasAttribute('data-temperature-clear')) input.value = '';
    update();
  });
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  document.getElementById('reply-reset').addEventListener('click', () => {
    for (const [name, value] of JSON.parse(saved)) form.elements[name].value = value;
    error.textContent = '';
    update();
  });
  const save = async (action, dialog = null) => {
    if (busy || !form.reportValidity()) return false;
    const data = new FormData(form);
    data.set('action', action);
    const submitted = snapshot();
    busy = true;
    const buttons = [...form.querySelectorAll('button'), ...document.querySelectorAll('.reply-dialog button')];
    buttons.forEach(button => button.disabled = true);
    error.textContent = '';
    if (dialog) dialog.querySelector('[data-dialog-error]').textContent = '';
    try {
      const response = await fetch(form.getAttribute('action'), {method: 'POST', body: data, headers: {
        'X-Reply-Request': '1', 'X-CSRF-Token': document.querySelector('meta[name="csrf-token"]')?.content || ''
      }});
      if (!response.headers.get('content-type')?.includes('application/json') || response.redirected) throw new Error('保存できませんでした。入力は残っています。ログイン状態を確認してください。');
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || '保存できませんでした。もう一度お試しください。');
      saved = submitted;
      form.elements.revision.value = result.revision;
      const state = document.getElementById('reply-state');
      if (state) state.textContent = result.status;
      update();
      if (!dirty()) document.getElementById('reply-edit-state').textContent = result.notice;
      return true;
    } catch (reason) {
      error.textContent = reason.message;
      if (dialog) dialog.querySelector('[data-dialog-error]').textContent = reason.message;
      return false;
    } finally { busy = false; buttons.forEach(button => button.disabled = false); }
  };
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (event.submitter?.value !== 'publish') { save('draft'); return; }
    const preview = document.getElementById('reply-publish-preview');
    preview.replaceChildren();
    fields.forEach(field => {
      const term = document.createElement('dt'), value = document.createElement('dd');
      term.textContent = form.querySelector(`label[for="${field.id}"]`)?.textContent || field.name;
      value.textContent = field.value || '未入力';
      preview.append(term, value);
    });
    publish.querySelector('[data-dialog-error]').textContent = '';
    publish.showModal();
  });
  publish.querySelector('[data-publish=back]').addEventListener('click', () => publish.close());
  publish.querySelector('[data-publish=confirm]').addEventListener('click', async () => { if (await save('publish', publish)) publish.close(); });
  const navigate = url => {
    if (!dirty()) { window.location.assign(url); return; }
    pendingUrl = url;
    leave.querySelector('[data-dialog-error]').textContent = '';
    leave.showModal();
  };
  document.addEventListener('click', event => {
    const anchor = event.target.closest('a[href]');
    if (!anchor || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0 || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
    if (!dirty() || anchor.getAttribute('href').startsWith('#')) return;
    event.preventDefault();
    navigate(anchor.href);
  });
  document.querySelector('.reply-date-nav form').addEventListener('submit', event => {
    event.preventDefault();
    const target = new URL(window.location.href);
    target.search = new URLSearchParams(new FormData(event.target)).toString();
    navigate(target.href);
  });
  leave.querySelectorAll('[data-leave]').forEach(button => button.addEventListener('click', async () => {
    if (button.dataset.leave === 'stay') { leave.close(); return; }
    if (button.dataset.leave === 'save' && !(await save('draft', leave))) return;
    saved = snapshot();
    window.location.assign(pendingUrl);
  }));
  [leave, publish].forEach(dialog => dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); }));
  window.addEventListener('beforeunload', event => { if (dirty() || busy) { event.preventDefault(); event.returnValue = ''; } });
  update();
})();
