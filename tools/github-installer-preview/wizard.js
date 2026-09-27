'use strict';

// Static review only. No network calls, storage, real installation or accounts.
const panel = document.querySelector('#wizard');
const steps = document.querySelector('#steps');
const cancelDialog = document.querySelector('#cancel-dialog');
let timer;
let os = 'windows';
let state;
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const osName = () => os === 'windows' ? 'Windows 11' : 'Ubuntu 24.04 LTS';
const defaultPath = () => os === 'windows' ? 'C:\\Users\\Trial\\AppData\\Local\\OpenHoikuICT\\beta' : '/home/trial/.local/share/open-hoikuict/beta';
const stageNames = ['準備', '管理者', '確認'];
const tasks = ['保存先と配布版を確認', 'GitHubからダウンロード', '配布ファイルを確認', 'アプリと必要なソフトを準備', 'データと設定を用意', '管理者アカウントを作成', '起動を確認'];

function reset(scenario = 'empty') {
  clearTimeout(timer);
  if (cancelDialog.open) cancelDialog.close();
  state = {step: 0, returnStep: 0, progress: 0, scenario, fail: scenario === 'failure', existing: scenario === 'existing', errors: {}, running: false,
    release: 'ready', version: '2026.9.23', changed: false, notice: '',
    values: {name:'', email:'', password:'', confirm:'', login:'', reason:'このPCでのβ版試用', actor:'', approver:'', path:defaultPath(), port:'8001'}};
  if (['partial','filled','invalid','failure','download','integrity','changed'].includes(scenario)) {
    Object.assign(state.values, {name:'試用管理者', email:'admin@example.test'});
    state.step = 1;
  }
  if (['filled','invalid','failure','download','integrity','changed'].includes(scenario)) {
    state.values.password = 'TrialSetup-2026';
    state.values.confirm = 'TrialSetup-2026';
  }
  if (scenario === 'invalid') { state.values.email = 'メールの例'; state.values.confirm = 'different'; validate(); }
  if (['failure','download','integrity','changed'].includes(scenario)) state.step = 2;
  if (['offline','unpublished','outdated'].includes(scenario)) state.release = scenario;
  if (os === 'linux') {state.release = 'unsupported'; state.step = 0;}
  render();
  if (scenario === 'empty' && os === 'windows') checkRelease();
}

function checkRelease() {
  clearTimeout(timer);
  state.release = 'checking'; render();
  timer = setTimeout(() => {
    state.release = os === 'linux' ? 'unsupported' : ['unpublished','outdated'].includes(state.scenario) ? state.scenario : 'ready';
    render(false);
  }, 650);
}

function releasePanel() {
  if (state.release === 'checking') return '<div class="release-box" role="status"><strong>GitHubの配布版を確認しています…</strong><p>このPCに対応した最新版を探しています。</p></div>';
  const problems = {
    offline: ['最新版を確認できませんでした', 'インターネット接続を確認して、もう一度お試しください。'],
    unpublished: ['配布の準備中です', 'このPCに導入できる版がまだ公開されていません。公開後にもう一度確認してください。'],
    unsupported: ['このOS向けの配布版は準備中です', '現在の導入対象はWindows 11 x64です。Ubuntu版は公開後に利用できます。'],
    outdated: ['新しい導入アプリが必要です', 'この版を導入するには、公式の配布ページから新しい導入アプリを取得して開き直してください。'],
  };
  if (problems[state.release]) {
    const [heading, message] = problems[state.release];
    return `<div class="error-summary" role="alert"><strong>${heading}</strong><p>${message}</p><button class="secondary" data-action="check-release">もう一度確認</button></div>`;
  }
  return `<div class="release-box"><div class="release-heading"><strong>導入する版</strong><span class="badge">検証済み</span></div><div class="release-version">${escape(state.version)}</div><p>Windows 11 x64 ・ ダウンロード 約80 MB<br>配布元：GitHub / hoikuict/open-hoikuict</p><details><summary>この版の変更内容</summary><ul><li>保護者の利用停止・再開を認証管理にまとめました。</li><li>初期台帳をExcelから登録できます。</li></ul></details></div>`;
}

