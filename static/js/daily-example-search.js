/* Refresh only the candidates, keeping an unsaved daily draft in the page. */
(() => {
  const panel = document.querySelector('.daily-example-panel');
  const draft = document.getElementById('daily-draft');
  const feedback = document.getElementById('daily-example-feedback');
  if (!panel || !draft || !feedback) return;
  const field = (name, root = draft) => root.querySelector(`[name="${name}"]`);
  let busy = false;

  function notify(message, error = false) {
    feedback.textContent = message;
    feedback.setAttribute('role', error ? 'alert' : 'status');
    feedback.hidden = false;
  }

  function searchValues(searchForm) {
    return [['age_class', 'search_age_class'], ['month', 'search_month'], ['q', 'search_query']]
      .map(([searchName, draftName]) => [draftName, field(searchName, searchForm).value]);
  }

  async function load(url, copying) {
    if (busy) return;
    busy = true;
    feedback.hidden = true;
    panel.setAttribute('aria-busy', 'true');
    const button = panel.querySelector('button[type="submit"]');
    button.disabled = true;
    // The form below may have newer date/class values than the rendered link.
    for (const name of ['target_date', 'classroom_ref']) url.searchParams.set(name, field(name).value);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal});
      if (!response.ok || new URL(response.url).pathname !== '/plans/daily-plans/new') throw new Error('Invalid response');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const nextPanel = page.querySelector('.daily-example-panel');
      const nextDraft = page.getElementById('daily-draft');
      if (!nextPanel || !nextDraft) throw new Error('Missing form');
      const conditions = searchValues(nextPanel.querySelector('form'));
      if (copying) {
        if (field('example_id', nextDraft)?.value !== url.searchParams.get('example_id')) throw new Error('Missing example');
        const names = ['age_class', 'daily_aims', 'daily_content', 'example_id', 'example_source_ref'];
        const values = names.map(name => [name, field(name, nextDraft).value]);
        const rows = [...nextDraft.querySelectorAll('#daily-timeline-rows > tr')].map(row => document.importNode(row, true));
        if (!rows.length) throw new Error('Missing rows');
        values.forEach(([name, value]) => { field(name).value = value; });
        document.getElementById('daily-timeline-rows').replaceChildren(...rows);
        // Keep the conditions used for these results, even if the inputs were edited later.
        notify('候補を下書きへコピーしました。内容を確認・編集してから保存してください。');
        draft.scrollIntoView({block: 'start'});
        field('daily_aims').focus({preventScroll: true});
      } else {
        panel.replaceChildren(...[...nextPanel.childNodes].map(node => document.importNode(node, true)));
      }
      conditions.forEach(([name, value]) => { field(name).value = value; });
      history.replaceState(null, '', url.pathname + url.search + (copying ? '#daily-draft' : ''));
    } catch (_) {
      notify(copying ? '候補をコピーできませんでした。下書きはそのままです。時間をおいてもう一度お試しください。'
        : '候補を検索できませんでした。下書きはそのままです。時間をおいてもう一度お試しください。', true);
      feedback.scrollIntoView({block: 'center'});
    } finally {
      clearTimeout(timer);
      busy = false;
      panel.removeAttribute('aria-busy');
      panel.querySelector('button[type="submit"]').disabled = false;
    }
  }

  panel.addEventListener('submit', event => {
    const form = event.target.closest('form');
    if (!form) return;
    event.preventDefault();
    const url = new URL(form.action, location.href);
    url.search = new URLSearchParams(new FormData(form)).toString();
    load(url, false);
  });
  panel.addEventListener('click', event => {
    const link = event.target.closest('.daily-example-copy');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    load(new URL(link.href), true);
  });
})();
