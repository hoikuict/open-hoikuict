function effective(){return {...s.v,login:s.v.login.trim()||s.v.email.trim(),actor:s.v.actor.trim()||s.v.name.trim(),approver:s.v.approver.trim()||s.v.name.trim()};}
function button(action,label,kind='primary',disabled=false){return `<button type="button" class="${kind}" data-action="${action}" ${disabled?'disabled':''}>${label}</button>`;}
function input(key,label,type='text',note='',optional=false) {
  return `<label for="${key}">${label}${note?`<span id="${key}-hint">${note}</span>`:''}<input id="${key}" name="${key}" type="${type}" value="${esc(s.v[key])}" ${optional?'':'required'} ${type==='number'?'min="1" max="65535"':''} maxlength="${key==='tunnelToken'?8192:['dnsToken','smtpPassword'].includes(key)?2048:['path','backupPath'].includes(key)?1024:255}" autocomplete="${type==='password'?'new-password':'off'}" ${note?`aria-describedby="${key}-hint"`:''}></label>`;
}
function select(key,label,items,note=''){return `<label for="${key}">${label}${note?`<span>${note}</span>`:''}<select name="${key}" id="${key}">${items.map(([v,l])=>`<option value="${v}" ${s.v[key]===v?'selected':''}>${l}</option>`).join('')}</select></label>`;}
function check(key,label,note=''){return `<label class="check-row" for="${key}"><input type="checkbox" id="${key}" name="${key}" ${s.v[key]?'checked':''}><span>${label}${note?`<small>${note}</small>`:''}</span></label>`;}
function row(label,value,action=''){return `<div><dt>${label}</dt><dd>${esc(value)}${action?button(action,'変更','edit'):''}</dd></div>`;}
function title(label,description){return `<p class="eyebrow">${s.flow==='local'?'このPCに導入':s.flow==='lan'?'園内LANの設定':'園外からの利用'} ・ ${s.step+1} / ${names[s.flow].length}</p><h2 tabindex="-1">${label}</h2><p class="intro">${description}</p>`;}
function note(text){return `<div class="soft-note">${text}</div>`;}
function footer(next='next',label='次へ',disabled=false){return `<div class="buttons">${button('pause','いったん中断','quiet')}${button('back',s.step?'戻る':'導入ホームへ','secondary')}${button(next,label,'primary',disabled)}</div>`;}
function checkResult(key,success){return s.checks[key]?`<div class="result" role="status">✓ ${success}</div>`:'';}
function reviewURL(){return 'https://'+(s.v.tls==='domain'?s.v.hostname:s.v.localHostname);}
function steps(){
  const list=s.flow==='home'?['このPCで試す','園内LANで使う','園外からも使う']:names[s.flow];
  document.querySelector('#steps').innerHTML=list.map((text,i)=>`<li class="${s.flow==='home'?([s.local,s.lan,s.public][i]?'done':''):i===s.step?'active':i<s.step?'done':''}" ${s.flow!=='home'&&i===s.step?'aria-current="step"':''}><span>${s.flow==='home'&&[s.local,s.lan,s.public][i]?'✓':i+1}</span>${text}</li>`).join('');
}
function stage(n,label,status,description,actions,active=false){return `<article class="stage ${active?'active':''}"><div class="stage-heading"><h3><span class="stage-num">${n}</span>${label}</h3><span class="pill ${status.includes('利用中')||status==='導入済み'?'good':status.includes('確認')?'wait':''}">${status}</span></div><p>${description}</p><div class="buttons">${actions}</div></article>`;}
function home(){
  const localText=s.local?`${esc(s.v.path)} ・ ${esc(s.release?.version || s.version || '導入済みの版')}<br>管理者：${esc(effective().login)}<br>導入済みのデータとアカウントを、次の設定でも引き継ぎます。`:'GitHubから配布版と必要なソフトを取得します。まずは架空の園児・家庭で動作を確かめます。';
  return `<h2 tabindex="-1">導入と接続のホーム</h2><p class="intro">まずこのPCで確認し、園内へ。園外からの利用は、園内の準備ができてから追加できます。</p>
    <div class="stage-grid">
      ${stage('01','このPCで試す',s.local?'導入済み':'これから',localText,s.local?button('open-app',s.trialRunning||s.lan||s.lanPending?'ログイン画面を確認':'起動してログイン画面を確認','secondary')+(s.trialRunning&&!s.lan&&!s.lanPending?button('stop-local','試用アプリを停止','secondary'):''):button('start-local','このPCに導入する'),!s.local)}
      ${stage('02','園内LANで使う',s.lan?'利用中':s.lanPending?'動作確認待ち':'これから',s.lan?`${esc(reviewURL())}<br>自動起動・園内限定接続・定期バックアップを設定済み。`:'他のPCやタブレットから使えるようにします。自動起動、HTTPS、メール、バックアップを順番に設定します。',s.lan?button('lan-details','園内の設定を見る','secondary'):button('start-lan',s.lanPending?'動作確認を続ける':'園内LANを設定する','primary',!s.local),s.local&&!s.lan)}
      ${stage('03','園外からも使う',s.public?'利用中':s.publicPending?'園外確認待ち':'未公開',s.public?`https://${esc(s.v.publicHostname)}<br>保護者などが、園外からログインできます。`:'園内のデータを引き継ぎ、保護者などが園外からログインできるようにします。',s.public?button('public-details','公開設定を見る','secondary')+button('stop-public','園外からの利用を停止','secondary'):button('start-public',s.publicPending?'園外確認を続ける':'園外からの利用を設定','primary',!s.lan)+(s.publicPending?button('stop-public','公開を取り消す','secondary'):''),s.lan&&!s.public)}
    </div>${s.lan?note('この導入画面を閉じても、サーバーは動き続けます。Windowsの再起動後も自動で起動します。'):note('LANの設定に進むまでは、このPCだけでの試用です。園内LANの設定を完了すると、本番用の動作に切り替わります。')}
    <p class="subtle">導入済みの版は、毎回ダウンロードしません。導入済みの環境は自動更新せず、現在の版とデータを保持します。</p>`;
}
function localPage(){
  if(s.step===0)return title('配布版を確認します','公開済みの配布版から、このPC用の環境を用意します。')+
    `<div class="release-box"><div class="release-heading"><strong>導入する版</strong><span class="pill">検証済みの配布情報</span></div><div class="release-version">${esc(s.release?.version || s.version || '導入済みの版')}</div><p>Windows 11 x64 ・ 約${Math.ceil((s.release?.size || 0)/1048576)} MB<br>GitHub / hoikuict/open-hoikuict</p><details><summary>この版の変更内容</summary><p>${esc(s.release?.notes || '')}</p></details></div>
    <ul class="check-list"><li><span class="check">✓</span><div>必要なソフトをまとめて準備<small>Git・Pythonの個別導入は不要です。</small></div></li><li><span class="check">✓</span><div>同じアプリから園内LANへ進める<small>園児・家庭・管理者のデータを引き継ぎます。</small></div></li></ul>
    <details><summary>保存場所などを変更する</summary><p>既存ファイルがある場所には、新規導入しません。</p><div class="fields">${input('path','保存場所')}${input('port','接続ポート','number')}</div></details>${footer()}`;
  if(s.step===1)return title('管理者を決めましょう','このPCで使う管理者アカウントを作成します。')+
    `<div class="fields">${input('name','管理者の名前')}${input('email','メールアドレス','email','未指定ならログインIDにも使います。試用中はメールを送りません。')}<div class="two-col">${input('password','パスワード','password','8〜128文字。氏名やIDを含めないでください。')}${input('confirm','パスワードの確認','password','同じものをもう一度')}</div></div><details><summary>ログインID・導入の記録を変更する</summary><p>本人が導入する場合、実行者・承認者には管理者の名前を使います。</p><div class="fields">${input('login','ログインID','text','未入力ならメールアドレス',true)}${input('reason','作成理由')}${input('actor','実行者','text','未入力なら管理者の名前',true)}${input('approver','承認者','text','未入力なら管理者の名前',true)}</div></details>${footer('next','確認へ')}`;
  const v=effective();
  return title('この内容で準備します','実行すると、ダウンロード・検証・展開と管理者作成を行います。')+
    `<dl class="review-list">${row('利用方法','このPCだけでの試用')}${row('導入する版',s.release?.version || s.version || '同梱版')}${row('管理者',v.name,'edit-local-1')}${row('ログインID',v.login)}${row('メール',v.email)}${row('パスワード','入力済み・内容は表示しません')}${row('保存場所',v.path,'edit-local-0')}${row('接続ポート',v.port)}</dl><details><summary>導入の記録を見る</summary><dl class="review-list">${row('作成理由',v.reason)}${row('実行者',v.actor)}${row('承認者',v.approver)}</dl></details>${note('ここまでの入力では、アカウントやファイルはまだ作成していません。')}${footer('apply','ダウンロードして準備')}`;
}
function lanPage(){
  if(s.step===0)return title('サーバーにするPCを確認','導入済みの環境を引き継ぎます。園内から接続できるか、必要な設定を確認します。')+
    `<dl class="review-list">${row('引き継ぐ環境',s.v.path)}${row('引き継ぐ内容','園児・家庭・アカウント・添付・設定鍵')}${row('PC',s.pcName || 'Windows 11 x64')}${row('空き容量','事前確認で検査します')}</dl><div class="fields">${input('facility','園名')}${select('adapter','園内につながるネットワーク',s.adapters.map(a=>[a.id,a.name+' / '+a.ip+' / '+(a.private?'プライベート':'要確認')]))}</div>
    ${s.adapters.some(a=>a.id===s.v.adapter&&!a.private)?'<div class="result error">このネットワークは「パブリック」です。園のネットワークであることを確認し、Windowsの設定を見直してください。</div>':''}
    <div class="inline-action">${button('check-pc','このPCを確認する','secondary')}</div>${checkResult('pc','既存環境・空き容量・ネットワークを確認しました')}
    ${note('適用時は元のデータを保持したままコピーし、初回バックアップも作ります。設定の入力中は、このPCの試用環境を変更しません。')}${footer('next','園内の接続設定へ')}`;
  if(s.step===1)return title('園内で使うアドレスを設定','サーバーの住所と、ブラウザーで開くURLを決めます。')+
    `<div class="fields"><div class="two-col">${input('ip','サーバーのIPアドレス','text','ルーターで予約するアドレス')}${input('subnet','接続を許可する園内範囲','text','例：192.168.10.0/24')}</div></div>
    ${check('ipReserved','ルーターで、このPCのIPアドレスを固定しました','DHCPの「アドレス予約」などで設定します。設定名は機種により異なります。')}
    <div class="fields">${select('tls','HTTPSの用意方法',[['domain','園用ドメインを使う（後で園外公開する場合に推奨）'],['internal','園内専用の証明書を使う']])}</div>
    ${s.v.tls==='domain'?`<div class="fields">${input('hostname','園内で開くホスト名','text','https:// や末尾の / は付けません。例：hoikuict.sakura.example')}${input('dnsToken','証明書用のDNS接続トークン','password','Cloudflare DNSを使用。対象ドメインのDNS編集だけを許可します。')}</div><p class="choice-note">ドメインを管理するCloudflareアカウントが必要です。証明書はサーバーを外部公開せずに取得し、自動更新する構成です。</p>`:`<div class="fields">${input('localHostname','園内専用のホスト名','text','例：hoikuict.home.arpa')}</div>${note('使うPC・タブレットすべてに園内証明書を登録します。園外公開へ進むときは公開用URLに変わるため、ブックマークや通知の再設定が必要になる場合があります。')}`}
    <details><summary>ルーターで必要な設定を見る</summary><ol class="numbered"><li>このPCのIPアドレスを予約します。</li><li>園内DNSで、上のホスト名をこのPCのIPアドレスに割り当てます。</li><li>対応していないルーターでは、ネットワーク担当者に園内DNSの設定を依頼します。</li></ol></details>
    ${check('dnsReady','園内DNSで、URLがこのPCを指すよう設定しました')}
    <div class="inline-action">${button('check-dns','URLとHTTPSを確認する','secondary')}</div>${checkResult('dns','URLと証明書の設定を確認しました')}${footer('next','メールの設定へ')}`;
  if(s.step===2)return title('送信用メールを設定','登録案内やパスワード再設定に使います。園内LANでの本番利用にも必要です。')+
    `<div class="fields"><div class="two-col">${input('smtpHost','メールサーバー（SMTP）')}${input('smtpPort','メールの接続ポート','number','STARTTLS対応。通常は587')}</div>${input('mailFrom','送信元メールアドレス','email')}${input('smtpUser','メールのログインID','text','認証が不要な園内メールサーバーでは空欄',true)}${input('smtpPassword','メールのパスワード','password','メール提供元が指定するアプリパスワード等を使います。',true)}${input('testRecipient','確認メールの送信先','email','この宛先だけに確認メールを送ります。')}</div>
    <p class="subtle">暗号化：STARTTLSを使用します。保護者への案内メールは、この設定操作では送りません。</p><div class="inline-action">${button('check-mail','確認メールを送る','secondary')}</div>${checkResult('mail','メールサーバーが確認メールを受け付けました')}
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
    `<div class="result">✓ サーバー・HTTPS・定期バックアップが起動しました</div><p class="url-display">${esc(reviewURL())}</p><div class="mini-map"><span>園内PC・タブレット</span><b>→</b><span>このWindows PC</span></div>
    ${s.v.tls==='internal'?note('「園内証明書を保存」で取得した証明書を各端末に登録してから、このURLを開きます。ブラウザーの警告画面を通過して利用する運用にはしません。')+button('certificate','園内証明書を保存','secondary')+check('trust','利用する端末に園内証明書を登録しました'):''}
    ${check('otherDevice','別のPC・タブレットからログインできました','園内Wi-Fiまたは園内の有線LANにつないで確認します。')}
    ${check('reboot','サーバーPCを再起動しても、別の端末から接続できました','Windowsにログインする前に使えることも確認します。')}
    <div class="inline-action">${button('check-restore','バックアップと復元の練習をする','secondary')}</div>${checkResult('restore','別の検証場所への復元と、データの読み取りを確認しました')}
    ${check('restore','復元の結果を確認しました','復元の練習では、利用中のデータを上書きしません。')}
    ${note('この後は、導入画面を閉じてもサーバーが動き続けます。園外からの利用は、必要になったときに追加できます。')}${footer('finish-lan','確認を完了して園内で使う')}`;
}
function publicPage(){
  if(s.step===0)return title('園外から使うURLを確認','園内で使っているデータとアカウントを、そのまま利用します。')+
    `<div class="fields">${input('publicHostname','園外から開くホスト名','text','例：hoikuict.sakura.example。管理するドメインを指定します。')}</div>
    ${s.v.tls==='domain'?note('園内と同じホスト名を使います。園内DNSは今のサーバーを指す設定を保持します。'):note('園外には公開用のURLを追加します。園内専用URLも保持しますが、登録メールのリンクは公開用に変わります。通知の再登録が必要になる場合があります。')}
    <dl class="review-list">${row('公開する機能','職員・保護者のログイン画面と業務アプリ')}${row('アクセスの条件','既存アカウントでのログイン・現在の閲覧権限')}${row('管理用導入画面','このPCだけで開く')}</dl>${footer('next','接続の準備へ')}`;
  if(s.step===1)return title('Cloudflareと接続する準備','園のネットワークから外向きに接続します。ルーターのポート開放は不要です。')+
    `<ol class="numbered"><li>ドメインを管理するCloudflareアカウントを開きます。</li><li>この園用のTunnelを作り、上のホスト名を割り当てます。接続先：HTTP / 127.0.0.1:${esc(s.ports?.tunnel || '')}。</li><li>接続用トークンを下に入力します。Cloudflareの公開先には、下に表示する接続先を指定します。</li></ol>
    <div class="fields">${input('tunnelToken','Cloudflare Tunnelの接続用トークン','password','この園のTunnel専用トークンを入力します。')}</div>
    <p class="subtle">トークンをWindowsの保護された保存先へ記録します。確認画面や操作ログには表示しません。</p>
    <div class="inline-action">${button('check-tunnel','接続の準備を確認する','secondary')}</div>${checkResult('tunnel','トークン形式を確認しました。認証・接続は開始時に検査します')}
    ${note('公開は、次の確認画面で「園外からの利用を開始」を押してから行います。')}${footer('next','公開内容を確認')}`;
  if(s.step===2)return title('園外からの利用を開始します','開始すると、インターネットからこのURLにアクセスできるようになります。')+
    `<div class="mini-map"><span>保護者のスマートフォン</span><b>→</b><span>Cloudflare</span><b>→</b><span>園のPC</span></div><dl class="review-list">${row('園外URL','https://'+s.v.publicHostname,'edit-public-0')}${row('園内URL',reviewURL())}${row('データ・権限','現在のデータ・パスワード・閲覧権限を維持')}${row('登録メール等','公開URLを使用する設定へ切り替え')}${row('公開用接続','Windows起動時に自動接続')}${row('園内接続','現在の園内接続を維持')}</dl>
    ${note('保護者への登録案内は、業務アプリから必要な相手に送ります。公開の開始だけで一斉送信は行いません。')}${footer('apply','園外からの利用を開始')}`;
  return title('園外から接続できるか確認','公開用の接続を開始しました。園外の回線から、実際のログインを確認します。')+
    `<p class="url-display">https://${esc(s.v.publicHostname)}</p><div class="result">✓ 公開用接続が起動しました</div>
    ${check('externalDevice','スマートフォンのWi-Fiを切り、携帯回線からログインできました','園内の接続だけでは、園外からの接続確認になりません。')}${check('externalMail','確認用アカウントで、メール内のリンクを開けました')}${check('externalReady','登録済みアカウントの閲覧範囲を確認しました')}
    ${note('接続できない場合は、公開を取り消して園内運用を続けられます。')}
    <div class="buttons">${button('stop-public','公開を取り消す','secondary')}${button('finish-public','確認を完了')}</div>`;
}