function effective() {
  return {...state.values, login: state.values.login.trim() || state.values.email.trim(), actor:state.values.actor.trim() || state.values.name.trim(), approver:state.values.approver.trim() || state.values.name.trim()};
}

function field(name, label, type = 'text', note = '', optional = false) {
  const error = state.errors[name];
  const limits = {password:128, confirm:128, login:255, email:255, name:100, path:1024, port:5, reason:300, actor:100, approver:100};
  const hint = name === 'login' ? '未変更ならメールアドレス' : ['actor','approver'].includes(name) ? '未変更なら管理者の名前' : '';
  return `<label for="${name}">${label}${note ? `<span id="${name}-hint">${note}</span>` : ''}<input id="${name}" name="${name}" type="${type}" value="${escape(state.values[name])}" maxlength="${limits[name] || 255}" autocomplete="off" ${optional ? '' : 'required'} ${hint ? `placeholder="${hint}"` : ''} ${error ? `aria-invalid="true" aria-describedby="${name}-error"` : note ? `aria-describedby="${name}-hint"` : ''}>${error ? `<span class="error-field" id="${name}-error">${escape(error)}</span>` : ''}</label>`;
}

function errors() {
  const messages = Object.values(state.errors);
  return messages.length ? `<div class="error-summary" role="alert"><strong>入力を確認してください。</strong><ul>${messages.map(e => `<li>${escape(e)}</li>`).join('')}</ul></div>` : '';
}

function footer(back, forward, forwardLabel, cancel = true) {
  return `<div class="buttons">${cancel ? '<button class="quiet" type="button" data-action="cancel">いったん中断</button>' : ''}${back ? `<button class="secondary" type="button" data-action="${back}">戻る</button>` : ''}${forward ? `<button class="primary" type="button" data-action="${forward}" ${forward==='to-admin'&&state.release!=='ready'?'disabled':''}>${forwardLabel}</button>` : ''}</div>`;
}

function details() {
  return `<details ${['login','reason','actor','approver'].some(n => state.errors[n]) ? 'open' : ''}><summary>ログインID・導入の記録を変更する</summary><p>ログインIDにはメールアドレスを使います。このPCでの試用では、作成と承認を行う人を管理者本人とする案です。別の担当者がいる場合は変更できます。</p><div class="fields">${field('login','ログインID','text','',true)}${field('reason','作成理由')}${field('actor','実行者','text','',true)}${field('approver','承認者','text','',true)}</div></details>`;
}

function preparation() {
  if (state.existing) return `<p class="eyebrow">導入済みの環境を検出した場合</p><h2 tabindex="-1">すでに準備されています</h2><p class="intro">保存済みのデータと設定を使って起動する案です。初期設定は繰り返しません。</p><div class="soft-note"><strong>β版の試用環境</strong><br><code>${escape(state.values.path)}</code></div><p class="subtle">ここでの検出結果は架空のものです。実際のフォルダーは調べていません。</p><div class="buttons"><button class="secondary" data-action="separate">別の場所で新しく試す</button><button class="primary" data-action="existing-launch">起動を試す</button></div>`;
  return `<p class="eyebrow">STEP 1 / 3</p><h2 tabindex="-1">最新版で試用をはじめます</h2><p class="intro">検証済みの配布版をGitHubから取得します。必要なソフトも一緒に用意するので、個別の導入は不要です。</p>${releasePanel()}<ul class="check-list"><li><span class="check">✓</span><div>このPCだけで試用<small>まずは架空の園児・家庭でお試しください。</small></div></li><li><span class="check">✓</span><div>次回からは同じアイコンで起動<small>導入済みの版を使い、毎回ダウンロードしません。</small></div></li></ul><details ${Object.keys(state.errors).length ? 'open' : ''}><summary>保存場所などを変更する</summary><p>既存のファイルがある場所には導入しません。通常は変更不要です。</p>${errors()}<div class="fields">${field('path','保存場所')}${field('port','接続ポート','text')}</div></details>${footer(null,'to-admin','次へ')}`;
}

