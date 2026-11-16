document.querySelectorAll('[data-order-editor]').forEach(editor => {
  const list = editor.querySelector('ol');
  const savedRows = list.cloneNode(true);
  editor.addEventListener('resetorder', () => {
    list.replaceChildren(...Array.from(savedRows.children, row => row.cloneNode(true)));
    update();
  });
  function update() {
    Array.from(list.children).forEach((row, i) => {
      row.querySelector('[data-move="up"]').disabled = i === 0;
      row.querySelector('[data-move="down"]').disabled = i === list.children.length - 1;
    });
  }
  editor.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (!button) return;
    const row = button.closest('li');
    if (button.hasAttribute('data-add')) {
      const copy = editor.querySelector('template').content.firstElementChild.cloneNode(true);
      copy.querySelector('[name=emergency_label]').value = button.dataset.label || '';
      copy.querySelector('[name=emergency_phone]').value = button.dataset.phone || '';
      list.append(copy);
      copy.querySelector('input').focus();
    } else if (button.hasAttribute('data-remove')) row.remove();
    else if (button.dataset.move === 'up' && row.previousElementSibling) row.previousElementSibling.before(row);
    else if (button.dataset.move === 'down' && row.nextElementSibling) row.nextElementSibling.after(row);
    update();
  });
  update();
});

document.querySelectorAll('[data-day-emergency]').forEach(section => {
  const editor = section.querySelector('[data-order-editor]');
  function sync() {
    editor.hidden = section.querySelector('[name=emergency_mode]:checked')?.value !== 'change';
    editor.querySelectorAll('input').forEach(input => { input.disabled = editor.hidden; });
  }
  section.addEventListener('change', sync);
  section.querySelector('[data-cancel-emergency]')?.addEventListener('click', () => {
    section.querySelectorAll('[name=emergency_mode]').forEach(radio => { radio.checked = false; });
    section.querySelector('details').open = false;
    editor.dispatchEvent(new Event('resetorder'));
    sync();
  });
  sync();
});
