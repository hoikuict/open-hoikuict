'use strict';
// Disconnected, in-memory review prototype. No fetch, storage, OS calls or form submission.
const panel = document.querySelector('#wizard');
const fixture = document.querySelector('#fixture');
const fault = document.querySelector('#fault');
const dialog = document.querySelector('#dialog');
const names = {local:['配布版','管理者','確認'], lan:['PC確認','園内接続','メール','バックアップ','確認','動作確認'], public:['公開先','接続準備','確認','園外確認']};
const sample = {
  name:'さくら園 導入担当',email:'admin@sakura.example',login:'',password:'SampleGarden!73',confirm:'SampleGarden!73',
  reason:'このPCでのβ版試用',actor:'',approver:'',path:'C:\\HoikuICT',port:'8001',
  facility:'さくら保育園（架空）',adapter:'ethernet',ip:'192.168.10.20',subnet:'192.168.10.0/24',ipReserved:false,
  tls:'domain',hostname:'hoikuict.sakura.example',localHostname:'hoikuict.home.arpa',dnsToken:'DEMO-NOT-A-REAL-DNS-TOKEN',dnsReady:false,
  smtpHost:'smtp.sakura.example',smtpPort:'587',smtpUser:'no-reply@sakura.example',smtpPassword:'DEMO-MAIL-PASSWORD',mailFrom:'no-reply@sakura.example',testRecipient:'admin@sakura.example',
  backupPath:'E:\\HoikuICT-Backup',backupTime:'02:00',retention:'30',noSleep:true,
  otherDevice:false,reboot:false,restore:false,trust:false,mailReceived:false,
  publicHostname:'hoikuict.sakura.example',tunnelToken:'DEMO-NOT-A-REAL-TUNNEL-TOKEN',externalDevice:false,externalMail:false,externalReady:false
};
let s, tick, dialogAction;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function reset(mode='filled') {
  clearInterval(tick);
  s={flow:'home',step:0,local:['local','lan','public'].includes(mode),lan:['lan','public'].includes(mode),public:mode==='public',lanPending:false,publicPending:false,
    v:{...sample},checks:{},error:'',notice:'',paused:false,applying:false,progress:0,failed:false,trialRunning:['local','lan','public'].includes(mode)};
  if(mode==='empty'||mode==='partial') {
    for(const key of ['name','email','login','password','confirm','actor','approver','facility','hostname','dnsToken','smtpHost','smtpUser','smtpPassword','mailFrom','testRecipient','backupPath','publicHostname','tunnelToken'])s.v[key]='';
    if(mode==='partial'){s.v.name=sample.name;s.v.email=sample.email;}
  }
  if(s.lan){s.v.ipReserved=true;s.v.dnsReady=true;}
  render();
}
function effective(){return {...s.v,login:s.v.login.trim()||s.v.email.trim(),actor:s.v.actor.trim()||s.v.name.trim(),approver:s.v.approver.trim()||s.v.name.trim()};}
function button(action,label,kind='primary',disabled=false){return `<button type="button" class="${kind}" data-action="${action}" ${disabled?'disabled':''}>${label}</button>`;}
function input(key,label,type='text',note='',optional=false) {
  return `<label for="${key}">${label}${note?`<span id="${key}-hint">${note}</span>`:''}<input id="${key}" name="${key}" type="${type}" value="${esc(s.v[key])}" ${optional?'':'required'} ${type==='number'?'min="1" max="65535"':''} maxlength="${['path','backupPath'].includes(key)?1024:255}" autocomplete="${type==='password'?'new-password':'off'}" ${note?`aria-describedby="${key}-hint"`:''}></label>`;
}
function select(key,label,items,note=''){return `<label for="${key}">${label}${note?`<span>${note}</span>`:''}<select name="${key}" id="${key}">${items.map(([v,l])=>`<option value="${v}" ${s.v[key]===v?'selected':''}>${l}</option>`).join('')}</select></label>`;}
function check(key,label,note=''){return `<label class="check-row" for="${key}"><input type="checkbox" id="${key}" name="${key}" ${s.v[key]?'checked':''}><span>${label}${note?`<small>${note}</small>`:''}</span></label>`;}
function row(label,value,action=''){return `<div><dt>${label}</dt><dd>${esc(value)}${action?button(action,'変更','edit'):''}</dd></div>`;}
function title(label,description){return `<p class="eyebrow">${s.flow==='local'?'このPCに導入':s.flow==='lan'?'園内LANの設定':'園外からの利用'} ・ ${s.step+1} / ${names[s.flow].length}</p><h2 tabindex="-1">${label}</h2><p class="intro">${description}</p>`;}
function note(text){return `<div class="soft-note">${text}</div>`;}
function footer(next='next',label='次へ',disabled=false){return `<div class="buttons">${button('pause','いったん中断','quiet')}${button('back',s.step?'戻る':'導入ホームへ','secondary')}${button(next,label,'primary',disabled)}</div>`;}
function checkResult(key,success){return s.checks[key]?`<div class="result" role="status">✓ ${success}（模擬結果）</div>`:'';}
function reviewURL(){return 'https://'+(s.v.tls==='domain'?s.v.hostname:s.v.localHostname);}
function steps(){
  const list=s.flow==='home'?['このPCで試す','園内LANで使う','園外からも使う']:names[s.flow];
  document.querySelector('#steps').innerHTML=list.map((text,i)=>`<li class="${s.flow==='home'?([s.local,s.lan,s.public][i]?'done':''):i===s.step?'active':i<s.step?'done':''}" ${s.flow!=='home'&&i===s.step?'aria-current="step"':''}><span>${s.flow==='home'&&[s.local,s.lan,s.public][i]?'✓':i+1}</span>${text}</li>`).join('');
}
function stage(n,label,status,description,actions,active=false){return `<article class="stage ${active?'active':''}"><div class="stage-heading"><h3><span class="stage-num">${n}</span>${label}</h3><span class="pill ${status.includes('利用中')||status==='導入済み'?'good':status.includes('確認')?'wait':''}">${status}</span></div><p>${description}</p><div class="buttons">${actions}</div></article>`;}
function home(){
  const localText=s.local?`${esc(s.v.path)} ・ v2026.9.23.1<br>管理者：${esc(effective().login)}<br>導入済みのデータとアカウントを、次の設定でも引き継ぎます。`:'GitHubから配布版と必要なソフトを取得します。まずは架空の園児・家庭で動作を確かめます。';
  return `<h2 tabindex="-1">導入と接続のホーム</h2><p class="intro">まずこのPCで確認し、園内へ。園外からの利用は、園内の準備ができてから追加できます。</p>
    <div class="stage-grid">
      ${stage('01','このPCで試す',s.local?'導入済み':'これから',localText,s.local?button('open-app',s.trialRunning||s.lan||s.lanPending?'ログイン画面を確認':'起動してログイン画面を確認','secondary')+(s.trialRunning&&!s.lan&&!s.lanPending?button('stop-local','試用アプリを停止','secondary'):''):button('start-local','このPCに導入する'),!s.local)}
      ${stage('02','園内LANで使う',s.lan?'利用中':s.lanPending?'動作確認待ち':'これから',s.lan?`${esc(reviewURL())}<br>自動起動・園内限定接続・定期バックアップを設定済み。`:'他のPCやタブレットから使えるようにします。自動起動、HTTPS、メール、バックアップを順番に設定します。',s.lan?button('lan-details','園内の設定を見る','secondary'):button('start-lan',s.lanPending?'動作確認を続ける':'園内LANを設定する','primary',!s.local),s.local&&!s.lan)}
      ${stage('03','園外からも使う',s.public?'利用中':s.publicPending?'園外確認待ち':'未公開',s.public?`https://${esc(s.v.publicHostname)}<br>保護者などが、園外からログインできます。`:'園内のデータを引き継ぎ、保護者などが園外からログインできるようにします。',s.public?button('public-details','公開設定を見る','secondary')+button('stop-public','園外からの利用を停止','secondary'):button('start-public',s.publicPending?'園外確認を続ける':'園外からの利用を設定','primary',!s.lan)+(s.publicPending?button('stop-public','公開を取り消す','secondary'):''),s.lan&&!s.public)}
    </div>${s.lan?note('この導入画面を閉じても、サーバーは動き続けます。Windowsの再起動後も自動で起動します。'):note('LANの設定に進むまでは、このPCだけでの試用です。園内LANの設定を完了すると、本番用の動作に切り替わります。')}
    <p class="subtle">導入済みの版は、毎回ダウンロードしません。新しい版への更新は、バックアップを確認してから別の操作で行う設計です。</p>`;
}
function localPage(){
  if(s.step===0)return title('配布版を確認します','公開済みの配布版から、このPC用の環境を用意します。')+
    `<div class="release-box"><div class="release-heading"><strong>導入する版の表示例</strong><span class="pill">確認結果は架空</span></div><div class="release-version">v2026.9.23.1</div><p>Windows 11 x64 ・ 約71 MB<br>GitHub / hoikuict/open-hoikuict</p><details><summary>この版の変更内容</summary><p>初期台帳の取り込み、保護者アカウントの停止・再開、オンライン導入に対応。</p></details></div>
    <ul class="check-list"><li><span class="check">✓</span><div>必要なソフトをまとめて準備<small>Git・Pythonの個別導入は不要です。</small></div></li><li><span class="check">✓</span><div>同じアプリから園内LANへ進める<small>園児・家庭・管理者のデータを引き継ぎます。</small></div></li></ul>
    <details><summary>保存場所などを変更する</summary><p>既存ファイルがある場所には、新規導入しません。</p><div class="fields">${input('path','保存場所')}${input('port','接続ポート','number')}</div></details>${footer()}`;
  if(s.step===1)return title('管理者を決めましょう','このPCで使う管理者アカウントを作成します。')+
    `<div class="fields">${input('name','管理者の名前')}${input('email','メールアドレス','email','未指定ならログインIDにも使います。試用中はメールを送りません。')}<div class="two-col">${input('password','パスワード','password','8〜128文字。氏名やIDを含めないでください。')}${input('confirm','パスワードの確認','password','同じものをもう一度')}</div></div><details><summary>ログインID・導入の記録を変更する</summary><p>本人が導入する場合、実行者・承認者には管理者の名前を使います。</p><div class="fields">${input('login','ログインID','text','未入力ならメールアドレス',true)}${input('reason','作成理由')}${input('actor','実行者','text','未入力なら管理者の名前',true)}${input('approver','承認者','text','未入力なら管理者の名前',true)}</div></details>${footer('next','確認へ')}`;
  const v=effective();
  return title('この内容で準備します','実行すると、ダウンロード・検証・展開と管理者作成を行います。')+
    `<dl class="review-list">${row('利用方法','このPCだけでの試用')}${row('導入する版','v2026.9.23.1（表示例）')}${row('管理者',v.name,'edit-local-1')}${row('ログインID',v.login)}${row('メール',v.email)}${row('パスワード','入力済み・内容は表示しません')}${row('保存場所',v.path,'edit-local-0')}${row('接続ポート',v.port)}</dl><details><summary>導入の記録を見る</summary><dl class="review-list">${row('作成理由',v.reason)}${row('実行者',v.actor)}${row('承認者',v.approver)}</dl></details>${note('ここまでの入力では、アカウントやファイルはまだ作成していません。')}${footer('apply','ダウンロードして準備')}`;
}
function lanPage(){
  if(s.step===0)return title('サーバーにするPCを確認','導入済みの環境を引き継ぎます。園内から接続できるか、必要な設定を確認します。')+
    `<dl class="review-list">${row('引き継ぐ環境',s.v.path)}${row('引き継ぐ内容','園児・家庭・アカウント・添付・設定鍵')}${row('PCの例','SAKURA-SERVER / Windows 11 x64')}${row('空き容量の例','128 GB')}</dl><div class="fields">${input('facility','園名')}${select('adapter','園内につながるネットワーク',[['ethernet','有線LAN / 192.168.10.20 / プライベート'],['wifi','Wi-Fi / 192.168.20.15 / パブリック']])}</div>
    ${s.v.adapter==='wifi'?'<div class="result error">このネットワークは「パブリック」です。園のネットワークであることを確認し、Windowsの設定を見直してください。</div>':''}
    <div class="inline-action">${button('check-pc','このPCを確認する','secondary')}</div>${checkResult('pc','既存環境・空き容量・ネットワークを確認しました')}
    ${note('適用直前に既存環境のバックアップを作ります。設定の入力中は、このPCの試用環境を変更しません。')}${footer('next','園内の接続設定へ')}`;
  if(s.step===1)return title('園内で使うアドレスを設定','サーバーの住所と、ブラウザーで開くURLを決めます。')+
    `<div class="fields"><div class="two-col">${input('ip','サーバーのIPアドレス','text','ルーターで予約するアドレス')}${input('subnet','接続を許可する園内範囲','text','例：192.168.10.0/24')}</div></div>
    ${check('ipReserved','ルーターで、このPCのIPアドレスを固定しました','DHCPの「アドレス予約」などで設定します。設定名は機種により異なります。')}
    <div class="fields">${select('tls','HTTPSの用意方法',[['domain','園用ドメインを使う（後で園外公開する場合に推奨）'],['internal','園内専用の証明書を使う']])}</div>
    ${s.v.tls==='domain'?`<div class="fields">${input('hostname','園内で開くホスト名','text','https:// や末尾の / は付けません。例：hoikuict.sakura.example')}${input('dnsToken','証明書用のDNS接続トークン','password','この提案ではCloudflare DNSを使用。対象ドメインのDNS編集だけを許可します。')}</div><p class="choice-note">ドメインを管理するCloudflareアカウントが必要です。証明書はサーバーを外部公開せずに取得し、自動更新する構成です。</p>`:`<div class="fields">${input('localHostname','園内専用のホスト名','text','例：hoikuict.home.arpa')}</div>${note('使うPC・タブレットすべてに園内証明書を登録します。園外公開へ進むときは公開用URLに変わるため、ブックマークや通知の再設定が必要になる場合があります。')}`}
    <details><summary>ルーターで必要な設定を見る</summary><ol class="numbered"><li>このPCのIPアドレスを予約します。</li><li>園内DNSで、上のホスト名をこのPCのIPアドレスに割り当てます。</li><li>対応していないルーターでは、ネットワーク担当者に園内DNSの設定を依頼します。</li></ol></details>
    ${check('dnsReady','園内DNSで、URLがこのPCを指すよう設定しました')}
    <div class="inline-action">${button('check-dns','URLとHTTPSを確認する','secondary')}</div>${checkResult('dns','URLと証明書の設定を確認しました')}${footer('next','メールの設定へ')}`;
  if(s.step===2)return title('送信用メールを設定','登録案内やパスワード再設定に使います。園内LANでの本番利用にも必要です。')+
    `<div class="fields"><div class="two-col">${input('smtpHost','メールサーバー（SMTP）')}${input('smtpPort','メールの接続ポート','number','STARTTLS対応。通常は587')}</div>${input('mailFrom','送信元メールアドレス','email')}${input('smtpUser','メールのログインID','text','認証が不要な園内メールサーバーでは空欄',true)}${input('smtpPassword','メールのパスワード','password','メール提供元が指定するアプリパスワード等を使います。',true)}${input('testRecipient','確認メールの送信先','email','実装後は、この宛先だけに確認メールを送ります。')}</div>
    <p class="subtle">暗号化：STARTTLSを使用します。保護者への案内メールは、この設定操作では送りません。</p><div class="inline-action">${button('check-mail','確認メールを送る（模擬）','secondary')}</div>${checkResult('mail','メールサーバーが確認メールを受け付けました')}
    ${check('mailReceived','確認メールを受信できました')}${footer('next','バックアップの設定へ')}`;
  if(s.step===3)return title('自動起動とバックアップ','毎日の運用を続けるための設定です。保存先には、サーバー本体とは別のドライブを推奨します。')+
    `<div class="fields">${input('backupPath','バックアップの保存場所','text','例：E:\\HoikuICT-Backup。常時接続した保存先を指定します。')}<div class="two-col">${input('backupTime','毎日のバックアップ時刻','time')}${select('retention','保存期間',[['14','14日'],['30','30日'],['90','90日']])}</div></div>
    <div class="inline-action">${button('check-backup','保存先を確認する','secondary')}</div>${checkResult('backup','保存権限・空き容量を確認しました')}
    ${note('Windowsへのログイン前からサーバーを自動起動します。障害で停止した場合も、サービスを再起動する設定にします。')}
    ${check('noSleep','電源接続中は、このPCを自動スリープさせない','画面は消灯できます。PCの電源が切れている間は利用・バックアップできません。')}
    <p class="subtle">スリープ設定を変更しない場合は、運用担当者が常時稼働を確保してください。</p>${footer('next','設定内容を確認')}`;
  if(s.step===4)return title('園内LANの設定を適用します','適用時にWindowsの管理者権限が必要です。試用アプリを一時停止して設定を切り替えます。')+
    `<dl class="review-list">${row('園名',s.v.facility,'edit-lan-0')}${row('既存データ',s.v.path+' を引き継ぐ')}${row('園内URL',reviewURL(),'edit-lan-1')}${row('IPアドレス',s.v.ip)}${row('接続元の範囲',s.v.subnet+' / プライベートネットワークのみ')}${row('HTTPS',s.v.tls==='domain'?'園用ドメイン・証明書自動更新':'園内証明書・各端末への登録が必要')}${row('メール送信元',s.v.mailFrom,'edit-lan-2')}${row('バックアップ',`${s.v.backupPath} / 毎日 ${s.v.backupTime} / ${s.v.retention}日`,'edit-lan-3')}${row('自動起動','有効・Windowsログイン不要')}${row('自動スリープ',s.v.noSleep?'電源接続中は無効':'現在のWindows設定を維持')}${row('園外からの利用','未公開')}</dl>
    <details><summary>このPCに行う変更を見る</summary><ul class="help-list"><li>既存データ・設定・鍵を退避してから本番用設定へ切り替えます。</li><li>アプリ、HTTPS接続、バックアップのサービスを登録します。</li><li>指定した園内範囲だけにHTTPS接続を許可します。</li><li>管理用の導入画面は、このPCだけで開ける状態を保ちます。</li><li>途中で失敗した場合は、変更記録に従い今回の設定を戻します。</li></ul></details>
    ${note('適用後は、別の端末からの接続・再起動・復元を確認します。園外公開の設定は、その確認後に進めます。')}${footer('apply','園内LANの設定を適用')}`;
  return title('園内で使えることを確認','設定は適用済みです。日常の運用を始める前に、次を確認してください。')+
    `<div class="result">✓ サーバー・HTTPS・定期バックアップが起動しました（模擬結果）</div><p class="url-display">${esc(reviewURL())}</p><div class="mini-map"><span>園内PC・タブレット</span><b>→</b><span>このWindows PC</span></div>
    ${s.v.tls==='internal'?note('園内証明書を各端末に登録してから、このURLを開きます。ブラウザーの警告画面を通過して利用する運用にはしません。')+check('trust','利用する端末に園内証明書を登録しました'):''}
    ${check('otherDevice','別のPC・タブレットからログインできました','園内Wi-Fiまたは園内の有線LANにつないで確認します。')}
    ${check('reboot','サーバーPCを再起動しても、別の端末から接続できました','Windowsにログインする前に使えることも確認します。')}
    <div class="inline-action">${button('check-restore','バックアップと復元の練習をする（模擬）','secondary')}</div>${checkResult('restore','別の検証場所への復元と、データの読み取りを確認しました')}
    ${check('restore','復元の結果を確認しました','復元の練習では、利用中のデータを上書きしません。')}
    ${note('この後は、導入画面を閉じてもサーバーが動き続けます。園外からの利用は、必要になったときに追加できます。')}${footer('finish-lan','確認を完了して園内で使う')}`;
}
function publicPage(){
  if(s.step===0)return title('園外から使うURLを確認','園内で使っているデータとアカウントを、そのまま利用します。')+
    `<div class="fields">${input('publicHostname','園外から開くホスト名','text','例：hoikuict.sakura.example。管理するドメインを指定します。')}</div>
    ${s.v.tls==='domain'?note('園内と同じホスト名を使います。園内DNSは今のサーバーを指す設定を保持します。'):note('園外には公開用のURLを追加します。園内専用URLも保持しますが、登録メールのリンクは公開用に変わります。通知の再登録が必要になる場合があります。')}
    <dl class="review-list">${row('公開する機能','職員・保護者のログイン画面と業務アプリ')}${row('アクセスの条件','既存アカウントでのログイン・現在の閲覧権限')}${row('管理用導入画面','このPCだけで開く')}</dl>${footer('next','接続の準備へ')}`;
  if(s.step===1)return title('Cloudflareと接続する準備','園のネットワークから外向きに接続します。ルーターのポート開放は不要です。')+
    `<ol class="numbered"><li>ドメインを管理するCloudflareアカウントを開きます。</li><li>この園用のTunnelを作り、上のホスト名を割り当てます。</li><li>接続用トークンを下に入力します。実装時は手順を画面から開けるようにします。</li></ol>
    <div class="fields">${input('tunnelToken','Cloudflare Tunnelの接続用トークン','password','このモックでは架空の値だけを使ってください。')}</div>
    <p class="subtle">実装では、トークンをWindowsの保護された保存先へ記録します。確認画面や操作ログには表示しません。</p>
    <div class="inline-action">${button('check-tunnel','接続の準備を確認する','secondary')}</div>${checkResult('tunnel','トークン・公開先・外向き通信の準備を確認しました')}
    ${note('公開は、次の確認画面で「園外からの利用を開始」を押してから行います。')}${footer('next','公開内容を確認')}`;
  if(s.step===2)return title('園外からの利用を開始します','開始すると、インターネットからこのURLにアクセスできるようになります。')+
    `<div class="mini-map"><span>保護者のスマートフォン</span><b>→</b><span>Cloudflare</span><b>→</b><span>園のPC</span></div><dl class="review-list">${row('園外URL','https://'+s.v.publicHostname,'edit-public-0')}${row('園内URL',reviewURL())}${row('データ・権限','現在のデータ・パスワード・閲覧権限を維持')}${row('登録メール等','公開URLを使用する設定へ切り替え')}${row('公開用接続','Windows起動時に自動接続')}${row('園内接続','現在の園内接続を維持')}</dl>
    ${note('保護者への登録案内は、業務アプリから必要な相手に送ります。公開の開始だけで一斉送信は行いません。')}${footer('apply','園外からの利用を開始')}`;
  return title('園外から接続できるか確認','公開用の接続を開始しました。園外の回線から、実際のログインを確認します。')+
    `<p class="url-display">https://${esc(s.v.publicHostname)}</p><div class="result">✓ 公開用接続が起動しました（模擬結果）</div>
    ${check('externalDevice','スマートフォンのWi-Fiを切り、携帯回線からログインできました','園内の接続だけでは、園外からの接続確認になりません。')}${check('externalMail','確認用アカウントで、メール内のリンクを開けました')}${check('externalReady','登録済みアカウントの閲覧範囲を確認しました')}
    ${note('接続できない場合は、公開を取り消して園内運用を続けられます。')}
    <div class="buttons">${button('stop-public','公開を取り消す','secondary')}${button('finish-public','確認を完了')}</div>`;
}
function progressNames(){return s.flow==='local'?['保存先を確認','配布ファイルをダウンロード','ファイルを検証・展開','設定と管理者を作成','起動を確認']:s.flow==='lan'?['管理者権限と適用内容を確認','既存環境をバックアップ','HTTPSと本番用設定を準備','Windowsサービスを登録','園内接続を許可・起動を確認']:['現在の設定を退避','公開用接続を登録','URL・メールリンクを切り替え','公開用接続を開始'];}
function applying(){
  const list=progressNames();
  return `<h2 tabindex="-1">${s.failed?'設定を完了できませんでした':'設定を進めています'}</h2><p class="intro">${s.failed?'下の案内を確認して、再試行できます。':'これは進行表示のデモです。実際のPC設定は変更していません。'}</p><progress max="${list.length}" value="${s.progress}" aria-label="設定の進み具合"></progress><ul class="progress-items">${list.map((l,i)=>`<li class="${i<s.progress?'done':i===s.progress?s.failed?'failed':'running':''}"><span class="status-dot">${i<s.progress?'✓':i===s.progress&&s.failed?'!':''}</span>${l}</li>`).join('')}</ul>
    ${s.failed?note(s.flow==='local'?'今回の準備用フォルダーを片付けました。入力内容を保持しています。':s.flow==='lan'?'今回のLAN設定を戻し、元の試用環境を起動しました。データと設定鍵を保持しています。':'公開用接続を停止し、URLなどを元に戻しました。園内運用を継続しています。')+`<div class="buttons">${button('edit-failed','入力に戻る','secondary')}${button('retry','もう一度試す')}</div>`:`<p class="subtle" role="status">${esc(list[s.progress]||'確認中')}（模擬処理）</p><div class="buttons">${button('pause','いったん中断','secondary')}</div>`}`;
}
function render(focus=true){
  steps();
  const error=s.error?`<div class="error-summary" tabindex="-1" role="alert">${esc(s.error)}</div>`:'';
  const notification=s.notice?`<div class="result" role="status">${esc(s.notice)}</div>`:'';
  panel.innerHTML=error+notification+(s.paused?`<h2 tabindex="-1">中断しました</h2><p class="intro">入力内容は、このページを開いている間だけ保持します。実際のアプリでは、秘密情報を除いた下書きをこのPCに保存する設計です。</p>${note(s.lanPending?'LAN設定は適用済みです。確認の続きから再開できます。':s.lan?'園内の運用は続いています。':s.local?'このPCの導入済み環境は保持しています。':'まだ環境を作成していません。')}<div class="buttons">${button('resume','設定を再開する')}</div>`:s.applying?applying():s.flow==='home'?home():`<form id="setup-form" novalidate>${s.flow==='local'?localPage():s.flow==='lan'?lanPage():publicPage()}</form>`);
  fixture.disabled=s.applying&&!s.failed;fault.disabled=s.applying&&!s.failed;
  if(focus){panel.querySelector(s.error?'.error-summary':'h2')?.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});}
}
function fail(message,key=''){s.error=message;render();if(key){const field=document.getElementById(key);field?.setAttribute('aria-invalid','true');field?.closest('details')?.setAttribute('open','');}return false;}
function required(keys){
  for(const key of keys){
    const element=document.getElementById(key);
    if(!String(s.v[key]||'').trim())return fail(`${element?.closest('label')?.childNodes[0]?.textContent||key}を入力してください。`,key);
    if(element?.type==='email'&&!element.validity.valid)return fail('メールアドレスの形式を確認してください。',key);
  } return true;
}
function hostnameOK(value){return /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}$/i.test(value)&&!value.includes('..');}
function ipv4(value){return /^\d+\.\d+\.\d+\.\d+$/.test(value)&&value.split('.').every(part=>Number(part)<=255);}
function portOK(value){return /^\d+$/.test(value)&&Number(value)>0&&Number(value)<=65535;}
function pathOK(value){return /^[a-z]:\\[^<>"|?*]+$/i.test(value);}
function validateStep(){
  if(s.flow==='local'){
    if(s.step===0){if(!required(['path','port']))return false;if(!pathOK(s.v.path))return fail('保存場所は、C:\\HoikuICT のようなローカルの専用フォルダーを指定してください。');if(!portOK(s.v.port))return fail('接続ポートは1〜65535で指定してください。');if(fault.value==='port')return fail('この接続ポートは別のアプリが使っています。ポートを変更して再確認してください。');}
    if(s.step===1){if(!required(['name','email','password','confirm','reason']))return false;if(s.v.password.length<8||s.v.password.length>128||s.v.password!==s.v.confirm)return fail('パスワードを8〜128文字にし、確認欄に同じ内容を入力してください。');}
  }
  if(s.flow==='lan'){
    if(s.step===0&&(!required(['facility'])||!s.checks.pc))return s.error?false:fail('「このPCを確認する」を実行してください。');
    if(s.step===1&&!s.checks.dns)return fail('IPアドレス・園内DNSを設定して「URLとHTTPSを確認する」を実行してください。');
    if(s.step===2&&(!s.checks.mail||!s.v.mailReceived))return fail('確認メールを送信し、受信できたことを確認してください。');
    if(s.step===3){if(!required(['backupTime']))return false;if(!s.checks.backup)return fail('バックアップの保存先を確認してください。');}
  }
  if(s.flow==='public'){
    if(s.step===0){if(!required(['publicHostname']))return false;if(!hostnameOK(s.v.publicHostname))return fail('園外ホスト名は https:// や / を含めず入力してください。');if(s.v.tls==='domain'&&s.v.publicHostname!==s.v.hostname)return fail('この提案では、園用ドメインを使う場合は園内と同じホスト名で公開します。');if(s.v.publicHostname.endsWith('.home.arpa')||s.v.publicHostname.endsWith('.local'))return fail('園外用には、管理している公開ドメインを指定してください。');}
    if(s.step===1&&!s.checks.tunnel)return fail('Cloudflareの接続準備を確認してください。');
  }
  return true;
}
function confirmDialog(title,message,label,action){document.querySelector('#dialog-title').textContent=title;document.querySelector('#dialog-message').textContent=message;document.querySelector('#dialog-confirm').textContent=label;dialogAction=action;dialog.showModal();}
function beginApply(){
  s.error='';s.notice='';s.applying=true;s.failed=false;s.progress=0;render();
  const kind=s.flow;
  tick=setInterval(()=>{
    const failure=(kind==='local'&&fault.value==='download'&&s.progress===1)||(kind==='lan'&&fault.value==='admin'&&s.progress===0)||(kind==='lan'&&fault.value==='lan'&&s.progress===3)||(kind==='public'&&fault.value==='tunnel'&&s.progress===2);
    if(failure){clearInterval(tick);s.failed=true;s.error=fault.value==='admin'?'Windowsの管理者許可が得られませんでした。設定は変更していません。':kind==='local'?'ダウンロードが中断しました。通信状態を確認して再試行してください。':kind==='lan'?'サービスを開始できませんでした。変更を取り消し、元の環境を復旧しました。':'公開用接続を開始できませんでした。トークンと接続先を確認してください。';render();return;}
    s.progress++;
    if(s.progress>=progressNames().length){clearInterval(tick);s.applying=false;
      if(kind==='local'){s.local=true;s.trialRunning=true;s.v.password='';s.v.confirm='';s.flow='home';s.step=0;s.notice='このPCへの導入が完了しました（模擬結果）。続けて園内LANを設定できます。';}
      if(kind==='lan'){s.lanPending=true;s.step=5;}
      if(kind==='public'){s.publicPending=true;s.step=3;}
    }render(!s.applying);
  },450);
}
function change(key,value){
  s.v[key]=value;s.error='';
  if(['facility','adapter'].includes(key))delete s.checks.pc;
  if(['ip','subnet','ipReserved','tls','hostname','localHostname','dnsToken','dnsReady'].includes(key))delete s.checks.dns;
  if(['smtpHost','smtpPort','smtpUser','smtpPassword','mailFrom','testRecipient'].includes(key)){delete s.checks.mail;s.v.mailReceived=false;}
  if(['backupPath'].includes(key)){delete s.checks.backup;delete s.checks.restore;s.v.restore=false;}
  if(['publicHostname','tunnelToken'].includes(key))delete s.checks.tunnel;
}
panel.addEventListener('submit',e=>e.preventDefault());
panel.addEventListener('input',e=>{if(e.target.name&&Object.hasOwn(s.v,e.target.name))change(e.target.name,e.target.type==='checkbox'?e.target.checked:e.target.value);});
panel.addEventListener('change',e=>{if(e.target.name&&Object.hasOwn(s.v,e.target.name)){change(e.target.name,e.target.type==='checkbox'?e.target.checked:e.target.value);if(e.target.tagName==='SELECT')render(false);}});
panel.addEventListener('click',event=>{
  const control=event.target.closest('[data-action]');if(!control||control.disabled)return;
  const a=control.dataset.action;if(s.applying&&!s.failed&&a!=='pause')return;
  s.error='';s.notice='';
  if(a.startsWith('edit-')&&a!=='edit-failed'){const [,flow,index]=a.split('-');s.flow=flow;s.step=Number(index);render();return;}
  if(a==='start-local'){s.flow='local';s.step=0;}
  if(a==='start-lan'){if(!s.local)return;s.flow='lan';s.step=s.lanPending?5:0;}
  if(a==='start-public'){if(!s.lan)return;s.flow='public';s.step=s.publicPending?3:0;if(s.v.tls==='domain')s.v.publicHostname=s.v.hostname;}
  if(a==='back'){if(s.step===5&&s.flow==='lan'){s.flow='home';s.step=0;}else if(s.step)s.step--;else s.flow='home';}
  if(a==='next'){if(!validateStep())return;s.step++;}
  if(a==='open-app'){s.trialRunning=true;s.notice='実装では、必要に応じて起動し、導入済みの職員ログイン画面を開きます。このモックは業務アプリに接続しません。';}
  if(a==='stop-local'){s.trialRunning=false;s.notice='このPCの試用アプリを停止しました（模擬結果）。データは保持しています。';}
  if(a==='lan-details'){s.notice=`園内URL：${reviewURL()} ／ 保存先：${s.v.backupPath} ／ 毎日 ${s.v.backupTime} ／ ${s.v.retention}日保存（表示例）`;
  }
  if(a==='public-details'){s.notice=`園外URL：https://${s.v.publicHostname} ／ 公開用接続は自動起動。停止しても園内接続とデータは保持します（表示例）。`;}
  if(a==='pause'){confirmDialog('いったん中断しますか？',s.applying?'今回の処理を区切りで中断し、変更を戻します。入力内容はこのページ内に保持します。':s.lanPending?'適用済みのLAN設定を保持し、動作確認を中断します。次回は確認の続きから進めます。':'現在の利用状態を維持して、設定を中断します。入力内容はこのページ内に保持します。','中断する',()=>{clearInterval(tick);s.applying=false;s.failed=false;s.paused=true;render();});return;}
  if(a==='resume'){s.paused=false;}
  if(a==='check-pc'){if(!required(['facility']))return;if(s.v.adapter!=='ethernet')return fail('園のネットワークを確認し、Windowsでプライベートに設定してから再確認してください。このモックでは有線LANを選ぶと続けられます。');s.checks.pc=true;}
  if(a==='check-dns'){
    if(!required(['ip','subnet',s.v.tls==='domain'?'hostname':'localHostname',...(s.v.tls==='domain'?['dnsToken']:[])]))return;
    const [network,prefix,...rest]=s.v.subnet.split('/');
    if(!ipv4(s.v.ip)||!ipv4(network)||rest.length||!/^\d+$/.test(prefix||'')||Number(prefix)<1||Number(prefix)>32)return fail('IPアドレスと園内範囲を確認してください。例：192.168.10.20 と 192.168.10.0/24。');
    const number=ip=>ip.split('.').reduce((acc,n)=>(acc*256+Number(n))>>>0,0);const mask=(0xffffffff << (32-Number(prefix)))>>>0;
    if((number(network)&mask)!==(number(s.v.ip)&mask))return fail('このPCのIPアドレスが、接続を許可する園内範囲に含まれていません。');
    const host=s.v.tls==='domain'?s.v.hostname:s.v.localHostname;if(!hostnameOK(host))return fail('ホスト名を確認してください。https:// や / は付けません。');
    if(!s.v.ipReserved||!s.v.dnsReady)return fail('IPアドレスの固定と園内DNSの設定を確認してください。');
    if(fault.value==='dns')return fail('園内DNSまたは証明書の確認に失敗しました。設定を見直して再確認してください。');s.checks.dns=true;
  }
  if(a==='check-mail'){
    if(!required(['smtpHost','smtpPort','mailFrom','testRecipient']))return;
    if(!portOK(s.v.smtpPort))return fail('メールの接続ポートを1〜65535で指定してください。');
    if(s.v.smtpUser&&!s.v.smtpPassword)return fail('メールのログインIDを指定した場合は、パスワードも入力してください。');
    if(fault.value==='mail')return fail('メールサーバーに接続できませんでした。サーバー名・ポート・認証情報を確認してください。');s.checks.mail=true;
  }
  if(a==='check-backup'){
    if(!required(['backupPath']))return;
    if(!pathOK(s.v.backupPath))return fail('バックアップ先は、E:\\HoikuICT-Backup のようなローカルドライブの専用フォルダーを指定してください。');
    const path=s.v.path.replace(/\\+$/,'').toLowerCase();const target=s.v.backupPath.replace(/\\+$/,'').toLowerCase();if(target===path||target.startsWith(path+'\\'))return fail('バックアップ先は、アプリの保存場所の外に指定してください。');
    if(fault.value==='backup')return fail('保存先に書き込めません。接続・空き容量・サービスの保存権限を確認してください。');s.checks.backup=true;
  }
  if(a==='check-restore'){if(fault.value==='backup')return fail('復元用のバックアップを作成できませんでした。保存先を確認して再試行してください。');s.checks.restore=true;}
  if(a==='check-tunnel'){
    if(!required(['tunnelToken']))return;
    // The tunnel error fixture deliberately fails during application, exercising rollback.
    s.checks.tunnel=true;
  }
  if(a==='apply'){
    if(s.flow==='lan'&&(!s.checks.pc||!s.checks.dns||!s.checks.mail||!s.checks.backup))return fail('変更後の設定に未確認の項目があります。各設定を確認し直してください。');
    if(s.flow==='public'&&!s.checks.tunnel)return fail('接続の準備を確認し直してください。');
    beginApply();return;
  }
  if(a==='retry'){beginApply();return;}
  if(a==='edit-failed'){s.applying=false;s.failed=false;s.step=s.flow==='local'?0:s.flow==='lan'?0:1;}
  if(a==='finish-lan'){
    if(!s.v.otherDevice||!s.v.reboot||!s.v.restore||!s.checks.restore||(s.v.tls==='internal'&&!s.v.trust))return fail('別の端末からの接続、再起動、復元を確認してください。園内証明書を使う場合は端末への登録も必要です。');
    s.lan=true;s.lanPending=false;s.flow='home';s.step=0;s.notice='園内LANの確認が完了しました（模擬結果）。園外公開は、必要になったときに進められます。';
  }
  if(a==='finish-public'){
    if(!s.v.externalDevice||!s.v.externalMail||!s.v.externalReady)return fail('携帯回線からのログイン、メールのリンク、閲覧範囲を確認してください。');
    s.public=true;s.publicPending=false;s.flow='home';s.step=0;s.notice='園外からの利用確認が完了しました（模擬結果）。';
  }
  if(a==='stop-public'){
    confirmDialog('園外からの利用を停止しますか？','園外からの接続と、公開URLを使う登録・再設定メールの送信を停止します。園内の接続・データ・アカウントは保持します。','園外からの利用を停止',()=>{s.public=false;s.publicPending=false;s.flow='home';s.step=0;s.checks.tunnel=false;s.v.externalDevice=false;s.v.externalMail=false;s.v.externalReady=false;s.notice='園外からの利用を停止しました（模擬結果）。園内では引き続き使えます。公開URLのメール送信は、公開を再開するまで停止します。';render();});return;
  }
  render();
});
document.querySelector('#dialog-back').addEventListener('click',()=>dialog.close());
document.querySelector('#dialog-confirm').addEventListener('click',()=>{dialog.close();dialogAction?.();dialogAction=null;});
fixture.addEventListener('change',()=>reset(fixture.value));
fault.addEventListener('change',()=>{s.error='';render();});
reset();