function admin() {
  return `<p class="eyebrow">STEP 2 / 3</p><h2 tabindex="-1">管理者を決めましょう</h2><p class="intro">ふだん入力するのは、この4項目です。<br>このモックには架空の名前・メール・パスワードを使ってください。</p>${errors()}<div class="fields">${field('name','管理者の名前')}${field('email','メールアドレス','email','ログインIDとして使います。試用中はメールを送りません。')}<div class="two-col">${field('password','パスワード','password','8文字以上（モック用の値）')}${field('confirm','パスワードの確認','password','同じものをもう一度')}</div></div>${details()}${footer('back','review','確認へ')}`;
}

function summaryRow(label, value, button = '') {
  return `<div><dt>${label}</dt><dd>${escape(value)}${button}</dd></div>`;
}

function review() {
  const v = effective();
  return `<p class="eyebrow">STEP 3 / 3</p><h2 tabindex="-1">この内容で準備します</h2>${state.notice?`<div class="soft-note" role="status">${escape(state.notice)}</div>`:""}<p class="intro">「ダウンロードして準備」を押すと、表示中の版を取得してアプリと管理者を作成します。</p><dl class="review-list">${summaryRow('利用方法','このPCでの試用')}${summaryRow('導入する版',v.version||state.version)}${summaryRow('取得先','GitHubの検証済み配布版')}${summaryRow('管理者',v.name,'<button class="edit" data-action="edit-admin">変更</button>')}${summaryRow('ログインID',v.login)}${summaryRow('メール',v.email)}${summaryRow('パスワード','入力済み（内容は表示しません）')}</dl><details><summary>保存場所・導入の記録を見る</summary><dl class="review-list small">${summaryRow('保存場所',v.path,'<button class="edit" data-action="edit-path">変更</button>')}${summaryRow('接続ポート',v.port)}${summaryRow('作成理由',v.reason)}${summaryRow('実行者',v.actor)}${summaryRow('承認者',v.approver)}</dl><button class="link-button" data-action="edit-records">導入の記録を変更する</button></details><div class="soft-note">作成を行う人：<strong>${escape(v.actor)}</strong><br>内容を承認する人：<strong>${escape(v.approver)}</strong><br><small>入力はまだ確定していません。戻って修正できます。</small></div><p class="subtle">モックでは準備の進み方だけを再現します。実際のアカウントやファイルは作りません。</p>${footer('back','install','ダウンロードして準備')}`;
}

function installing() {
  return `<p class="eyebrow">自動セットアップの確認</p><h2 tabindex="-1">使えるように準備しています</h2><p class="intro">導入する版：${escape(state.version)}。この間のコマンド入力は不要です。</p><progress max="${tasks.length}" value="${state.progress}" aria-label="準備の進み具合"></progress><ul class="progress-items" aria-live="polite">${tasks.map((t,i)=>`<li class="${i<state.progress?'done':i===state.progress?'running':''}"><span class="status-dot">${i<state.progress?'✓':''}</span>${t}</li>`).join('')}</ul><p class="download-status" role="status">${state.progress===1?"ダウンロード中：32 MB / 約80 MB（模擬表示）":""}</p><div class="soft-note">これは数秒で進む模擬表示です。実際の所要時間を表すものではありません。</div>${footer(null,null,null)}`;
}

