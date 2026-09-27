(() => {
  const arrangement = document.getElementById('preview-arrangement');
  const scenario = document.getElementById('preview-scenario');
  const error = document.getElementById('preview-error');
  if (!arrangement) return;
  arrangement.value = sessionStorage.getItem('desktop-arrangement') === 'current' ? 'current' : 'compact';
  error.checked = sessionStorage.getItem('desktop-error') === 'true';
  document.body.dataset.arrangement = arrangement.value;
  const originalFetch = window.fetch.bind(window);
  window.fetch = (url, options = {}) => {
    const target = new URL(typeof url === 'string' ? url : url.url, location.href);
    if (target.origin === location.origin && target.pathname.startsWith('/attendance-checks/') && options.method === 'POST' && error.checked) {
      const headers = new Headers(options.headers);
      headers.set('X-Preview-Save-Error', '1');
      error.checked = false;
      sessionStorage.setItem('desktop-error', 'false');
      return originalFetch(url, {...options, headers});
    }
    return originalFetch(url, options);
  };
  function updateNote() {
    document.getElementById('preview-layout-note').textContent = arrangement.value === 'current' ? '現在の本番と同じ横幅' : '1列のまま、名前と確認ボタンを近づける案';
  }
  arrangement.addEventListener('change', () => {
    document.body.dataset.arrangement = arrangement.value;
    sessionStorage.setItem('desktop-arrangement', arrangement.value);
    updateNote();
  });
  error.addEventListener('change', () => sessionStorage.setItem('desktop-error', String(error.checked)));
  scenario.addEventListener('change', async () => {
    scenario.disabled = true;
    try {
      const response = await originalFetch('/__preview__/scenario?value=' + encodeURIComponent(scenario.value), {method:'POST',headers:{'X-CSRF-Token':document.querySelector('meta[name=csrf-token]')?.content || ''}});
      if (!response.ok) throw new Error('入力状態を変更できませんでした。');
      location.reload();
    } catch (e) { document.getElementById('preview-layout-note').textContent = e.message; scenario.disabled = false; }
  });
  updateNote();
})();
