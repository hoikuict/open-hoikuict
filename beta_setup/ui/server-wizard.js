'use strict';
const panel=document.querySelector('#wizard'),dialog=document.querySelector('#dialog'),token=location.hash.slice(1);
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const names={local:['配布版','管理者','確認'],lan:['PC確認','園内接続','メール','バックアップ','確認','動作確認'],public:['公開先','接続準備','確認','園外確認']};
let timer,dialogAction,busy=false;
let s={flow:'home',step:0,netStep:0,tokenStep:0,mailStep:0,mailDrafts:{},mailError:'',netOutcome:null,netDetails:null,networkStart:null,resumeDraft:null,local:false,lan:false,public:false,lanPending:false,publicPending:false,trialRunning:false,
  v:{name:'',email:'',login:'',password:'',confirm:'',reason:'このPCでのβ版試用',actor:'',approver:'',path:'',port:'8001',
    facility:'',adapter:'',ip:'',subnet:'',ipReserved:false,tls:'',hostname:'',localHostname:'hoikuict.home.arpa',dnsToken:'',dnsReady:false,networkConfirmed:false,domainReady:false,trustPlan:false,
    smtpHost:'',smtpPort:'587',smtpUser:'',smtpPassword:'',mailFrom:'',testRecipient:'',mailReceived:false,mailProvider:'',googleReady:false,
    backupPath:'',backupTime:'02:00',retention:'30',noSleep:true,otherDevice:false,reboot:false,restore:false,trust:false,
    publicHostname:'',tunnelToken:'',externalDevice:false,externalMail:false,externalReady:false},
  adapters:[],checks:{},error:'',notice:'',paused:false,applying:false,failed:false,progress:0,operation:'',online:true,
  release:null,releaseError:'',checking:false,serverHealth:{},serverState:null};