function failure() {
  const messages = {
    download: ['ダウンロードが中断されました', 'インターネット接続を確認してください。取得途中のファイルを片付け、同じ版を最初から取得し直します。'],
    integrity: ['配布ファイルを確認できませんでした', '取得したファイルが配布元の情報と一致しませんでした。ファイルを使わず停止しました。もう一度取得し直せます。'],
    failure: ['保存場所に書き込めません', '別の保存場所を選ぶか、フォルダーの権限を確認してからお試しください。'],
  };
  const [heading, message] = messages[state.scenario] || messages.failure;
  return `<p class="eyebrow">エラー時の案内</p><h2 tabindex="-1">準備を完了できませんでした</h2><div class="error-summary" role="alert"><strong>${heading}</strong><p>${message}</p></div><p class="intro">入力はこの画面を開いている間だけ保持します。アカウントはまだ作成していません。</p><dl class="review-list">${summaryRow('導入する版',state.version)}</dl><div class="buttons"><button class="quiet" data-action="cancel">いったん中断</button><button class="secondary" data-action="edit-path">保存場所を変更</button><button class="primary" data-action="retry">もう一度試す</button></div>`;
}

function complete() {
  const v = effective();
  return `<div class="success-mark" aria-hidden="true">✓</div><p class="eyebrow">セットアップ完了の表示例</p><h2 tabindex="-1">準備ができました</h2><p class="intro">次回からも「オープン保育ICT」のアイコンで起動する形にします。</p><dl class="review-list">${summaryRow('導入した版',state.existing?'2026.9.20（既存の版）':state.version)}${summaryRow('保存場所',v.path)}${summaryRow('ログインID',state.existing?'登録済みのログインID':v.login)}${summaryRow('接続先',`http://127.0.0.1:${v.port}`)}</dl><p><span class="status-pill ${state.running?'on':''}" role="status">${state.running?'起動中（模擬表示）':'停止中（模擬表示）'}</span></p><div class="soft-note">${state.running?'実装後は、この操作でブラウザーの職員ログイン画面を開きます。今は画面の流れだけを確認しています。':'架空の園児・家庭で操作を試してから、園内の端末や保護者との接続を準備します。'}</div><div class="buttons">${state.running?'<button class="secondary" data-action="stop">停止する</button>':''}<button class="primary" data-action="launch">${state.running?'画面を開く操作を試す':'起動して開く'}</button></div><p class="subtle">実際の起動・停止やページ移動は行いません。</p>`;
}

function cancelled() {
  return `<p class="eyebrow">中断の表示例</p><h2 tabindex="-1">ここで中断しました</h2><p class="intro">画面を開いている間は入力を残します。あとで再開する場合は、入力をやり直す案です。</p><div class="soft-note">このモックは、入力をファイルやブラウザーの保存領域へ記録していません。再読込すると消えます。</div><div class="buttons"><button class="primary" data-action="resume">入力した内容で続ける</button></div>`;
}

function render(focus = true) {
  const active = Number.isInteger(state.step) ? state.step : 3;
  steps.innerHTML = stageNames.map((name,i)=>`<li class="${i===active?'active':i<active?'done':''}" ${i===active?'aria-current="step"':''}><span>${i<active?'✓':i+1}</span>${name}</li>`).join('');
  panel.innerHTML = state.step===0 ? preparation() : state.step===1 ? admin() : state.step===2 ? review() : state.step==='installing' ? installing() : state.step==='failure' ? failure() : state.step==='cancelled' ? cancelled() : complete();
  if (focus) panel.querySelector('h2')?.focus({preventScroll:true});
}

function validate() {
  const v = effective();
  state.errors = {};
  if (!v.name.trim()) state.errors.name = '管理者の名前を入力してください。';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.email.trim())) state.errors.email = 'メールアドレスの形式を確認してください。';
  if (v.password.length < 8) state.errors.password = 'パスワードは8文字以上にしてください。';
  if (!v.confirm || v.password !== v.confirm) state.errors.confirm = '確認用パスワードを同じ内容で入力してください。';
  if (!v.reason.trim()) state.errors.reason = '作成理由を入力してください。';
  if (v.login.length > 255) state.errors.login = 'ログインIDを255文字以内で入力してください。';
  return Object.keys(state.errors).length === 0;
}

