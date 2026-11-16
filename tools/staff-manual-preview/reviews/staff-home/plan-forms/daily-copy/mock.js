// All trial data stays in this page. Use the deployed form's row template and row controls.
(() => {
  const byId = id => document.getElementById(id);
  const draft = byId('daily-draft');
  const search = byId('example-search');
  const rows = byId('daily-timeline-rows');
  const choices = byId('choice');
  const feedback = byId('daily-example-feedback');
  const samples = JSON.parse(byId('example-data').textContent);
  const input = name => draft.elements.namedItem(name);
  const columns = ['timeline_time', 'timeline_children', 'timeline_support', 'timeline_considerations'];
  const cards = [...document.querySelectorAll('.daily-example-card')];
  let candidate = null;
  let nextRow = 0;
  let savedDraft = null;

  function rowValues(row) {
    return columns.map(name => row.querySelector('[name="' + name + '"]').value);
  }
  function hasValues(values) {
    return values.some(value => value.trim() !== '');
  }
  function addRow(values) {
    const row = byId('daily-row-template').content.firstElementChild.cloneNode(true);
    row.querySelector('[name=timeline_row_key]').value = 'example-row-' + ++nextRow;
    columns.forEach((name, i) => { row.querySelector('[name="' + name + '"]').value = values[i] || ''; });
    rows.append(row);
  }
  function notify(text, error = false) {
    feedback.textContent = text;
    feedback.hidden = false;
    feedback.toggleAttribute('data-error', error);
  }
  function scrollToDraft() {
    input('daily_aims').focus({preventScroll:true});
    (feedback.hidden ? draft : feedback).scrollIntoView({block:'start'});
  }
  function hasDraftContent() {
    return hasValues([input('age_class').value, input('daily_aims').value, input('daily_content').value])
      || [...rows.rows].some(row => hasValues(rowValues(row)));
  }
  function appendText(current, addition) {
    if (!addition.trim()) return current;
    if (!current.trim()) return addition;
    return current + (current.endsWith('\n') ? '' : '\n') + addition;
  }
  function useExample(example, mode) {
    const append = mode === 'append';
    const fields = {daily_aims:example.aims.join('\n'), daily_content:example.content};
    Object.entries(fields).forEach(([name, text]) => {
      const field = input(name);
      field.value = append ? appendText(field.value, text) : text;
    });
    if (!append) {
      input('age_class').value = example.age_class;
      input('example_id').value = example.id;
      input('example_source_ref').value = 'sample-' + example.id;
    }
    if (!append || ![...rows.rows].some(row => hasValues(rowValues(row)))) rows.replaceChildren();
    for (const block of example.activity_blocks) {
      addRow([block.time_and_activity, block.child_state, block.support, block.considerations]);
    }
    for (const el of draft.querySelectorAll('[aria-invalid]')) el.removeAttribute('aria-invalid');
    const messages = {append:'文例を追加しました。', replace:'文例に置き換えました。', copy:'文例をコピーしました。'};
    notify(messages[mode] + ' 内容を確かめて「下書きを保存」を押してください。');
    scrollToDraft();
  }
  function choose(example) {
    if (choices.open) return;
    if (!hasDraftContent()) {
      useExample(example, 'copy');
      return;
    }
    candidate = example;
    byId('choice-example').textContent = '選んだ文例は「' + example.main_activity + '」（' + example.age_class + '）です。';
    choices.showModal();
  }
  choices.addEventListener('click', event => {
    const button = event.target.closest('[data-mode]');
    if (!button || !candidate) return;
    const selected = candidate;
    candidate = null;
    choices.close();
    if (button.dataset.mode === 'cancel') {
      if (feedback.hidden || !feedback.hasAttribute('data-error')) notify('書きかけの日案に戻りました。');
      scrollToDraft();
    } else {
      useExample(selected, button.dataset.mode);
    }
  });
  choices.addEventListener('cancel', () => { candidate = null; });

  const sampleById = new Map(samples.map(example => [example.id, example]));
  document.querySelector('.daily-example-list').addEventListener('click', event => {
    const button = event.target.closest('[data-copy]');
    if (button) choose(sampleById.get(button.dataset.copy));
  });
  byId('try-copy').addEventListener('click', () => choose(samples[0]));
  const noResults = document.createElement('p');
  noResults.textContent = '条件に合う日案例がありません。下の表へ手入力して作成できます。';
  noResults.hidden = true;
  document.querySelector('.daily-example-list').after(noResults);
  function filterExamples() {
    const filters = new FormData(search);
    const terms = String(filters.get('q')).trim().split(/\s+/).filter(Boolean);
    let count = 0;
    for (const card of cards) {
      const sample = sampleById.get(card.querySelector('[data-copy]').dataset.copy);
      const show = (!filters.get('age_class') || filters.get('age_class') === sample.age_class)
        && (!filters.get('month') || filters.get('month') === String(sample.month))
        && terms.every(term => card.textContent.includes(term));
      card.hidden = !show;
      if (show) count++;
    }
    document.querySelector('.daily-example-list-heading strong').textContent = '主な活動　' + count + '件';
    noResults.hidden = count > 0;
  }
  search.addEventListener('submit', event => { event.preventDefault(); filterExamples(); });

  function invalidFields() {
    const issues = [];
    if (!input('target_date').value) issues.push([input('target_date'), '対象日を選択してください。']);
    if (!input('age_class').value) issues.push([input('age_class'), '年齢を選択してください。']);
    if (![...rows.rows].some(row => hasValues(rowValues(row)))) {
      issues.push([rows.querySelector('[name=timeline_time]'), '1日の流れを1行以上入力してください。']);
    }
    return issues;
  }
  function validate() {
    draft.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
    const issues = invalidFields();
    if (!issues.length) return true;
    issues.forEach(([field]) => field.setAttribute('aria-invalid', 'true'));
    notify('入力を確認してください。' + issues.map(issue => issue[1]).join(' '), true);
    return false;
  }
  function showSaved() {
    byId('saved-scope').textContent = [savedDraft.date, savedDraft.room, savedDraft.age, savedDraft.owner].filter(Boolean).join('　');
    byId('saved-aim').textContent = savedDraft.aim;
    byId('saved-content').textContent = savedDraft.content;
    const body = byId('saved-rows');
    body.replaceChildren();
    for (const values of savedDraft.rows) {
      const row = body.insertRow();
      for (const value of values) row.insertCell().textContent = value;
    }
    byId('editor').hidden = true;
    byId('saved').hidden = false;
    byId('try-copy').hidden = true;
    byId('saved-title').focus();
  }
  draft.addEventListener('submit', event => {
    event.preventDefault();
    if (!validate()) { feedback.scrollIntoView({block:'center'}); return; }
    savedDraft = {
      date:input('target_date').value, room:input('classroom_ref').value, age:input('age_class').value,
      owner:input('owner_name').value, aim:input('daily_aims').value, content:input('daily_content').value,
      rows:[...rows.rows].map(rowValues),
    };
    showSaved();
  });
  function showEditor() {
    byId('saved').hidden = true;
    byId('editor').hidden = false;
    byId('try-copy').hidden = false;
    feedback.hidden = true;
  }
  byId('edit').addEventListener('click', () => { showEditor(); scrollToDraft(); });
  function reset() {
    const state = byId('scenario').value;
    savedDraft = null;
    showEditor();
    draft.reset();
    draft.querySelectorAll('[aria-invalid]').forEach(el => el.removeAttribute('aria-invalid'));
    rows.replaceChildren();
    input('age_class').value = state === 'empty' ? '' : '3歳児';
    if (state !== 'empty') input('daily_aims').value = '葉っぱの色を見つける。';
    if (state === 'filled') input('daily_content').value = '園庭を歩き、赤や黄色の葉っぱを探す。';
    if (state === 'filled' || state === 'partial') {
      addRow(['9:30', '園庭で好きな葉っぱを探す。', state === 'filled' ? '見つけた葉っぱの色を一緒に見る。' : '',
        state === 'filled' ? '足元を確かめる。' : '']);
    } else { addRow([]); }
    search.reset();
    cards.forEach(card => { card.open = false; });
    filterExamples();
    if (state === 'error') { input('target_date').value = ''; validate(); }
  }
  byId('scenario').addEventListener('change', reset);
  byId('reset').addEventListener('click', reset);
  reset();
})();
