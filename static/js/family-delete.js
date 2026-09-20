(() => {
  const form = document.querySelector('[data-family-delete]');
  if (!form) return;
  const confirmation = form.querySelector('[name="confirmed"]');
  const submit = form.querySelector('[type="submit"]');
  const update = () => { submit.disabled = !confirmation.checked; };
  confirmation.addEventListener('change', update);
  window.addEventListener('pageshow', () => {
    confirmation.checked = false;
    submit.textContent = 'この家族を削除';
    update();
  });
  form.addEventListener('submit', () => {
    submit.disabled = true;
    submit.textContent = '削除しています…';
  });
  update();
})();
