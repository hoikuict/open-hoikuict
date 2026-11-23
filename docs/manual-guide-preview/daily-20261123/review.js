'use strict';
const fontButton = document.getElementById('font-toggle');
fontButton.addEventListener('click', () => {
  const large = document.body.classList.toggle('large');
  fontButton.setAttribute('aria-pressed', String(large));
  fontButton.textContent = large ? '標準の文字に戻す' : '文字を大きく';
});
for (const group of document.querySelectorAll('.states')) {
  group.addEventListener('click', event => {
    const button = event.target.closest('[data-state]');
    if (!button) return;
    for (const item of group.querySelectorAll('[data-state]')) item.setAttribute('aria-pressed', String(item === button));
    for (const panel of group.querySelectorAll('[data-state-panel]')) panel.hidden = panel.dataset.statePanel !== button.dataset.state;
  });
}
const dialog = document.getElementById('image-dialog');
let opener;
for (const link of document.querySelectorAll('.image-link')) link.addEventListener('click', event => {
  event.preventDefault(); opener = link;
  const source = link.querySelector('img'), image = dialog.querySelector('img');
  image.src = source.src; image.alt = source.alt;
  dialog.querySelector('p').textContent = source.alt;
  dialog.showModal(); document.body.classList.add('modal-open');
});
document.getElementById('image-close').addEventListener('click', () => dialog.close());
dialog.addEventListener('close', () => { document.body.classList.remove('modal-open'); opener?.focus(); });
const steps = [...document.querySelectorAll('.manual-step')], toggle = document.getElementById('reading-toggle');
let single = false, position = 0;
function updateSteps() {
  steps.forEach((step, index) => { step.hidden = single && index !== position; });
  document.querySelector('.step-nav').hidden = !single;
  toggle.textContent = single ? 'まとめて読む' : '1つずつ読む'; toggle.setAttribute('aria-pressed', String(single));
  document.getElementById('step-position').textContent = `${position + 1} / ${steps.length}`;
  document.getElementById('previous-step').disabled = position === 0;
  document.getElementById('next-step').disabled = position === steps.length - 1;
}
if (toggle) {
  toggle.addEventListener('click', () => { single = !single; updateSteps(); });
  for (const [id, change] of [['previous-step', -1], ['next-step', 1]]) document.getElementById(id).addEventListener('click', () => {
    position += change; updateSteps(); steps[position].scrollIntoView({block:'start'});
  });
  for (const link of document.querySelectorAll('.contents a')) link.addEventListener('click', () => {
    position = steps.findIndex(step => '#' + step.id === link.getAttribute('href')); if (single) updateSteps();
  });
}
