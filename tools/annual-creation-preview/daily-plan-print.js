/* Keep the printable reflection current without changing or saving the input. */
(() => {
  const panel = document.querySelector('.daily-reflection-panel');
  const input = panel?.querySelector('[name="reflection_body"]');
  const output = panel?.querySelector('[data-daily-print-reflection]');
  if (!input || !output) return;

  const update = () => {
    output.textContent = input.value.trim() ? input.value : '未入力';
  };
  input.addEventListener('input', update);
  window.addEventListener('beforeprint', update);
  update();
})();
