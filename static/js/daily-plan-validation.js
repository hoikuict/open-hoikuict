/* Keep validation beside the daily draft's save button. The server still validates every save. */
(() => {
  'use strict';
  const form = document.getElementById('daily-draft');
  const feedback = document.getElementById('daily-save-feedback');
  const rows = document.getElementById('daily-timeline-rows');
  if (!form || !feedback || !rows) return;

  const targets = {
    target_date: document.getElementById('daily-target-date'),
    age_class: document.getElementById('daily-age-class'),
    timeline: document.getElementById('daily-timeline-input'),
  };
  const timelineNames = new Set(['timeline_time', 'timeline_activity', 'timeline_children',
    'timeline_support', 'timeline_considerations']);
  let attempted = !feedback.hidden;
  let lastErrors = [...feedback.querySelectorAll('[data-error-field]')]
    .map(link => [link.dataset.errorField, link.textContent]);

  function errors() {
    const result = [];
    const date = targets.target_date;
    if (date.validity.badInput || (date.value && !date.validity.valid)) {
      result.push(['target_date', '対象日を正しい形式で選択してください。']);
    } else if (!date.value) {
      result.push(['target_date', '対象日を選択してください。']);
    }
    if (!targets.age_class.value) result.push(['age_class', '年齢を選択してください。']);
    // Match the server: any nonblank cell (including an imported activity name) is enough.
    if (![...rows.querySelectorAll('input, textarea')]
      .some(input => timelineNames.has(input.name) && input.value.trim())) {
      result.push(['timeline', '1日の流れを1行以上入力してください。']);
    }
    return result;
  }

  function render(list) {
    lastErrors = list;
    for (const [key, target] of Object.entries(targets)) {
      const message = list.find(item => item[0] === key)?.[1] || '';
      document.getElementById(`daily-error-${key}`).textContent = message;
      if (message) target.setAttribute('aria-invalid', 'true');
      else target.removeAttribute('aria-invalid');
    }
    feedback.replaceChildren();
    feedback.hidden = false;
    feedback.dataset.kind = list.length ? 'error' : 'status';
    feedback.setAttribute('role', list.length ? 'alert' : 'status');
    const title = document.createElement('strong');
    title.textContent = list.length
      ? `まだ保存できません（確認が必要な項目 ${list.length}件）` : '記入漏れは解消しました。';
    const hint = document.createElement('p');
    hint.textContent = list.length ? '入力内容は残っています。項目名を押すと記入欄へ移動できます。'
      : '内容を確認して、もう一度「下書きを保存」を押してください。';
    feedback.append(title, hint);
    if (list.length) {
      const ul = document.createElement('ul');
      for (const [key, message] of list) {
        const li = document.createElement('li'), link = document.createElement('a');
        link.href = `#${targets[key].id}`;
        link.dataset.errorField = key;
        link.textContent = message;
        li.append(link);
        ul.append(li);
      }
      feedback.append(ul);
    }
  }

  function reveal() {
    feedback.focus({preventScroll: true});
    document.getElementById('daily-save-area').scrollIntoView({block: 'end'});
  }

  feedback.addEventListener('click', event => {
    const link = event.target.closest('[data-error-field]');
    if (!link) return;
    event.preventDefault();
    const key = link.dataset.errorField;
    const target = key === 'timeline' ? rows.querySelector('[name="timeline_time"]') || targets.timeline : targets[key];
    target.focus({preventScroll: true});
    target.scrollIntoView({block: 'center'});
  });

  form.addEventListener('submit', event => {
    const list = errors();
    if (!list.length) return; // Preserve the normal POST, save and redirect.
    event.preventDefault();
    attempted = true;
    render(list);
    reveal();
  });

  function refresh() {
    if (!attempted) return;
    const list = errors();
    if (JSON.stringify(list) !== JSON.stringify(lastErrors)) render(list);
  }
  form.addEventListener('input', refresh);
  form.addEventListener('change', refresh);
  // Row insertion/removal and example copying also change validation without typing.
  new MutationObserver(refresh).observe(rows, {childList: true});
  if (attempted) reveal();
})();
