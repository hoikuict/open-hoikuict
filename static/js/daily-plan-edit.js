(() => {
  'use strict';
  const timeline = document.getElementById('daily-saved-timeline');
  if (!timeline) return;
  const keys = new Set(Array.from(timeline.querySelectorAll('[name="daily_row_key"]'), field => field.value));
  timeline.addEventListener('click', event => {
    const button = event.target.closest('.insert-daily-row');
    if (!button) return;
    const current = button.closest('tr');
    const row = current.cloneNode(true);
    const previousKey = row.querySelector('[name="daily_row_key"]').value;
    let key;
    do {
      key = `row_${Date.now()}_${Math.random().toString(16).slice(2)}`;
    } while (keys.has(key));
    keys.add(key);
    row.querySelectorAll('input,textarea').forEach(field => {
      if (field.name === 'daily_row_key') {
        field.value = key;
      } else {
        field.name = field.name.replace(`__${previousKey}`, `__${key}`);
        field.value = '';
      }
    });
    row.querySelectorAll('.inline-note').forEach(note => note.remove());
    current.after(row);
    row.querySelector('[name^="rowtime__"]').focus();
  });
})();