async function api(path,values){
  const response=await fetch('/api/'+path,{method:values===undefined?'GET':'POST',cache:'no-store',
    headers:{Authorization:'Bearer '+token,...(values===undefined?{}:{'Content-Type':'application/json'})},
    ...(values===undefined?{}:{body:JSON.stringify(values)})});
  const data=await response.json();
  if(!response.ok||!data.ok){const e=new Error(data.message||'操作を完了できませんでした。');e.code=data.code;throw e;}
  return data;
}
function confirmDialog(title,message,label,action){document.querySelector('#dialog-title').textContent=title;document.querySelector('#dialog-message').textContent=message;document.querySelector('#dialog-confirm').textContent=label;dialogAction=action;dialog.showModal();}
function fail(message){s.error=message;render();return false;}
function required(keys){for(const key of keys){const e=document.getElementById(key);if(!String(s.v[key]||'').trim()||(e&&['email','time','number'].includes(e.type)&&!e.validity.valid)){fail((e?.closest('label')?.childNodes[0]?.textContent||'入力')+'を確認してください。');const field=document.getElementById(key);field?.setAttribute('aria-invalid','true');field?.closest('details')?.setAttribute('open','');return false;}}return true;}
function progressNames(){return s.operation==='local'?['保存先を確認','配布版をダウンロード','配布ファイルを検証','アプリを展開','データと設定を用意','管理者を作成','起動を確認']:s.operation==='lan'?['引継ぎ元と配布版を確認','サービス用のアプリを配置','データと認証鍵を引継ぎ','自動起動と保存権限を設定','HTTPS・バックアップを確認','園内からの接続を有効化']:s.operation==='stop-public'?['現在の接続を確認','園外接続を停止','園内の接続を確認','完了']:['現在の設定を退避','接続設定を切り替え','公開URLを確認','完了'];}
function applying(){const list=progressNames();return `<h2 tabindex="-1">${s.failed?'設定を完了できませんでした':'設定を進めています'}</h2><p class="intro" role="status">${esc(s.jobMessage||'準備しています')}</p><progress max="${list.length}" value="${s.progress}" aria-label="設定の進み具合"></progress><ul class="progress-items">${list.map((name,i)=>`<li class="${i<s.progress?'done':i===s.progress?s.failed?'failed':'running':''}"><span class="status-dot">${i<s.progress?'✓':i===s.progress&&s.failed?'!':''}</span>${name}</li>`).join('')}</ul>${s.recovery?note(esc(s.recovery)):''}${s.failed?`<div class="buttons">${button('edit-failed','入力に戻る','secondary')}${s.blocked?'':button('retry','もう一度試す')}</div>`:`<p class="subtle">管理者許可、ダウンロード、証明書発行に時間がかかる場合があります。</p><div class="buttons">${button('pause','いったん中断','secondary')}</div>`}`;}
function render(focus=true){
  panel.classList.toggle('guided',s.flow==='lan'&&[1,2].includes(s.step)&&!s.paused&&!s.applying);
  steps();
  const alerts=(s.error?`<div class="error-summary" role="alert" tabindex="-1">${esc(s.error)}</div>`:'')+(s.notice?`<div class="result" role="status">${esc(s.notice)}</div>`:'');
  let content=s.flow==='home'?home():s.flow==='local'?localPage():s.flow==='lan'?lanPage():publicPage();
  if(s.flow==='local'&&s.step===0&&!s.release)content=`<h2 tabindex="-1">配布版を確認します</h2><p class="intro">${s.checking?'GitHubの配布版を確認しています…':esc(s.releaseError||'配布情報の確認が必要です。')}</p>${s.checking?'':button('check-release','もう一度確認','secondary')}<div class="buttons">${button('back','導入ホームへ','secondary')}</div>`;
  if(s.applying)content=applying();
  if(s.paused)content=`<h2 tabindex="-1">中断しました</h2><p class="intro">入力内容はこの画面内に保持しています。${s.flow==='local'?'画面を閉じた場合は再入力してください。':'秘密情報を除いた下書きは、このPCに保存します。'}</p>${note(s.lan||s.lanPending?'園内のサーバーは動き続けています。':'このPCへの導入状態を保持しています。')}<div class="buttons">${button('resume','設定を再開する')}</div>`;
  panel.innerHTML=alerts+(s.openUrl?`<p><a href="${esc(s.openUrl)}" target="_blank" rel="noopener noreferrer">ログイン画面を開く</a></p>`:'')+`<form id="setup-form" novalidate>${content}</form>`;
  const received=document.getElementById('mailReceived');if(received)received.disabled=!s.checks.mail;
  if(busy)panel.querySelectorAll('button,input,select,textarea').forEach(b=>b.disabled=true);
  document.querySelector('#exit').disabled=busy;
  if(focus){panel.querySelector(s.error?'.error-summary':'h2')?.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
}
async function loadRelease(){s.checking=true;s.releaseError='';render(false);try{s.release=s.online?await api('release'):{version:'同梱版',notes:'同梱されている配布版を導入します。',size:0};}catch(e){s.releaseError=e.message;s.release=null;}finally{s.checking=false;render(false);}}
function serverState(result){
  s.serverState=result.state;s.serverHealth=result.health||{};
  const state=result.state;if(!state)return;
  s.local=true;s.version=state.version;s.lan=!!state.lan_confirmed;s.lanPending=!s.lan;
  s.public=!!state.public&&!!state.public_confirmed;s.publicPending=!!state.public&&!s.public;
  s.v={...s.v,...state.lan,...(state.public||{})};s.ports=result.ports||s.ports;
  if(s.serverHealth.drill?.state==='complete')s.checks.restore=true;
}
async function saveDraft(){if(s.local&&['lan','public'].includes(s.flow)&&!s.lanPending&&!s.publicPending)await api('server/draft',{flow:s.flow,step:s.step,values:s.v,guide:guidePosition()});}
async function poll(){
  try{
    if(s.operation==='local'){
      const status=await api('status');s.progress=status.progress||0;s.jobMessage=status.message;
      if(status.state==='complete'){s.local=true;s.trialRunning=status.running;s.version=status.version;s.v.login=status.login;s.v.path=status.path;s.v.password='';s.v.confirm='';s.applying=false;s.flow='home';s.step=0;s.notice='このPCへの導入が完了しました。架空データで確認した後、園内LANの設定へ進めます。';}
      else if(['error','cancelled'].includes(status.state)){s.failed=true;s.error=status.message;s.recovery=status.cleanup_path?'作成途中の保存先：'+status.cleanup_path:'既存の環境は上書きしていません。';}
    }else{
      const result=await api('server/status');serverState(result);s.ports=result.ports;
      const job=result.job;s.progress=job.progress||0;s.jobMessage=job.message;
      if(job.state==='complete'){s.applying=false;s.failed=false;s.error='';s.v.dnsToken='';s.v.smtpPassword='';s.v.tunnelToken='';clearGuideSecrets();
        if(s.operation==='lan'){s.flow='lan';s.step=5;}else if(s.operation==='public'){s.flow='public';s.step=3;}
        else{s.flow='home';s.step=0;s.notice=job.message;}
      }else if(['error','blocked','cancelled'].includes(job.state)){s.failed=true;s.blocked=job.state==='blocked';s.error=job.message;s.recovery=job.recovery||'';}
    }
    render(!s.applying);if(s.applying&&!s.failed)timer=setTimeout(poll,800);
  }catch(e){s.applying=true;s.failed=true;s.blocked=true;s.error=e.message;s.recovery='実行中の設定がある可能性があります。アプリを開き直して導入状態を確認してください。';render();}
}
async function apply(operation){
  s.operation=operation;s.recovery='';s.blocked=false;
  if(operation==='local')await api('install',{...effective(),release_revision:s.release?.revision});
  else await api('server/apply',{operation,values:s.v});
  s.applying=true;s.failed=false;s.progress=0;s.jobMessage='準備しています';render();timer=setTimeout(poll,300);
}
async function validateStep(){
  if(s.flow==='local'){
    if(s.step===0){const result=await api('preflight',{path:s.v.path,port:s.v.port});if(result.existing){serverState(await api('select',{path:s.v.path}));s.local=true;s.v.login=result.login;s.v.port=String(result.port);s.flow='home';s.step=0;s.notice='この場所には導入済みの環境があります。既存の環境を使います。';return false;}}
    if(s.step===1){if(!required(['name','email','password','confirm','reason']))return false;if(s.v.password.length<8||s.v.password.length>128||s.v.password!==s.v.confirm)return fail('パスワードを8〜128文字にし、確認欄に同じ内容を入力してください。');}
  }
  if(s.flow==='lan'){
    if(s.step===0&&!s.checks.pc)return fail('このPCの事前確認を実行してください。');
    if(s.step===1&&!s.checks.dns)return fail('園内URLとHTTPSの事前確認を実行してください。');
    if(s.step===2&&(!s.checks.mail||!s.v.mailReceived))return fail('確認メールの送信と受信を確認してください。');
    if(s.step===3&&(!s.checks.backup||!required(['backupTime'])))return fail('バックアップの保存先と時刻を確認してください。');
  }
  if(s.flow==='public'){if(s.step===0&&!required(['publicHostname']))return false;if(s.step===1&&!s.checks.tunnel)return fail('園外接続の準備を確認してください。');}
  return true;
}
function change(key,value){
  if(s.v[key]===value)return;
  if(key==='mailProvider'){setMailProvider(value);return;}
  s.v[key]=value;
  const checks={pc:['facility','adapter'],dns:['adapter','ip','subnet','ipReserved','tls','hostname','localHostname','dnsToken','dnsReady'],mail:['smtpHost','smtpPort','smtpUser','smtpPassword','mailFrom','testRecipient'],backup:['backupPath'],tunnel:['publicHostname','tunnelToken']};
  for(const [kind,keys] of Object.entries(checks))if(keys.includes(key)){delete s.checks[kind];if(kind==='mail')s.v.mailReceived=false;}
  guideChanged(key);
}
panel.addEventListener('submit',e=>e.preventDefault());
panel.addEventListener('input',e=>{if(e.target.name&&Object.hasOwn(s.v,e.target.name))change(e.target.name,e.target.type==='checkbox'?e.target.checked:e.target.value);});
panel.addEventListener('change',e=>{if(e.target.name&&Object.hasOwn(s.v,e.target.name)){change(e.target.name,e.target.type==='checkbox'?e.target.checked:e.target.value);if(e.target.tagName==='SELECT'||e.target.type==='radio'){if(e.target.name==='adapter'){const a=s.adapters.find(a=>a.id===s.v.adapter);if(a){change('ip',a.ip);change('subnet',a.subnet);}}render(false);}}});
panel.addEventListener('click',async event=>{
  const control=event.target.closest('[data-action]');if(!control||control.disabled||busy)return;
  const a=control.dataset.action;s.error='';s.notice='';
  if(a==='pause'){confirmDialog('いったん中断しますか？',s.applying?'処理の区切りで中断し、今回の設定を戻します。':'入力と手順を保持して中断します。秘密情報は、画面を閉じると再入力が必要です。ルーターなどで手動変更した設定は元には戻りません。','中断する',async()=>{if(s.applying){await api(s.operation==='local'?'cancel':'server/cancel',{});}else{await saveDraft();s.paused=true;render();}});return;}
  if(a==='stop-public'){confirmDialog('園外からの利用を停止しますか？','園外からの接続と、公開URLを使う登録・再設定メールを停止します。切替中はサーバーを短時間再起動し、園内運用を再開します。','園外からの利用を停止',()=>apply('stop-public'));return;}
  busy=true;
  try{
    if(await handleGuidedAction(a))return;
    if(a==='start-local'){s.flow='local';s.step=0;if(!s.release)await loadRelease();}
    else if(a==='start-lan'){s.flow='lan';s.step=s.lanPending?5:0;}
    else if(a==='start-public'){s.flow='public';s.step=s.publicPending?3:0;if(s.v.tls==='domain')s.v.publicHostname=s.v.hostname;}
    else if(a==='back'){if(s.step===5&&s.flow==='lan'){s.flow='home';s.step=0;}else if(s.step)s.step--;else s.flow='home';await saveDraft();}
    else if(a==='resume')s.paused=false;
    else if(a==='check-release')await loadRelease();
    else if(a==='next'){if(await validateStep()){s.step++;await saveDraft();}}
    else if(a.startsWith('edit-')&&a!=='edit-failed'){const [,flow,step]=a.split('-');s.flow=flow;s.step=Number(step);}
    else if(a==='edit-failed'){s.applying=false;s.failed=false;s.step=s.flow==='public'?1:0;}
    else if(a==='apply'||a==='retry')await apply(a==='retry'?s.operation:s.flow);
    else if(['check-pc','check-dns','check-mail','check-backup','check-tunnel'].includes(a)){
      const kind=a.slice(6);delete s.checks[kind];s.notice='確認しています…';render(false);
      const result=await api('server/check',{kind,values:s.v});s.checks[kind]=true;s.notice=result.message;
    }
    else if(a==='check-restore'){await api('server/drill',{});s.notice='バックアップと別の場所への復元を確認しています。';await pollDrill();}
    else if(a==='finish-lan'||a==='finish-public'){await api('server/confirm',{...s.v,phase:a==='finish-lan'?'lan':'public'});serverState(await api('server/status'));s.flow='home';s.step=0;s.notice='利用確認を完了しました。';}
    else if(a==='open-app'){const result=await api('launch',{path:s.v.path});s.trialRunning=true;window.open(result.url,'_blank','noopener');s.openUrl=result.url;s.notice='ログイン画面を開きました。開かない場合は、下のリンクを使ってください。';}
    else if(a==='stop-local'){await api('stop',{});s.trialRunning=false;s.notice='このPCの試用アプリを停止しました。データは保持しています。';}
    else if(a==='lan-details')s.notice='園内URL：'+reviewURL()+' ／ バックアップ：'+s.v.backupPath+' ／ 毎日 '+s.v.backupTime;
    else if(a==='public-details')s.notice='公開URL：https://'+s.v.publicHostname+' ／ 停止しても園内接続とデータを保持します。';
    else if(a==='certificate'){
      const response=await fetch('/api/server/certificate',{headers:{Authorization:'Bearer '+token}});
      if(!response.ok)throw new Error('園内証明書を取得できませんでした。');
      const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='OpenHoikuICT-LAN-root.crt';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    }
  }catch(e){s.notice='';s.error=e.message;if(e.code==='release_changed'){s.step=2;await loadRelease();}}
  finally{busy=false;render();}
});
async function pollDrill(){const result=await api('server/status');serverState(result);const drill=result.health?.drill;if(drill?.state==='complete'){s.checks.restore=true;s.notice=drill.message;render();}else if(drill?.state==='failed'){s.error=drill.message;render();}else timer=setTimeout(()=>pollDrill().catch(e=>fail(e.message)),1000);}
document.querySelector('#dialog-back').addEventListener('click',()=>dialog.close());
document.querySelector('#help-close').addEventListener('click',()=>document.querySelector('#help-dialog').close());
document.querySelector('#dialog-confirm').addEventListener('click',async()=>{dialog.close();try{await dialogAction?.();}catch(e){s.error=e.message;render();}dialogAction=null;});
document.querySelector('#exit').addEventListener('click',()=>confirmDialog('導入アプリを終了しますか？',s.applying?'設定中です。いったん中断してから終了してください。':s.lan||s.lanPending?'園内サーバーは動き続けます。入力中の秘密情報は保存しません。':'このPCの試用アプリを停止して終了します。','終了する',async()=>{if(s.applying)throw new Error('設定処理を中断してから終了してください。');await saveDraft();await api('exit',{});clearTimeout(timer);s.v.password=s.v.confirm=s.v.dnsToken=s.v.smtpPassword=s.v.tunnelToken='';clearGuideSecrets();panel.innerHTML='<h2>終了しました</h2><p>この画面を閉じてください。</p>';}));
(async()=>{
  try{
    if(!token)throw new Error('導入アプリのアイコンから開いてください。');
    const info=await api('info');s.v.path=info.path;s.online=info.online;s.local=!!info.existing;s.error=info.problem||'';s.trialRunning=info.status.running;
    if(info.existing){s.v.port=String(info.existing.port);s.v.login=info.existing.login;s.version=info.existing.version;}
    const server=await api('server/info');serverState(server);s.adapters=server.adapters;s.ports=server.ports;
    if(!server.state&&server.draft?.values){s.v={...s.v,...server.draft.values};resumeGuide(server.draft);if(Object.keys(server.draft.values).length)s.notice='下書きを読み込みました。園内LANの設定を開くと続きから再開します。秘密情報と接続確認は、もう一度入力・実行してください。';}
    if(!s.v.adapter&&s.adapters.length){const a=s.adapters.find(a=>a.private)||s.adapters[0];s.v.adapter=a.id;s.v.ip=a.ip;s.v.subnet=a.subnet;}
    if(server.job?.state==='running'||server.job?.state==='blocked'){s.operation=server.job.operation|| (server.state?'public':'lan');s.flow=s.operation==='stop-public'?'public':s.operation;s.applying=true;timer=setTimeout(poll,100);}
    if(info.status.state==='installing'){s.operation='local';s.flow='local';s.applying=true;timer=setTimeout(poll,100);}
    render();
  }catch(e){s.error=e.message;render();}
})();
