'use strict';
// No setup is applied by these navigation actions. Explicit checks use the
// loopback API; only the mail-test action requests a test message.
function guidePosition(){return {netStep:s.netStep,tokenStep:s.tokenStep,mailStep:s.mailStep};}
function clearGuideSecrets(){s.mailDrafts={};if(s.networkStart)s.networkStart.dnsToken='';}
function captureNetworkStart(){if(!s.networkStart)s.networkStart=Object.fromEntries(networkKeys.map(k=>[k,s.v[k]]));}
function guideChanged(key){
  if(networkKeys.includes(key)){
    s.netOutcome=null;s.netDetails=null;delete s.checks.dns;
    if(['ip','subnet','adapter'].includes(key)){s.v.ipReserved=false;s.v.dnsReady=false;s.v.networkConfirmed=false;}
    if(['hostname','localHostname','tls'].includes(key))s.v.dnsReady=false;
    if(key==='hostname')s.v.domainReady=false;
    if(key==='tls'){s.tokenStep=0;s.v.domainReady=false;s.v.trustPlan=false;}
    for(const name of ['ipReserved','dnsReady','networkConfirmed','domainReady','trustPlan']){
      const field=document.getElementById(name);if(field)field.checked=s.v[name];
    }
  }
  if(mailKeys.includes(key)){
    s.mailError='';delete s.checks.mail;s.v.mailReceived=false;
    const result=document.getElementById('mail-result');if(result)result.replaceChildren();
    s.notice='';panel.querySelector(':scope > .result')?.remove();
  }
  if(key==='mailFrom'&&s.v.mailProvider==='gmail'){
    s.v.smtpUser=s.v.mailFrom.trim();s.v.smtpPassword='';s.v.googleReady=false;
  }
  if(key==='googleReady'&&!s.v.googleReady)s.v.smtpPassword='';
  const received=document.getElementById('mailReceived');
  if(received){received.checked=s.v.mailReceived;received.disabled=!s.checks.mail;}
  if(['hostname','localHostname'].includes(key)){
    const url=panel.querySelector('.url-display');if(url)url.textContent=selectedHost()?'https://'+selectedHost():'名前を入力すると表示します';
  }
}
function resumeGuide(draft){
  s.resumeDraft=draft;
  for(const [key,max] of [['netStep',7],['tokenStep',2],['mailStep',4]]){
    const n=draft.guide?.[key];s[key]=Number.isInteger(n)&&n>=0&&n<=max?n:0;
  }
  if(!s.v.mailProvider&&s.v.smtpHost)s.v.mailProvider='custom';
  if(s.v.mailProvider==='custom')s.mailStep=Math.min(1,s.mailStep);
  s.v.mailReceived=false;s.checks={};s.netOutcome=null;s.netDetails=null;
}
function mailSendStep(){s.mailStep=s.v.mailProvider==='gmail'?(s.v.smtpPassword?4:3):s.v.mailProvider==='custom'?1:0;}
function guideApplyReady(){
  if(!s.checks.pc){s.step=0;return fail('このPCの事前確認を、もう一度実行してください。');}
  if(!s.checks.dns){s.step=1;s.netStep=7;return fail('園内接続の準備を、もう一度確認してください。');}
  if(!s.checks.mail||!s.v.mailReceived){s.step=2;mailSendStep();return fail('確認メールの送信と受信を、もう一度確認してください。');}
  if(!s.checks.backup){s.step=3;return fail('バックアップの保存先を、もう一度確認してください。');}
  return true;
}
async function handleGuidedAction(action){
  if(action==='start-lan'&&!s.lanPending){
    s.flow='lan';s.step=s.resumeDraft?.flow==='lan'?Math.min(4,s.resumeDraft.step):0;
    s.resumeDraft=null;captureNetworkStart();return true;
  }
  if(action==='edit-lan-1')s.netStep=s.v.tls?4:3;
  if(action==='edit-lan-2')s.mailStep=s.v.mailProvider?1:0;
  if(action==='back'&&s.flow==='lan'&&s.step===3)s.mailStep=s.v.mailProvider==='gmail'?4:1;
  if(action==='next'&&s.flow==='lan'&&s.step===0)captureNetworkStart();
  if(['apply','retry'].includes(action)&&(action==='retry'?s.operation:s.flow)==='lan'){
    if(!guideApplyReady()){s.applying=false;s.failed=false;await saveDraft();return true;}
  }
  if(!action.startsWith('guide-')&&!action.startsWith('mail-'))return false;
  if(action==='guide-help'){showHelp();return true;}
  if(action==='mail-help'){mailHelp();return true;}
  if(action==='guide-cancel'){
    confirmDialog('この接続設定を取り消しますか？','このアプリ内の接続入力を開始時へ戻します。ルーターなどで手動変更した内容は元には戻りません。このPCの保育ICTとデータは保持します。','接続設定を取り消す',async()=>{
      if(s.networkStart)Object.assign(s.v,s.networkStart);
      s.netOutcome=null;s.netDetails=null;delete s.checks.dns;s.netStep=0;s.tokenStep=0;s.networkStart=null;
      s.flow='lan';s.step=0;await saveDraft();s.resumeDraft=null;s.flow='home';render();
    });return true;
  }
  if(action==='guide-back'){if(s.netStep>0)s.netStep--;else s.step=0;}
  if(action==='guide-next'){if(!validateGuideStep())return true;if(s.netStep===7)s.step=2;else s.netStep++;}
  if(/^guide-go-[0-7]$/.test(action))s.netStep=Number(action.slice(-1));
  if(action==='guide-detect'){
    s.notice='PCの接続情報を読み直しています…';render(false);
    const result=await api('server/check',{kind:'adapters',values:{}});
    s.adapters=result.adapters;delete s.checks.pc;delete s.checks.dns;s.netOutcome=null;s.netDetails=null;
    const adapter=selectedAdapter();
    if(!adapter.id)throw new Error('選択した接続が見つかりません。「戻る」でPC確認へ戻り、ネットワークを選び直してください。');
    change('ip',adapter.ip);change('subnet',adapter.subnet);s.notice=result.message;
  }
  if(action==='guide-token-next')s.tokenStep=Math.min(2,s.tokenStep+1);
  if(action==='guide-token-back')s.tokenStep=Math.max(0,s.tokenStep-1);
  if(action==='guide-check'){
    delete s.checks.dns;s.netOutcome=null;s.netDetails=null;
    if(!validGuideNetwork())return true;
    if(!s.v.networkConfirmed||!s.v.ipReserved){s.netStep=!s.v.networkConfirmed?1:2;fail('園の接続とIP予約の作業を、先に確認してください。');return true;}
    if(!s.v.tls){s.netStep=3;fail('アドレスの方式を選んでください。');return true;}
    s.notice='接続の準備を確認しています…';render(false);
    if(!s.checks.pc){await api('server/check',{kind:'pc',values:s.v});s.checks.pc=true;}
    const result=await api('server/check',{kind:'connection',values:s.v});
    s.netDetails=result.results;s.netOutcome=Object.fromEntries(Object.entries(result.results).map(([k,v])=>[k,v.passed]));
    s.checks.dns=result.complete;s.notice=result.message;
  }
  if(action==='mail-back'){if(s.mailStep>0)s.mailStep--;else{s.step=1;s.netStep=7;}}
  if(action==='mail-next'){
    const n=s.mailStep;
    if(n===0&&!s.v.mailProvider){fail('使うメールの種類を選んでください。');return true;}
    if(s.v.mailProvider==='gmail'){
      if(n===1&&!required(['mailFrom']))return true;
      if(n===2&&!s.v.googleReady){fail('送信元のGoogleアカウントで、2段階認証が有効か確認してください。');return true;}
      if(n===3&&!/^[A-Za-z0-9]{16}$/.test(s.v.smtpPassword.replace(/ /g,''))){fail('Googleで発行した16文字のアプリパスワードを入力してください。');return true;}
      if(n<4)s.mailStep++;
      else if(s.checks.mail&&s.v.mailReceived)s.step=3;
      else{fail('確認メールを送り、受信できたことを確認してください。');return true;}
    }else if(n===0)s.mailStep=1;
    else if(s.checks.mail&&s.v.mailReceived)s.step=3;
    else{fail('確認メールを送り、受信できたことを確認してください。');return true;}
  }
  if(action==='mail-same-recipient')change('testRecipient',s.v.mailFrom);
  if(action==='mail-fix-password'){s.mailStep=3;s.mailError='';}
  if(action==='mail-test'){
    delete s.checks.mail;s.v.mailReceived=false;s.mailError='';
    if(!validateMailInput())return true;
    s.notice='確認メールを1通送信しています…';render(false);
    try{const result=await api('server/check',{kind:'mail',values:s.v});s.checks.mail=true;s.notice=result.message;}
    catch(error){s.notice='';s.mailError=error.code==='smtp_auth_failed'?'auth':error.code==='smtp_connection_failed'?'connection':'';throw error;}
  }
  await saveDraft();return true;
}
