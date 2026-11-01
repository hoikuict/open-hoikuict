(() => {
  const root = document.querySelector('[data-progress-editor]');
  const form = root?.querySelector('[data-progress-body]');
  const panel = root?.querySelector('[data-progress-unsaved]');
  let dirty = root?.dataset.progressHasUnsaved === 'true';
  let submitting = false;
  let destination = '';
  const navigate = (url) => {
    if (!dirty || !form) { window.location.assign(url); return; }
    destination = url;
    panel.hidden = false;
    panel.scrollIntoView({block: 'nearest'});
    panel.querySelector('[data-progress-stay]').focus();
  };
  document.querySelectorAll('[data-progress-period]').forEach((selector) => {
    selector.addEventListener('submit', (event) => {
      event.preventDefault();
      const query = new URLSearchParams(new FormData(selector));
      navigate(`${selector.getAttribute('action')}?${query}`);
    });
    selector.querySelector('[name="target_month"]').addEventListener('change', () => selector.requestSubmit());
  });
  if (!form) return;
  root.querySelector('[data-progress-save-go]').disabled = form.querySelector('button[type="submit"]').disabled;
  const markDirty = () => {
    dirty = true;
    root.querySelector('[data-progress-save-state]').textContent = '未保存の変更があります';
  };
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  form.addEventListener('submit', () => { submitting = true; });
  root.querySelectorAll('[data-progress-navigation]').forEach((link) => {
    link.addEventListener('click', (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault();
      navigate(link.getAttribute('href'));
    });
  });
  root.querySelector('[data-progress-stay]').addEventListener('click', () => {
    panel.hidden = true;
    destination = '';
    root.querySelector('[name="target_month"]').value = form.querySelector('[name="period_end"]').value.slice(0, 7);
  });
  root.querySelector('[data-progress-discard]').addEventListener('click', () => {
    dirty = false;
    window.location.assign(destination);
  });
  root.querySelector('[data-progress-save-go]').addEventListener('click', () => {
    const save = form.querySelector('button[type="submit"]');
    if (save.disabled) return;
    form.querySelector('[name="continue_url"]').value = destination;
    if (!form.reportValidity()) {
      form.querySelector('[name="continue_url"]').value = '';
      return;
    }
    form.requestSubmit(save);
  });
  window.addEventListener('beforeunload', (event) => {
    if (!dirty || submitting) return;
    event.preventDefault();
    event.returnValue = '';
  });
})();
