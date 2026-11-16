/* Presence design only: fictional colleagues, no network or production data. */
(() => {
  'use strict';
  const root = document.querySelector('#drive-monthly-plan');
  const panel = document.createElement('section');
  panel.id = 'editing-presence';
  panel.setAttribute('aria-label', 'この月案を編集中の職員');
  panel.setAttribute('aria-live', 'polite');
  panel.innerHTML = '<h3 id="presence-heading"></h3><div id="presence-people"></div><p id="presence-warning" role="status" hidden></p><p id="presence-explanation"></p><small id="presence-confirmed"></small>';
  root.querySelector('.toolbar').after(panel);
  const boot = JSON.parse(document.querySelector('#monthly-library-boot').textContent);
  let context = boot;
  let field = root.querySelector('[data-cell][data-active="true"]')?.dataset.cell || 'common:goal';
  const scopeKey = value => `${value.classroom_id}/${value.target_month}/${value.age}`;
  let peerScope = scopeKey(context), peerField = '', mode = 'other', confirmedAt = new Date();
  let lastConnectedMode = 'other';
  let peerName = context.preview_peer_names?.[0] || '';
  const at = selector => panel.querySelector(selector);
  const text = (selector, value) => {at(selector).textContent = value;};
  const label = key => {
    const childRef = key.startsWith('child:') ? key.split(':').slice(0,2).join(':') : null;
    const name = childRef ? context.sheet.children.find(child => child.ref === childRef)?.name : context.classroom_name;
    return `${name || context.classroom_name} / ${context.definitions[key]?.label || '担任名'}`;
  };
  function otherField() {
    const personal = context.sheet.children.map(child => `${child.ref}:play`);
    return [...personal, 'common:home', ...Object.keys(context.definitions)].find(key => key !== field && context.definitions[key]) || field;
  }
  function controls() {
    document.querySelectorAll('[data-presence-case]').forEach(button => button.setAttribute('aria-pressed',String(button.dataset.presenceCase === mode)));
  }
  function render() {
    const sameScope = scopeKey(context) === peerScope;
    const connected = mode !== 'offline';
    const hasPeer = sameScope && !!peerName && (mode === 'offline' ? lastConnectedMode !== 'none' : mode !== 'none');
    const colliding = connected && hasPeer && context.editable && field === peerField;
    panel.dataset.state = connected ? colliding ? 'same' : hasPeer ? 'other' : 'none' : 'offline';
    text('#presence-heading', connected ? hasPeer ? 'ほかに1人がこの月案を編集中です' : 'ほかに編集中の職員はいません' : '編集中の職員の状況を確認できません');
    const people = at('#presence-people');
    people.replaceChildren();
    if (hasPeer) {
      const chip = document.createElement('span');
      chip.className = 'presence-person';
      const dot = document.createElement('span'); dot.className = 'presence-dot'; dot.setAttribute('aria-hidden','true');
      const name = document.createElement('strong'); name.textContent = `${peerName}さん`;
      const activity = document.createElement('span'); activity.textContent = `${label(peerField)} ${connected ? 'を編集中' : '（最後に確認した欄）'}`;
      chip.append(dot,name,activity); people.append(chip);
    }
    const self = document.createElement('span'); self.id = 'presence-self';
    self.textContent = context.editable ? 'あなた：編集できます' : 'あなた：閲覧のみ';
    people.append(self);
    at('#presence-warning').hidden = !colliding;
    text('#presence-warning', colliding ? `${peerName}さんも同じ欄を編集中です。入力が重ならないよう、担当者同士で確認してください。` : '');
    text('#presence-explanation', !connected
      ? '最新の状況を確認できていません。ほかの職員が編集している可能性があります。'
      : hasPeer ? '違う欄への変更は、それぞれ保存できます。同じ欄への変更が重なると、内容を確認する画面が開きます。'
      : 'この表示は目安です。保存時にも、ほかの職員の更新を確認します。');
    if (!context.editable && connected) text('#presence-explanation','保存済みの月案を閲覧できます。編集中の表示によって編集権限は変わりません。');
    text('#presence-confirmed', (connected ? '確認時刻：' : '最後に確認できた時刻：') + confirmedAt.toLocaleTimeString('ja-JP', {hour:'2-digit',minute:'2-digit',second:'2-digit'}));
    root.querySelectorAll('[data-other-editor]').forEach(cell => {delete cell.dataset.otherEditor; cell.removeAttribute('title');});
    if (connected && hasPeer) root.querySelectorAll('[data-cell],[data-owner]').forEach(cell => {
      if((cell.hasAttribute('data-owner') ? 'owner' : cell.dataset.cell) === peerField) {cell.dataset.otherEditor = peerName; cell.title = `${peerName}さんが編集中`;}
    });
    controls();
  }
  function simulate(next) {
    if(next === 'offline') {lastConnectedMode = mode === 'offline' ? lastConnectedMode : mode;}
    else {
      confirmedAt = new Date(); peerScope = scopeKey(context); peerName = context.preview_peer_names?.[0] || '';
      peerField = next === 'same' ? field : otherField();
    }
    mode = next;
    render();
  }
  window.renderPreviewPresence = (nextContext, nextField) => {
    context = nextContext;
    if(nextField) field = nextField;
    render();
  };
  root.addEventListener('focusin', event => {
    if(event.target.matches('[data-owner]')) {field = 'owner'; render();}
  });
  // The sheet rebuilds cells on scope/page changes after its highlight hook.
  new MutationObserver(() => render()).observe(root.querySelector('#form'),{childList:true,subtree:true});
  document.querySelectorAll('[data-presence-case]').forEach(button => button.addEventListener('click', () => simulate(button.dataset.presenceCase)));
  document.addEventListener('preview-peer-saved',()=>simulate('none'));
  peerField = otherField();
  render();
})();