function validatePath() {
  state.errors = {};
  const v = state.values;
  if (!(os==='windows' ? /^[A-Za-z]:\\.+/.test(v.path) : /^\/.+/.test(v.path))) state.errors.path = '保存場所を絶対パスで指定してください。';
  if (!/^\d+$/.test(v.port) || Number(v.port)<1024 || Number(v.port)>65535) state.errors.port = '接続ポートは1024〜65535の整数で指定してください。';
  return Object.keys(state.errors).length === 0;
}

function start() {
  clearTimeout(timer);
  state.step = 'installing'; state.progress = 0; state.notice = '';
  render();
  function tick() {
    if (state.step !== 'installing') return;
    if (cancelDialog.open) { timer = setTimeout(tick, 400); return; }
    state.progress += 1;
    if ((state.fail && state.progress === 1) || (state.scenario==='download' && state.progress===2) || (state.scenario==='integrity' && state.progress===3)) { state.step='failure'; render(); return; }
    if (state.progress === tasks.length) { state.step='complete'; state.values.password=''; state.values.confirm=''; render(); return; }
    render(false);
    timer = setTimeout(tick, 700);
  }
  timer = setTimeout(tick, 700);
}

panel.addEventListener('input', event => {
  if (event.target.name && Object.hasOwn(state.values,event.target.name)) state.values[event.target.name] = event.target.value;
});

panel.addEventListener('click', event => {
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (!action) return;
  if (action==='cancel') {
    document.querySelector('#cancel-text').textContent = state.step==='installing' ? '処理の区切りで中断し、入力画面へ戻れるようにする案です。モックでは実際のファイルは作りません。' : '画面を開いている間は入力を残します。閉じる・再読込をすると入力は消えます。';
    cancelDialog.showModal(); return;
  }
  if (action==='check-release') { checkRelease(); return; }
  if (action==='to-admin') { if (state.release==='ready' && validatePath()) state.step=1; }
  if (action==='back') state.step=Math.max(0,state.step-1);
  if (action==='review') { if (validate()) state.step=2; }
  if (action==='edit-admin' || action==='edit-records') { state.step=1; state.errors={}; }
  if (action==='edit-path') { state.step=0; state.errors={}; }
  if (action==='install') { if (state.scenario==='changed' && !state.changed) {state.changed=true;state.version='2026.9.24';state.notice='新しい配布版が公開されました。導入する版を更新したので、内容を確認してからもう一度進めてください。';render();return;} if (!validatePath()) {state.step=0;render();return;} if (!validate()) {state.step=1;render();return;} start(); return; }
  if (action==='retry') { state.fail=false; state.scenario='filled'; start(); return; }
  if (action==='resume') { state.step=state.returnStep; if (state.release==='checking') {checkRelease();return;} }
  if (action==='separate') { state.existing=false; state.values.path += '-2'; checkRelease(); return; }
  if (action==='existing-launch') { state.step='complete'; state.running=true; }
  if (action==='launch') state.running=true;
  if (action==='stop') state.running=false;
  render();
  if (['edit-path','edit-records'].includes(action)) panel.querySelector('details').open=true;
  if (Object.keys(state.errors).length) panel.querySelector('[aria-invalid="true"]')?.focus();
});

document.querySelector('#keep-working').addEventListener('click',()=>cancelDialog.close());
document.querySelector('#confirm-cancel').addEventListener('click',()=>{
  clearTimeout(timer);
  state.returnStep=Number.isInteger(state.step)?state.step:2;
  state.step='cancelled'; cancelDialog.close(); render();
});
document.querySelector('#scenario').addEventListener('change',event=>reset(event.target.value));
document.querySelector('#os').addEventListener('change',event=>{
  os=event.target.value;
  reset(document.querySelector('#scenario').value);
});
window.addEventListener('pagehide',()=>{clearTimeout(timer);state.values.password='';state.values.confirm='';});
reset();
