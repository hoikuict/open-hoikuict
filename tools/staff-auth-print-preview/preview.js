/* Fictional state only. No API, browser storage, real code issuance, or messages. */
(() => {
  const fixture = window.StaffPrintFixture;
  const root = document.getElementById('mock-view');
  const actionSelect = document.getElementById('preview-action');
  const viewSelect = document.getElementById('preview-view');
  const stateSelect = document.getElementById('preview-state');
  let loginId = 'hana@example.invalid';
  let confirming = false;
  let issueCount = 1;
  const text = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const action = () => actionSelect.value;
  const code = () => action() === 'activate' ? 'H7K3MP' : 'R9T4NW';
  const notify = message => { document.getElementById('preview-status').textContent = message; };
  function showError(message) {
    let box = root.querySelector('[role="alert"]');
    if (!box) { box = document.createElement('div'); box.className = 'status-error'; box.setAttribute('role', 'alert'); root.querySelector('form').before(box); }
    box.textContent = message;
  }
  function handout() {
    const initial = action() === 'activate';
    const expired = stateSelect.value === 'expired';
    const noUrl = stateSelect.value === 'urlmissing';
    const label = initial ? '初回設定' : 'パスワード再設定';
    const codeLabel = initial ? '有効化コード' : '再設定コード';
    const qr = fixture.qr[action()];
    root.innerHTML = `<div class="issue-toolbar no-print"><div><h1>${label}コードを発行しました</h1><p>本人へ渡す案内を印刷できます。</p></div><div class="issue-buttons"><button id="copy-code" class="secondary">コードをコピー</button><button id="print-handout" class="primary" ${expired || noUrl ? 'disabled' : ''}>QR付き案内を印刷</button></div></div>
      ${expired ? '<div class="status-error" role="alert">このコードは有効期限を過ぎています。認証管理に戻り、新しいコードを発行してください。</div>' : ''}
      ${noUrl ? '<div class="status-error" role="alert">案内に使う施設URLが未設定です。運用担当者がURLを設定してから、再度発行してください。</div>' : ''}
      <article class="handout" id="handout" aria-label="本人へ渡す案内用紙">
        <div class="paper-top"><span class="facility">みほん保育園</span><span class="paper-tag">職員ご本人へ</span></div>
        <h2 class="paper-title">${initial ? '職員アカウント 初回設定のご案内' : 'パスワード再設定のご案内'}</h2>
        <p class="paper-lead">${initial ? 'ご自身のスマートフォンなどで、ログインIDとパスワードを設定してください。' : 'ご自身のスマートフォンなどで、新しいパスワードを設定してください。'}</p>
        <p class="person">見本 はな<small>さん</small></p>
        <dl class="credentials"><div><dt>ログインID</dt><dd id="printed-login">${text(loginId)}${initial ? '<small>初回設定の画面で変更できます。変更したIDを覚えておいてください。</small>' : ''}</dd></div>
          <div><dt>${codeLabel}</dt><dd><span class="code" id="printed-code">${code()}</span><small>半角英数字6文字・1回限り</small></dd></div>
          <div><dt>有効期限</dt><dd><span class="deadline ${expired ? 'invalid' : ''}">2026年11月1日 10:30 まで${expired ? '（期限切れ）' : ''}</span><small>発行：2026年11月1日 10:00 ／ 発行から30分間（日本時間）</small></dd></div></dl>
        <div class="qr-step"><div class="qr-wrap" role="img" aria-label="${label}画面のQRコード">${noUrl ? '<span class="unavailable">施設URL未設定<br>QRを表示できません</span>' : qr.svg}</div><div><h3 class="step-head"><span class="number">1</span>QRコードから設定画面を開く</h3><p class="qr-description">スマートフォンのカメラで読み取ります。<br>読み取れない場合は、下のURLを開いてください。</p><p class="url">${noUrl ? '施設URL未設定' : text(qr.url)}</p></div></div>
        <ol class="paper-steps"><li><h3 class="step-head"><span class="number">2</span>${initial ? 'コードを確認し、ログイン情報を設定する' : 'コードと新しいパスワードを入力する'}</h3><p>${initial ? '上の有効化コードを入力し、「コードを確認して次へ」を押します。氏名・ログインIDを確認し、新しいパスワードを2回入力して「ログイン情報を設定」を押します。' : '上の再設定コードと、新しいパスワードを2回入力して「パスワードを再設定」を押します。ログインIDは変わりません。'}</p><p>パスワードは8〜128文字で、ご本人が決めてください。</p></li>
          <li><h3 class="step-head"><span class="number">3</span>ログインして確認する</h3><p>${initial ? '設定したログインIDとパスワードで、職員ログイン画面からログインします。' : 'これまでのログインIDと新しいパスワードで、職員ログイン画面からログインします。'}</p><p class="url">https://staff.example.invalid/staff/login</p></li></ol>
        <div class="paper-foot"><p><strong>期限が切れた・用紙をなくした場合</strong><br>園の管理者へ再発行を依頼してください。再発行後は新しい用紙のコードを使います。</p><p>この用紙はご本人だけで管理し、設定が終わったら破棄してください。</p></div>
        <p class="sample-mark">確認用見本・架空の職員／URL／コードです。実際の登録には使えません。</p>
      </article><p class="screen-note no-print">このコードは発行から30分間有効です。画面を離れると再表示できません。印刷をキャンセルしても、発行済みコードの期限は変わりません。</p>
      <a href="#" id="back-admin" class="back-link no-print">職員管理へ戻る</a>`;
    document.getElementById('print-handout').addEventListener('click', () => window.print());
    document.getElementById('copy-code').addEventListener('click', async event => {
      try { await navigator.clipboard.writeText(code()); event.target.textContent = 'コピーしました'; }
      catch { notify('この環境ではコピーできません。表示された見本コードを選択してコピーしてください。'); }
    });
    document.getElementById('back-admin').addEventListener('click', event => {
      event.preventDefault();
      if (!window.confirm('この画面を離れると同じコードは再表示できません。戻りますか？')) return;
      viewSelect.value = 'admin'; stateSelect.value = 'filled'; render();
      notify('確認用：職員管理に戻った後、同じ職員の認証管理を開いた状態です。');
    });
  }
  function render() {
    root.classList.toggle('no-print', viewSelect.value !== 'issued');
    if (viewSelect.value === 'issued') {
      if (['empty','partial','error'].includes(stateSelect.value)) { viewSelect.value = 'admin'; confirming = false; }
      else { handout(); return; }
    }
    const key = confirming ? 'confirm' : `${viewSelect.value}-${action()}`;
    root.innerHTML = fixture.views[key];
    const form = root.querySelector('form');
    const state = stateSelect.value;
    const set = (name, value) => { const input = form.elements.namedItem(name); if (input) input.value = value; };
    set('login_id', loginId);
    if (viewSelect.value === 'admin') {
      set('reason', state === 'empty' || state === 'partial' ? '' : action() === 'activate' ? '新規採用職員の初期設定' : '本人からパスワード紛失の申告');
      if (state === 'empty') set('login_id', '');
    } else {
      set(action() === 'activate' ? 'activation_code' : 'reset_code', state === 'empty' ? '' : code());
      if (state === 'filled' || state === 'error') { set('password','Preview2026!'); set('password_confirmation',state === 'error' ? 'Different2026!' : 'Preview2026!'); }
    }
    if (state === 'error') showError(viewSelect.value === 'admin' ? 'コードを発行できませんでした。入力内容を確認して、もう一度お試しください。' : '入力内容を確認してください。');
    if (state === 'expired') showError('コードが無効か、有効期限が切れています。管理者に再発行を依頼してください。');
    if (state === 'urlmissing') showError('案内に使う施設URLが未設定です。設定を確認してください。');
    form.addEventListener('submit', event => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      if (viewSelect.value === 'admin') {
        if (stateSelect.value === 'error') { showError('コードを発行できませんでした。入力内容は保持しています。状態を「入力済み」に切り替えると続けられます。'); return; }
        if (stateSelect.value === 'urlmissing') { showError('案内に使う施設URLを設定してから発行してください。'); return; }
        loginId = form.elements.namedItem('login_id')?.value.trim() || loginId;
        if (!form.elements.namedItem('reason').value.trim()) { showError('発行理由を入力してください。'); return; }
        if (!loginId) { showError('ログインIDを入力してください。'); return; }
        issueCount += 1; viewSelect.value = 'issued'; stateSelect.value = 'filled'; handout();
        root.classList.remove('no-print'); notify('確認用：コード発行を再現しました。実際のコード発行・保存はありません。');
      } else {
        if (stateSelect.value === 'expired') { showError('コードが無効か、有効期限が切れています。管理者に再発行を依頼してください。'); return; }
        if (!confirming && form.elements.namedItem(action() === 'activate' ? 'activation_code' : 'reset_code').value.trim().toUpperCase() !== code()) { showError('見本のコードを確認してください。'); return; }
        if (action() === 'activate' && !confirming) { confirming = true; render(); notify('本人の入力画面：ログインID・パスワードを確認できます。'); return; }
        if (form.elements.namedItem('password').value !== form.elements.namedItem('password_confirmation').value) { showError('確認用パスワードが一致しません。'); return; }
        root.innerHTML = '<section class="rounded-3xl border border-emerald-200 bg-white p-8"><h1 class="text-2xl font-bold">設定が完了しました（確認用）</h1><p class="mt-4">実際は職員ログイン画面へ移動し、設定したIDとパスワードでログインします。</p><button class="secondary mt-6" id="again">案内用紙へ戻る</button></section>';
        document.getElementById('again').onclick = () => { viewSelect.value = 'issued'; stateSelect.value = 'filled'; confirming = false; render(); };
        notify('確認用の完了表示です。パスワードは保存・送信していません。');
      }
    });
  }
  [actionSelect,viewSelect,stateSelect].forEach(select => select.addEventListener('change', () => { confirming = false; render(); notify('確認用の画面・状態を切り替えました。変更した入力は見本に戻ります。'); }));
  document.getElementById('try-recipient').onclick = () => { viewSelect.value = 'recipient'; stateSelect.value = 'empty'; confirming = false; render(); notify('QRで開く本人の画面を再現しています。実際のQRは架空のURLなので接続できません。'); };
  document.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link || link.id === 'back-admin') return;
    event.preventDefault();
    if (confirming && link.getAttribute('href') === '/staff/activate') { confirming = false; render(); }
    else notify('このリンクは確認用です。本番の画面には移動しません。');
  });
  document.addEventListener('submit', event => event.preventDefault());
  const sidebar = document.getElementById('staff-sidebar');
  const backdrop = document.getElementById('staff-sidebar-backdrop');
  const closeMenu = () => { sidebar.classList.add('-translate-x-full'); backdrop.classList.add('hidden'); };
  document.querySelector('[data-sidebar-open]').onclick = () => { sidebar.classList.remove('-translate-x-full'); backdrop.classList.remove('hidden'); };
  document.querySelector('[data-sidebar-close]').onclick = closeMenu;
  backdrop.onclick = closeMenu;
  window.addEventListener('resize', closeMenu);
  new ResizeObserver(() => document.documentElement.style.setProperty('--preview-toolbar-height', document.getElementById('preview-toolbar').offsetHeight + 'px')).observe(document.getElementById('preview-toolbar'));
  window.staffPrintPreview = { issuedCount: () => issueCount };
  render();
})();
