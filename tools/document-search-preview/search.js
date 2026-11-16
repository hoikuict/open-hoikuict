(() => {
  const listPath = '/plans/documents/';
  const form = document.getElementById('document-search');
  if (!form) {
    const back = document.getElementById('back-to-list');
    if (back && document.referrer && history.length > 1) {
      const previous = new URL(document.referrer);
      if (previous.origin === location.origin && previous.pathname === listPath) {
        back.addEventListener('click', event => {
          if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          history.back();
        });
      }
    }
    return;
  }

  const keys = ['q','kind','room','status','format'];
  const filters = keys.slice(1);
  const normalize = text => text.normalize('NFKC').toLowerCase();
  const rows = Array.from(document.querySelectorAll('#document-results .document-row'), element => ({
    element,
    fields: ['title','child','owner'].map(key => normalize(element.dataset[key] || '').replace(/\s+/gu,''))
  }));
  const results = document.getElementById('document-results');
  const count = document.getElementById('search-count');
  const none = document.getElementById('no-matches');
  const error = document.getElementById('search-error');
  const scenes = document.getElementById('search-scene');
  function fill(values) {
    for (const key of keys) {
      form.elements[key].value = values[key] || '';
      if (form.elements[key].selectedIndex === -1) form.elements[key].selectedIndex = 0;
    }
  }
  function apply() {
    const values = Object.fromEntries(new FormData(form));
    const words = normalize(values.q.trim()).split(/\s+/u).filter(Boolean);
    let found = 0;
    for (const row of rows) {
      const matches = filters.every(key => !values[key] || row.element.dataset[key] === values[key])
        && words.every(word => row.fields.some(field => field.includes(word)));
      row.element.hidden = !matches;
      if (matches) found++;
    }
    error.hidden = true;
    results.hidden = rows.length > 0 && found === 0;
    none.hidden = rows.length === 0 || found !== 0;
    count.textContent = words.length || filters.some(key => values[key])
      ? '全' + rows.length + '件中 ' + found + '件を表示' : '全' + rows.length + '件';
    history.replaceState({...history.state, documentSearch: values}, '');
  }
  function clear() {
    fill({});
    scenes.value = '';
    apply();
    form.elements.q.focus();
  }
  form.hidden = false;
  function restore() {
    fill(history.state?.documentSearch || {});
    apply();
  }
  window.addEventListener('pageshow', restore);
  restore();
  form.addEventListener('submit', event => { event.preventDefault(); scenes.value = ''; apply(); });
  form.addEventListener('reset', event => { event.preventDefault(); clear(); });
  document.getElementById('show-all').addEventListener('click', clear);
  document.getElementById('retry-search').addEventListener('click', () => {
    scenes.value = '';
    apply();
    form.elements.q.focus();
  });
  const samples = {
    empty: {}, partial: { q:'あおい' },
    filled: { room:'さくら組', kind:'児童票・発達経過記録', status:'下書き' },
    none: { q:'該当しない名前' }
  };
  scenes.addEventListener('change', () => {
    if (scenes.value === 'error') {
      none.hidden = true;
      results.hidden = true;
      error.hidden = false;
      count.textContent = '';
    } else if (samples[scenes.value]) {
      fill(samples[scenes.value]);
      apply();
    }
  });
})();
