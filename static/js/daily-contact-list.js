(() => {
  const root = document.querySelector('[data-contact-list]');
  if (!root) return;
  const scroller = root.querySelector('.contact-table-scroll');
  const wideButton = document.getElementById('contact-wide');
  const sidebar = document.getElementById('staff-sidebar');
  const layout = sidebar?.parentElement;
  const key = `daily-contact-list:${location.pathname}?${new URLSearchParams({
    date: root.querySelector('[name=date]').value,
    classroom: root.querySelector('[name=classroom_id]').value,
    sort: root.querySelector('[name=sort]').value,
    view: root.dataset.view,
  })}`;
  let saved = null;
  try {
    const stored = JSON.parse(sessionStorage.getItem(key));
    // A single short-lived position, never contact text or names.
    if (stored && Date.now() - stored.at < 30 * 60 * 1000) saved = stored;
    sessionStorage.removeItem(key);
  } catch (_) { /* The list also works without browser storage. */ }
  const setWide = wide => {
    layout?.classList.toggle('contact-list-wide', wide);
    wideButton.setAttribute('aria-pressed', String(wide));
    wideButton.textContent = wide ? 'メニューを表示' : '一覧を広く表示';
  };
  if (layout) {
    wideButton.hidden = false;
    setWide(Boolean(saved?.wide));
    wideButton.addEventListener('click', () => setWide(wideButton.getAttribute('aria-pressed') !== 'true'));
  }
  const restore = () => {
    if (!saved) return;
    if (scroller) {
      scroller.scrollLeft = Number(saved.x) || 0;
      scroller.scrollTop = Number(saved.y) || 0;
    }
    window.scrollTo(0, Number(saved.pageY) || 0);
    saved = null;
  };
  if (document.readyState === 'complete') restore();
  else window.addEventListener('load', restore, {once: true});
  root.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || !/^\/daily-contacts\/\d+\?/.test(link.getAttribute('href') || '')) return;
    try {
      sessionStorage.setItem(key, JSON.stringify({at: Date.now(), x: scroller?.scrollLeft || 0,
        y: scroller?.scrollTop || 0, pageY: window.scrollY,
        wide: wideButton.getAttribute('aria-pressed') === 'true'}));
    } catch (_) { /* Navigation must not depend on storage availability. */ }
  });
})();
