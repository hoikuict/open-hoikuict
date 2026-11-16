(() => {
  const form = document.getElementById('document-search');
  if (!form) {
    const back = document.getElementById('back-to-list');
    if (back && document.referrer && history.length > 1 &&
        new URL(document.referrer).origin === location.origin &&
        new URL(document.referrer).pathname === back.pathname) {
      back.addEventListener('click', event => {
        if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        history.back();
      });
    }
    return;
  }

  const filters = ['kind', 'room', 'status', 'format'];
  const results = document.getElementById('document-results');
  const count = document.getElementById('search-count');
  const empty = document.getElementById('no-matches');
  const error = document.getElementById('search-error');
  const normalize = value => value.normalize('NFKC').toLowerCase();
  const rows = Array.from(results.querySelectorAll('.document-row'), element => ({
    element,
    fields: ['title', 'child', 'owner'].map(key => normalize(element.dataset[key]).replace(/\s+/gu, ''))
  }));

  function search() {
    const values = Object.fromEntries(new FormData(form));
    try {
      const words = normalize(values.q).trim().split(/\s+/u).filter(Boolean);
      let matches = 0;
      for (const {element, fields} of rows) {
        const show = filters.every(key => !values[key] || values[key] === element.dataset[key])
          && words.every(word => fields.some(field => field.includes(word)));
        element.hidden = !show;
        if (show) matches++;
      }
      empty.hidden = !rows.length || matches > 0;
      results.hidden = !empty.hidden;
      error.hidden = true;
      count.textContent = words.length || filters.some(key => values[key])
        ? `全${rows.length}件中 ${matches}件を表示` : `全${rows.length}件`;
    } catch {
      results.hidden = true;
      empty.hidden = true;
      count.textContent = '';
      error.hidden = false;
      return;
    }
    // Browsers may restrict history writes. Filtering still works in that case.
    try {
      history.replaceState({...history.state, documentSearch: {staff: form.dataset.staff, values}}, '');
    } catch { /* This browser can still display the current results. */ }
  }

  function fill(values) {
    for (const key of ['q', ...filters]) {
      const field = form.elements.namedItem(key);
      field.value = values[key] || '';
      if (field.selectedIndex === -1) field.selectedIndex = 0;
    }
  }

  function restore() {
    const saved = history.state?.documentSearch;
    fill(saved?.staff === form.dataset.staff ? saved.values : {});
    search();
  }

  function clear() {
    fill({});
    search();
    form.elements.q.focus();
  }
  form.addEventListener('submit', event => { event.preventDefault(); search(); });
  form.addEventListener('reset', event => { event.preventDefault(); clear(); });
  document.getElementById('show-all').addEventListener('click', clear);
  document.getElementById('retry-search').addEventListener('click', search);
  window.addEventListener('pageshow', restore);
  restore();
  form.hidden = false;
})();
