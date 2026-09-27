'use strict';
const token = location.hash.slice(1);
const panel = document.querySelector('#wizard');
let timer, busy = false;
let state = {step:0, os:'', existing:false, online:true, release:null, releaseError:null, checking:false, error:'', status:{}, values:{name:'',email:'',login:'',password:'',confirm:'',reason:'このPCでのβ版試用',actor:'',approver:'',path:'',port:'8001'}};
const esc = x => String(x ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function api(path, values) {
  const response = await fetch('/api/'+path,{method:values===undefined?'GET':'POST',cache:'no-store',headers:{Authorization:'Bearer '+token,...(values===undefined?{}:{'Content-Type':'application/json'})},...(values===undefined?{}:{body:JSON.stringify(values)})});
  const data = await response.json();
  if (!response.ok || !data.ok) {const error=new Error(data.message || '操作を完了できませんでした。');error.code=data.code;throw error;}
  return data;
}

async function loadRelease() {
  state.checking=true;state.release=null;state.releaseError=null;render(false);
  try {state.release=await api('release');}
  catch(error){state.releaseError={message:error.message,code:error.code};}
  finally{state.checking=false;render(false);}
}
function releaseBox() {
  if(!state.online)return '<div class="release-box">同梱されている配布版を導入します。</div>';
  if(state.checking)return '<div class="release-box" role="status">GitHubの配布版を確認しています…</div>';
  if(state.releaseError)return `<div class="error-summary" role="alert"><strong>${esc(state.releaseError.message)}</strong><div class="buttons">${button('check-release','もう一度確認','secondary')}${state.releaseError.code==='installer_outdated'?'<a href="https://github.com/hoikuict/open-hoikuict/releases" target="_blank" rel="noopener noreferrer">公式配布ページを開く</a>':''}</div></div>`;
  if(!state.release)return `<div class="release-box">${button('check-release','最新版を確認する','secondary')}</div>`;
  const r=state.release;
  return `<div class="release-box"><div class="release-heading"><strong>導入する版</strong><span class="badge">検証済み</span></div><div class="release-version">${esc(r.version)}</div><p>Windows 11 x64 ・ ダウンロード 約${Math.ceil(r.size/1048576)} MB<br>配布元：GitHub / hoikuict/open-hoikuict</p>${r.notes?`<details><summary>この版の変更内容</summary><p class="release-notes">${esc(r.notes)}</p></details>`:''}</div>`;
}

function effective() {
  const v=state.values;
  return {...v,login:v.login.trim()||v.email.trim(),actor:v.actor.trim()||v.name.trim(),approver:v.approver.trim()||v.name.trim()};
}
function input(key,label,type='text',note='',optional=false) {
  const max=({path:1024,name:100,password:128,confirm:128,port:5})[key]||255;
  return `<label for="${key}">${label}${note?`<span id="${key}-hint">${note}</span>`:''}<input id="${key}" name="${key}" type="${type}" value="${esc(state.values[key])}" maxlength="${max}" autocomplete="${type==='password'?'new-password':'off'}" ${optional?'':'required'} ${note?`aria-describedby="${key}-hint"`:''}></label>`;
}
function button(action,label,kind='primary') {return `<button type="button" class="${kind}" data-action="${action}" ${['next','install'].includes(action)&&state.online&&(!state.release||state.checking)?'disabled':''}>${label}</button>`;}
function footer(back,next,label) {return `<div class="buttons">${button('cancel','いったん中断','quiet')}${back?button('back','戻る','secondary'):''}${next?button(next,label):''}</div>`;}
function row(label,value,edit='') {return `<div><dt>${label}</dt><dd>${esc(value)}${edit?button(edit,'変更','edit'):''}</dd></div>`;}
function error() {return state.error?`<div class="error-summary" role="alert">${esc(state.error)}</div>`:'';}
function title(step,title,description) {return `<p class="eyebrow">STEP ${step} / 3</p><h2 tabindex="-1">${title}</h2><p class="intro">${description}</p>`;}

function prepare() {
  if(state.existing) return `${title(1,'すでに準備されています','初期設定を繰り返さず、保存済みの環境を起動できます。')}<dl class="review-list">${row('保存場所',state.values.path)}${row('導入済みの版',state.status.version||'既存の版')}${row('ログインID',state.values.login)}</dl><div class="buttons">${button('separate','別の場所で試す','secondary')}${button('launch','起動して開く')}</div>`;
  return `${title(1,'最新版で試用をはじめます','検証済みの配布版をGitHubから取得します。必要なソフトも一緒に用意するので、個別の導入は不要です。')}${releaseBox()}<ul class="check-list"><li><span class="check">✓</span><div>このPCだけで試用<small>まずは架空の園児・家庭でお試しください。</small></div></li><li><span class="check">✓</span><div>次回からは同じアイコンで起動<small>導入済みの版を使い、毎回ダウンロードしません。</small></div></li></ul><details ${state.error?'open':''}><summary>保存場所などを変更する</summary><p>既存のファイルがある場所には導入しません。通常は変更不要です。</p><div class="fields">${input('path','保存場所')}${input('port','接続ポート')}</div></details>${footer(false,'next','次へ')}`;
}
function administrator() {
  return `${title(2,'管理者を決めましょう','このPCで試すための管理者アカウントを作成します。')}<form id="admin-form"><div class="fields">${input('name','管理者の名前')}${input('email','メールアドレス','email','ログインIDとして使います。試用中はメールを送りません。')}<div class="two-col">${input('password','パスワード','password','8〜128文字。氏名やIDを含めないでください。')}${input('confirm','パスワードの確認','password','同じものをもう一度')}</div></div><details><summary>ログインID・導入の記録を変更する</summary><p>このPCで本人が試す場合、実行者・承認者は管理者本人を既定値にします。別の担当者がいる場合は変更してください。</p><div class="fields">${input('login','ログインID','text','未入力ならメールアドレスを使います。',true)}${input('reason','作成理由')}${input('actor','実行者','text','未入力なら管理者の名前を使います。',true)}${input('approver','承認者','text','未入力なら管理者の名前を使います。',true)}</div></details></form>${footer(true,'review','確認へ')}`;
}
function review() {
  const v=effective();
  return `${title(3,'この内容で準備します','「ダウンロードして準備」を押すと、表示中の版を取得してアプリと管理者を作成します。')}<dl class="review-list">${row('利用方法','このPCでの試用')}${row('導入する版',state.release?.version||'同梱版')}${row('取得先',state.online?'GitHubの検証済み配布版':'同梱ファイル')}${row('管理者',v.name,'edit-admin')}${row('ログインID',v.login)}${row('メール',v.email)}${row('パスワード','入力済み（内容は表示しません）')}</dl><details><summary>保存場所・導入の記録を見る</summary><dl class="review-list small">${row('保存場所',v.path,'edit-path')}${row('接続ポート',v.port)}${row('作成理由',v.reason)}${row('実行者',v.actor)}${row('承認者',v.approver)}</dl></details><div class="soft-note">作成を行う人：<strong>${esc(v.actor)}</strong><br>内容を承認する人：<strong>${esc(v.approver)}</strong><br>アカウントは、まだ作成していません。</div>${state.online&&state.releaseError?releaseBox():''}${footer(true,'install','ダウンロードして準備')}`;
}
function progress() {
  const names=['保存先と配布版を確認',state.online?'GitHubからダウンロード':'同梱ファイルを準備','配布ファイルを確認','アプリと必要なソフトを準備','データと設定を用意','管理者アカウントを作成','起動を確認'];
  const p=state.status.progress||0;
  return `<h2 tabindex="-1">使えるように準備しています</h2><p class="intro" role="status">${esc(state.status.message||'準備を開始しています')}</p><progress max="7" value="${p}" aria-label="準備の進み具合"></progress><ul class="progress-items">${names.map((name,i)=>`<li class="${i<p?'done':i===p?'running':''}"><span class="status-dot">${i<p?'✓':''}</span>${name}</li>`).join('')}</ul><p class="download-status" role="status">${p===1&&state.status.total?`${Math.floor((state.status.received||0)/1048576)} MB / 約${Math.ceil(state.status.total/1048576)} MB`:""}</p><p class="subtle">ダウンロードと展開のため、接続やPCによって数分かかる場合があります。</p>${footer(false,null,null)}`;
}
function complete() {
  return `<div class="success-mark" aria-hidden="true">✓</div><h2 tabindex="-1">準備ができました</h2><p class="intro">次回からは、保存先にある「OpenHoikuICT」を開いてください。</p><dl class="review-list">${row('導入した版',state.status.version||'既存の版')}${row('ログインID',state.status.login||effective().login)}${row('保存場所',state.values.path)}</dl><p><span class="status-pill ${state.status.running?'on':''}" role="status">${state.status.running?'起動中':'停止中'}</span></p><div class="soft-note">職員ログイン画面で、設定したIDとパスワードを入力してください。</div><div class="buttons">${state.status.running?button('stop','停止する','secondary'):''}${button('launch',state.status.running?'ログイン画面を開く':'起動して開く')}</div>${state.appUrl?`<p class="subtle"><a href="${esc(state.appUrl)}" target="_blank" rel="noopener noreferrer">ログイン画面が開かない場合はこちら</a></p>`:''}<p class="subtle">園内の他端末や保護者から使うための接続設定は、この試用版には含まれません。</p>`;
}
function failure() {
  return `<h2 tabindex="-1">準備を完了できませんでした</h2><p class="intro">入力を確認してやり直せます。既存の環境は上書きしていません。</p>${state.status.cleanup_path?`<div class="soft-note">作成途中のフォルダーが残っています。<br><code>${esc(state.status.cleanup_path)}</code><br>この場所を新しい導入先に指定しないでください。</div>`:''}<div class="buttons">${button('edit-path','保存場所を変更','secondary')}${button('edit-admin','入力を確認する','secondary')}${button('install','もう一度試す')}</div>`;
}
function render(focus=true) {
  const step=Number.isInteger(state.step)?state.step:3;
  document.querySelector('#steps').innerHTML=['準備','管理者','確認'].map((name,i)=>`<li class="${i===step?'active':i<step?'done':''}" ${i===step?'aria-current="step"':''}><span>${i<step?'✓':i+1}</span>${name}</li>`).join('');
  panel.innerHTML=error()+(state.step===0?prepare():state.step===1?administrator():state.step===2?review():state.step==='installing'?progress():state.step==='complete'?complete():state.step==='cancelled'?`<h2 tabindex="-1">中断しました</h2><p class="intro">入力した内容は、この画面を開いている間だけ残ります。</p>${button('resume','入力した内容で続ける')}`:failure());
  if(focus) panel.querySelector('h2')?.focus({preventScroll:true});
}
async function poll() {
  try {
    state.status=await api('status');
    if(state.status.state==='complete') {state.step='complete';state.values.path=state.status.path;state.values.password='';state.values.confirm='';state.error='';}
    else if(state.status.state==='error') {state.step='error';state.error=state.status.message;}
    else if(state.status.state==='cancelled') {state.step='cancelled';state.error=state.status.cleanup_path?state.status.message:'';}
    render(false);
    if(state.status.state==='installing') timer=setTimeout(poll,400);
  } catch {state.error='導入アプリとの接続が切れました。アイコンから開き直し、導入済みか確認してください。';state.step='error';render();}
}

panel.addEventListener('input',event=>{if(event.target.name&&Object.hasOwn(state.values,event.target.name))state.values[event.target.name]=event.target.value;});
panel.addEventListener('submit',event=>event.preventDefault());
panel.addEventListener('click',async event=>{
  const control=event.target.closest('[data-action]');
  if(!control||busy||state.checking)return;
  const action=control.dataset.action;
  if(action==='cancel'){document.querySelector('#cancel-dialog').showModal();return;}
  if(action==='back'){state.step=Math.max(0,state.step-1);state.error='';render();return;}
  if(action==='edit-admin'||action==='edit-path'){state.step=action==='edit-admin'?1:0;state.error='';render();if(action==='edit-path')panel.querySelector('details')?.setAttribute('open','');return;}
  if(action==='resume'){state.step=state.values.password?2:1;state.error='';render();return;}
  if(action==='separate'){state.existing=false;state.values.path+='-2';state.values.name='';state.values.email='';state.values.login='';state.step=0;if(state.online)await loadRelease();else render();return;}
  if(action==='check-release'){await loadRelease();return;}
  if(action==='review'&&!document.querySelector('#admin-form').reportValidity())return;
  busy=true;control.disabled=true;state.error='';
  let opened;
  try {
    if(action==='next'){
      const result=await api('preflight',{path:state.values.path,port:state.values.port});
      state.existing=result.existing;
      if(result.existing){state.values.port=String(result.port);state.values.login=result.login;}else state.step=1;
    }
    if(action==='review'){
      if(state.values.password.length<8||state.values.password!==state.values.confirm)throw new Error('パスワードを8文字以上にし、確認欄に同じ内容を入力してください。');
      state.step=2;
    }
    if(action==='install'){
      await api('install',{...effective(),release_revision:state.release?.revision});state.step='installing';state.status={progress:0};render();timer=setTimeout(poll,100);
    }
    if(action==='launch'){
      opened=window.open('about:blank','_blank');if(opened)opened.opener=null;
      const result=await api('launch',{path:state.values.path});
      state.status=await api('status');state.step='complete';state.appUrl=result.url;
      if(opened)opened.location.href=result.url;
    }
    if(action==='stop'){await api('stop',{});state.status=await api('status');}
  }catch(error){if(opened)opened.close();if(error.code==='release_changed'){state.step=2;await loadRelease();}state.error=error.message;}
  finally{busy=false;render();}
});
document.querySelector('#keep-working').addEventListener('click',()=>document.querySelector('#cancel-dialog').close());
document.querySelector('#confirm-cancel').addEventListener('click',async()=>{
  document.querySelector('#cancel-dialog').close();
  try{if(state.step==='installing'){await api('cancel',{});state.status.message='処理の区切りまで待って中断しています';}else state.step='cancelled';render();}catch(error){state.error=error.message;render();}
});
document.querySelector('#exit').addEventListener('click',()=>document.querySelector('#exit-dialog').showModal());
document.querySelector('#keep-open').addEventListener('click',()=>document.querySelector('#exit-dialog').close());
document.querySelector('#confirm-exit').addEventListener('click',async()=>{
  document.querySelector('#exit-dialog').close();clearTimeout(timer);
  try{await api('exit',{});state.values.password='';state.values.confirm='';panel.innerHTML='<h2>終了しています</h2><p class="intro">実行中の処理を停止します。このページを閉じてください。</p>';document.querySelector('#exit').disabled=true;}catch(error){state.error=error.message;render();}
});
(async()=>{
  try{
    if(!token)throw new Error('導入アプリのアイコンからこの画面を開いてください。');
    const info=await api('info');state.values.path=info.path;state.os=info.platform==='win32'?'Windows 11':'Ubuntu 24.04 LTS';state.status=info.status;state.error=info.problem;state.existing=!!info.existing;state.online=info.online;
    if(info.existing){state.values.port=String(info.existing.port);state.values.login=info.existing.login;state.status.version=info.existing.version||'既存の版';}
    if(info.status.state==='installing'){state.step='installing';timer=setTimeout(poll,200);}
    else if(info.status.state==='complete'){state.step='complete';state.values.login=info.status.login;}
    render();
    if(state.online&&!info.existing&&info.status.state!=='installing'&&info.status.state!=='complete')await loadRelease();
  }catch(error){panel.innerHTML=`<h2>画面を開き直してください</h2><p class="intro">${esc(error.message)}</p>`;}
})();
