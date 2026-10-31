(() => {
  'use strict';
  const button = document.querySelector('#cancel-guardian-registration');
  const form = document.querySelector('#guardian-registration-form');
  if (!button || !form) return;
  button.hidden = false;
  button.addEventListener('click', () => {
    if (!window.confirm('入力をやめますか？ 入力中の内容は保存されません。')) return;
    const card = form.closest('.card');
    if (!card) return;
    const heading = document.createElement('h1');
    heading.textContent = '入力を終了しました';
    heading.tabIndex = -1;
    const message = document.createElement('p');
    message.textContent = '園への提出は行っていません。再開する場合は招待リンクからお進みください。';
    card.replaceChildren(heading, message);
    heading.focus();
  });
})();
