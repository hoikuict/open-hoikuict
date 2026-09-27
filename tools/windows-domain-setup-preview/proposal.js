'use strict';
// Deployed v5 templates/actions, with a disconnected in-memory API and the
// proposed domain flow. There is no network, persistent storage or OS access.
const originalState=structuredClone(s),oldGuidePage=guidePage,oldCertificate=certificateGuide,
  oldValidateGuide=validateGuideStep,oldReadiness=readinessGuide,oldLanPage=lanPage,oldPublicPage=publicPage;
const fixture=document.querySelector('#fixture'),fault=document.querySelector('#fault');
let mockJob=0,migrating=false,mockConfirmed={};
const oldProgressNames=progressNames;
const oldShowHelp=showHelp;
showHelp=function(){
  if(s.v.tls!=='domain')return oldShowHelp();
  document.querySelector('#help-title').textContent='ドメイン・ネットワーク担当者への相談内容';
  document.querySelector('#help-text').value=[
    '保育ICTの園用ドメイン方式について相談します（モックの架空データです）。',
    `園内名：${s.v.hostname||'未定'} / IP：${s.v.ip} / 園内範囲：${s.v.subnet}`,
    '園専用のCloudflareゾーンと、Zone Read・DNS Editに限定したトークンを準備してください。',
    'アプリが確定時にAレコードをDNS onlyで登録し、DNS-01で証明書を取得します。',
    'PCのIP予約、職員用LANの端末間通信、園内DNSが私設IPの応答を許可するかを確認したいです。',
    '園外公開は別名で後から設定します。秘密のトークンやパスワードはこの文面に含めません。'
  ].join('\n');
  document.querySelector('#help-dialog').showModal();
};
progressNames=function(){return s.operation==='lan'&&s.v.tls==='domain'?['引継ぎ元と配布版を確認','設定・データの退避','園内名をDNSへ登録','園内DNSで名前を確認','HTTPS・バックアップを確認','園内からの接続を有効化']:oldProgressNames();};
const sample={facility:'さくら保育園（架空）',adapter:'8',ip:'192.168.10.20',subnet:'192.168.10.0/24',networkConfirmed:true,ipReserved:true,tls:'domain',hostname:'lan.sakura.example',localHostname:'hoikuict.home.arpa',domainReady:true,dnsToken:'DEMO-DNS-TOKEN',dnsReady:true,trustPlan:false,mailProvider:'gmail',smtpHost:'smtp.gmail.com',smtpPort:'587',smtpUser:'demo@sakura.example',smtpPassword:'demodemodemodemo',mailFrom:'demo@sakura.example',testRecipient:'admin@sakura.example',googleReady:true,mailReceived:true,backupPath:'E:\\HoikuICT-Backup',backupTime:'02:00',retention:'30',noSleep:true,publicHostname:'app.sakura.example',tunnelToken:'DEMO-TUNNEL-TOKEN'};
function resetProposal(mode){
  clearTimeout(timer);busy=false;mockJob=0;mockConfirmed={};migrating=mode==='migration';s=structuredClone(originalState);
  s.local=true;s.version='v2026.9.23.5';s.v={...s.v,...sample,path:'C:\\HoikuICT',login:'admin@sakura.example'};
  s.adapters=[{id:'8',name:'イーサネット（架空）',ip:sample.ip,subnet:sample.subnet,private:true,pcName:'SAKURA-SERVER',mac:'02-00-00-00-00-20',gateway:'192.168.10.1'}];
  s.ports={tunnel:22002};s.flow='lan';s.step=1;s.netStep=3;s.tokenStep=0;
  if(mode==='empty'){for(const k of ['facility','hostname','dnsToken','smtpUser','smtpPassword','mailFrom','testRecipient','backupPath'])s.v[k]='';for(const k of ['networkConfirmed','ipReserved','domainReady','dnsReady','mailReceived'])s.v[k]=false;s.netStep=0;}
  if(mode==='partial'){s.v.dnsToken='';s.v.dnsReady=false;s.netStep=4;}
  if(mode==='filled'){s.netStep=3;}
  if(mode==='review'){s.step=4;s.checks={pc:true,dns:true,mail:true,backup:true};}
  if(mode==='internal'){s.v.tls='internal';s.v.trustPlan=true;s.netStep=3;}
  if(mode==='migration'){s.step=4;s.checks={pc:true,dns:true,mail:true,backup:true};}
  if(mode==='public'){s.flow='public';s.step=0;s.lan=true;}
  captureNetworkStart();render();
}
guidePage=function(){
  const n=s.netStep;
  if(n===3)return guideHead('通常は、園のドメインを使います','園内用と園外用に、別々の名前を用意します。まず園内の接続だけを設定します。')+
    `<label class="guide-choice"><input type="radio" name="tls" value="domain" ${s.v.tls==='domain'?'checked':''}><span><strong>園用ドメインを使う（推奨）</strong><small>アプリが名前とPCのIPを登録し、証明書も用意します。通常は各PC・iPadへの名前や証明書の登録が不要です。園専用のドメインとCloudflareの設定が必要です。</small></span></label>`+
    `<label class="guide-choice"><input type="radio" name="tls" value="internal" ${s.v.tls==='internal'?'checked':''}><span><strong>園内専用の名前・証明書を使う（担当者向け）</strong><small>ネットワークと端末を管理できる方がいる園向けです。園内DNSと各端末の証明書登録が必要です。iPadを手動設定する場合は、証明書の導入後に信頼設定も必要です。</small></span></label>`+
    tip('どちらでも、このPCのIP予約は必要です','ルーターで同じIPを割り当てる準備は残ります。ゲストWi-Fiなど、端末同士の接続を禁止する接続では使えません。')+guideFoot('開く名前を決める');
  if(s.v.tls==='domain'&&n===4)return guideHead('園内で開く名前を決めます','園が管理するドメインに lan. を付けた名前を使います。いまのホームページやメールの名前は変更しません。')+
    `<div class="fields">${input('hostname','園内で開くホスト名','text','例：lan.sakura.example（このモックだけの架空名）')}</div>`+
    check('domainReady','園専用のドメインをCloudflareで管理しています','ドメインの取得・Cloudflareへの登録がまだの場合は、設定担当者に依頼できます。')+
    tip('園外公開は、後から別の名前で設定します','例：app.sakura.example。園内名に私設IPを登録しても、それだけで園外に公開されることはありません。')+guideFoot('接続キーの準備へ');
  if(s.v.tls==='domain'&&n===6)return guideHead('名前とPCの対応はアプリが登録します','いまは変更内容の確認です。最後の「設定を適用」でDNSに書き込みます。')+
    `<dl class="review-list">${row('登録する名前',s.v.hostname)}${row('接続先',s.v.ip)}${row('レコード','A / DNS only（プロキシなし）')}</dl>`+
    check('dnsReady','この名前とIPを登録する予定で進めます','既存のA・AAAA・CNAMEと競合するときは上書きせず止まります。')+
    tip('通常は、園内DNSや端末の手動登録は不要です','ルーターのDNS保護機能で私設IPへの名前解決が遮断される場合があります。その場合は検査結果と相談内容を表示します。保護機能をアプリが勝手に無効化することはありません。')+
    `<details><summary>インターネット接続と公開される情報</summary><p>証明書の発行・更新と、名前を調べるためにインターネット接続を使います。インターネットが切れると、園内でも名前から開けなくなる場合があります。公開DNSに園内のIPアドレスが載ります。</p></details>`+guideFoot('登録前の確認へ');
  return oldGuidePage();
};
certificateGuide=function(){return oldCertificate().replaceAll('証明書用のDNS接続トークン','DNS登録・証明書用の接続トークン').replace('アプリが証明書を取得・更新するために使います。','アプリが園内名のAレコードを登録し、証明書を取得・更新するために使います。').replace('このキーでできること','このキーはドメイン全体のDNSを編集できます').replace('全ドメインやアカウント全体のキーではなく、必要なドメインに限定します。','園専用の1ゾーンに限定します。ほかの園と共有する親ドメインのキーは使いません。');};
validateGuideStep=function(){
  if(s.v.tls==='domain'&&s.netStep===4){if(!required(['hostname'])||!hostnameOK(s.v.hostname))return fail('園内の名前を入力してください。');if(!s.v.hostname.startsWith('lan.'))return fail('園内用の名前は lan. から始めます。');return s.v.domainReady||fail('ドメインの準備を確認してください。');}
  if(s.v.tls==='domain'&&s.netStep===6)return s.v.dnsReady||fail('登録する名前とIPを確認してください。');
  return oldValidateGuide();
};
readinessGuide=function(){
  if(s.v.tls!=='domain')return oldReadiness();
  return guideHead('変更前の準備を確認します','DNSレコードはまだ作成しません。登録後の名前解決とHTTPSは、適用時に調べます。')+
    `<dl class="review-list">${row('園内URL','https://'+s.v.hostname)}${row('このPC',s.v.ip)}${row('接続を許可する範囲',s.v.subnet)}</dl>`+
    (s.netDetails?Object.entries(s.netDetails).map(([k,v])=>`<p class="result ${v.passed?'':'error'}">${esc({ip:'PCの接続',dns:'レコードの競合',tls:'トークンの有効性・ドメイン参照'}[k])}：${v.passed?'確認できました':esc(v.message)}</p>`).join(''):'')+
    button('guide-check','登録前の準備を確認する','secondary')+tip('編集権限は、まだ確定していません','トークンの有効性とドメインを参照できることを調べます。実際の書き込み権限は、最後の適用時に確認します。')+guideFoot('メールの設定へ',!s.checks.dns);
};
lanPage=function(){
  if(s.step===4&&migrating)return title('園内用の名前を切り替えます','データ・アカウント・現在のパスワードは引き継ぎます。設定だけを切り替えます。')+
    `<dl class="review-list">${row('現在','https://hoikuict.home.arpa')}${row('切替後','https://'+s.v.hostname)}${row('IPアドレス',s.v.ip)}${row('変更するDNS','新しいAレコード / DNS only')}</dl>`+
    note('切替前にバックアップを取り、元の設定を保存します。新しい名前と証明書を確認してから切り替えます。失敗時は元の接続へ戻します。新しいURLは職員へ別途案内します。')+
    `<div class="proposal-warning">このモックは移行手順の提案です。実際の移行機能は未実装です。</div>`+footer('apply','バックアップして切り替える');
  const html=oldLanPage();
  return s.step===4&&s.v.tls==='domain'?html.replace('</h2>','</h2>'+tip('この操作でDNSへ登録します',`<p>${esc(s.v.hostname)} → ${esc(s.v.ip)} / A / DNS only</p><p>書き込み → 園内DNSの確認 → 証明書発行の順に進みます。作成済みなら重複登録しません。今回作成したレコードは所有記録を残し、取消時も第三者が変更したものは削除しません。</p>`)):html;
};
publicPage=function(){return oldPublicPage().replace('園内と同じホスト名を使います。園内DNSは今のサーバーを指す設定を保持します。','園内の lan. と異なる名前（例：app.）を使います。園内の直接接続は保持し、登録・再設定メールのリンクは公開URLへ切り替わります。');};
const previousValidate=validateStep;
validateStep=async function(){if(s.flow==='public'&&s.step===0){if(!required(['publicHostname']))return false;return s.v.publicHostname!==s.v.hostname||fail('園内名とは別の公開名を指定してください。');}return previousValidate();};
async function mockApi(path,payload){
  if(path==='server/check'){
    if(payload.kind==='adapters')return {adapters:s.adapters,message:'架空の接続情報を再表示しました。'};
    if(payload.kind==='connection'){
      const results={ip:{passed:true},dns:{passed:fault.value!=='conflict',message:'既存の別用途レコードがあります。上書きせず、別の名前を選んでください。'},tls:{passed:fault.value!=='zone',message:'対象ドメインを参照できません。ドメインの範囲と Zone Read を確認してください。'}};
      return {results,complete:Object.values(results).every(v=>v.passed),message:'変更前の模擬確認です。DNS書き込みは行っていません。'};
    }
    return {message:'確認しました（模擬）。実際の送信・検査は行っていません。'};
  }
  if(path==='server/apply'){mockJob=0;return {};}
  if(path==='server/status'){
    mockJob++;
    const errors={permission:'DNSを書き込めませんでした。園専用ゾーンの DNS Edit 権限を確認してください。',dns:'Cloudflareへの登録はできましたが、園内DNSで名前を確認できません。反映待ち・DNSの設定・リバインディング保護を担当者に確認してください。',https:'証明書の発行を確認できませんでした。外向き通信とDNS編集権限を確認してください。'};
    if(errors[fault.value])return {job:{state:'error',message:errors[fault.value],progress:2,recovery:'今回の作成レコードは所有記録に照らして取り消します。別の管理者が変更している場合は削除せず、要確認にします。元の接続とデータを保持します（模擬）。'}};
    const publicMode=s.operation==='public';
    if(mockJob<3)return {job:{state:'running',progress:mockJob*2,message:'DNS登録・HTTPS・データの確認を進めています（模擬）。'}};
    return {state:{version:s.version,lan:{...s.v},lan_confirmed:!!mockConfirmed.lan||publicMode,public:publicMode?{publicHostname:s.v.publicHostname}:null,public_confirmed:!!mockConfirmed.public},job:{state:'complete',progress:6,message:'設定しました（模擬）。'},health:{drill:{state:'complete',message:'隔離した復元先で確認しました（模擬）。'}}};
  }
  if(path==='server/drill')return {message:'隔離した復元先で確認しました（模擬）。'};
  if(path==='server/confirm'){mockConfirmed[payload.phase]=true;return {};}
  if(path==='launch')return {url:'#mock-login'};
  return {};
}
fixture.addEventListener('change',()=>resetProposal(fixture.value));
fault.addEventListener('change',()=>{if(['zone','conflict'].includes(fault.value))delete s.checks.dns;s.netOutcome=null;s.netDetails=null;s.error='';render();});
resetProposal('empty');
