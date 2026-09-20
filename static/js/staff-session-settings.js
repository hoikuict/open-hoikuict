(() => {
  const form = document.getElementById('session-settings');
  if (!form) return;
  const persisted = JSON.parse(document.getElementById('persisted-session-settings').textContent);
  const names = ['idle_value', 'idle_unit', 'absolute_hours'];
  const confirmation = document.getElementById('leave-confirmation');
  let leaving = false;
  let previousUnit = form.elements.idle_unit.value;
  const minutes = () => Number(form.elements.idle_value.value) * (form.elements.idle_unit.value === 'hours' ? 60 : 1);
  const savedMinutes = Number(persisted.idle_value) * (persisted.idle_unit === 'hours' ? 60 : 1);
  const dirty = () => !form.elements.idle_value.value.trim() || !form.elements.absolute_hours.value.trim() ||
    Math.abs(minutes() - savedMinutes) > 0.00001 || Number(form.elements.absolute_hours.value) !== Number(persisted.absolute_hours);
  function render() {
    document.getElementById('session-dirty').textContent = dirty() ? '未保存の変更があります' : '保存済みの設定です';
    const idle = minutes();
    const hours = Number(form.elements.absolute_hours.value);
    const valid = idle >= 5 && idle <= 1440 && Math.abs(idle - Math.round(idle)) < 0.00001 &&
      Number.isInteger(hours) && hours >= 1 && hours <= 24 && idle <= hours * 60;
    const duration = value => value % 60 === 0 ? (value / 60) + '時間' : value + '分';
    document.getElementById('session-preview').textContent = valid
      ? `設定後：非操作 ${duration(Math.round(idle))} / 最長 ${hours}時間。例：7:00にログインした場合、最長で${7 + hours >= 24 ? '翌日' : ''}${(7 + hours) % 24}:00まで。`
      : '2つの時間を入力すると、ログインを維持できる時間を確認できます。';
  }
  function restore() {
    names.forEach(name => { form.elements[name].value = persisted[name]; });
    document.getElementById('form-error')?.remove();
    confirmation.hidden = true;
    previousUnit = form.elements.idle_unit.value;
    render();
  }
  document.getElementById('workday-preset').addEventListener('click', () => {
    form.elements.idle_value.value = '12';
    form.elements.idle_unit.value = 'hours';
    form.elements.absolute_hours.value = '12';
    previousUnit = 'hours';
    render();
  });
  form.elements.idle_unit.addEventListener('change', () => {
    const field = form.elements.idle_value;
    const value = Number(field.value) * (previousUnit === 'hours' ? 60 : 1);
    previousUnit = form.elements.idle_unit.value;
    if (field.value.trim() && Number.isFinite(value)) {
      field.value = String(Number((value / (previousUnit === 'hours' ? 60 : 1)).toFixed(10)));
    }
    render();
  });
  form.addEventListener('input', render);
  document.getElementById('cancel-changes').addEventListener('click', restore);
  document.getElementById('settings-back').addEventListener('click', event => {
    if (dirty()) {
      event.preventDefault();
      confirmation.hidden = false;
      document.getElementById('keep-editing').focus();
    }
  });
  document.getElementById('keep-editing').addEventListener('click', () => {
    confirmation.hidden = true;
    form.elements.idle_value.focus();
  });
  document.getElementById('discard-and-leave').addEventListener('click', () => {
    restore();
    leaving = true;
    window.location.assign('/settings');
  });
  form.addEventListener('submit', () => { leaving = true; });
  window.addEventListener('beforeunload', event => {
    if (!leaving && dirty()) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  render();
})();
