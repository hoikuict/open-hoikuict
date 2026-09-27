'use strict';
// Templates shared by the approved guided setup; actions use authenticated APIs.
const guideNames=['はじめに','園の接続','住所の固定','方式を選ぶ','開く名前','暗号化の準備','名前とPC','準備の確認'];
const networkKeys=['adapter','ip','subnet','ipReserved','tls','hostname','localHostname','dnsToken','dnsReady','networkConfirmed','domainReady','trustPlan'];
const gmailNames=['使うメール','送信元','Googleの準備','アプリパスワード','受信の確認'];
const mailKeys=['smtpHost','smtpPort','smtpUser','smtpPassword','mailFrom','testRecipient','googleReady'];
function selectedAdapter(){return s.adapters.find(a=>a.id===s.v.adapter&&a.ip===s.v.ip)||s.adapters.find(a=>a.id===s.v.adapter)||{};}
function hostnameOK(value){return value.length<=253&&value.split('.').length>=2&&value.split('.').every(p=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(p))&&!ipv4(value);}
function ipv4(value){return /^\d+\.\d+\.\d+\.\d+$/.test(value)&&value.split('.').every(part=>Number(part)<=255);}
function portOK(value){return /^\d+$/.test(value)&&Number(value)>0&&Number(value)<=65535;}
function guideHead(heading,intro){
  const n=s.netStep||0;
  return `<p class="eyebrow">園内LANの設定 ・ 2 / 6</p><div class="guide-meter"><span>接続の準備をひとつずつ</span><span>${n+1} / ${guideNames.length}　${guideNames[n]}</span></div><progress class="guide-track" max="8" value="${n+1}" aria-label="園内接続の準備の進み具合"></progress><h2 tabindex="-1">${heading}</h2><p class="intro">${intro}</p>`;
}
function guideFoot(label='次へ',disabled=false){
  return `<div class="guide-help">${button('guide-help','分からない・担当者に相談する','quiet')}</div><div class="guide-foot">${button('pause','ここで中断する','quiet')}<div class="buttons">${button('guide-back','戻る','secondary')}${button('guide-next',label,'primary',disabled)}</div></div><div class="guide-cancel">${button('guide-cancel','この接続設定を取り消す','quiet')}</div>`;
}
function tip(heading,body){return `<div class="guide-tip"><strong>${heading}</strong>${body}</div>`;}
function work(heading,body){return `<section class="guide-do"><h3>${heading}</h3>${body}</section>`;}
function selectedHost(){return s.v.tls==='internal'?s.v.localHostname:s.v.hostname;}
function guidePage(){
  const n=s.netStep||0;
  if(n===0)return guideHead('ほかの端末から、このPCにつなぐ準備です','職員用のPCやタブレットから、同じ保育ICTを開けるようにします。ひとつずつ案内するので、今すべての設定を知っている必要はありません。')+
    `<div class="mini-map"><span>職員のPC・タブレット</span><b>→ 園のネットワーク →</b><span>このPC</span></div><div class="guide-work"><div><h3>アプリがお手伝いすること</h3><ul><li>PCの接続情報を調べる</li><li>入力する値を整理する</li><li>準備できたか確認する</li></ul></div><div><h3>園で準備していただくこと</h3><ul><li>ルーターの設定を開ける人</li><li>設定が難しい場合の相談先</li><li>園内で使うPC・タブレット</li></ul></div></div>`+
    tip('最初に行うのは、園の接続の確認です','画面で確認する作業から始めます。ルーターでの作業が必要になったら、操作する場所と入力する値を表示します。')+
    ''+guideFoot('園の接続を確認する');
  if(n===1)return guideHead('園の職員用ネットワークにつながっていますか？','園内で使う端末同士がつながる場所を確認します。IPアドレスは、ネットワーク上でこのPCを見つけるための番号です。')+
    `<dl class="review-list">${row('選択中の接続',(selectedAdapter().name||'未検出')+' / '+(selectedAdapter().private?'プライベート':'要確認'))}${row('読み取ったPCの番号',selectedAdapter().ip||'未検出')}${row('接続を許可する範囲',s.v.subnet||'未入力')}</dl>`+
    `<p class="subtle">「${esc(s.v.subnet||'未検出')}」は接続を許可するネットワークの範囲です。通常は読み取った候補を使います。ゲスト用Wi-Fiや別の部署のネットワークを含める場合は、担当者に確認します。</p>`+
    check('networkConfirmed','園の職員用ネットワークであることを確認しました','個人のテザリングや来客用Wi-Fiではないことを確認します。')+
    `<details><summary>担当者向け：IPアドレス・許可範囲を変更する</summary><p>別の番号を入力する場合は、PC側の設定とルーター側の予約も一致させる必要があります。</p><div class="fields">${input('ip','サーバーのIPアドレス','text','このPCが実際に使う番号')}${input('subnet','接続を許可する園内範囲','text','例：192.168.10.0/24')}</div>${button('guide-detect','接続を読み直して値を入れる','secondary')}</details>`+
    `<p class="next-up">次は、このPCの番号が変わらないようにします。</p>`+guideFoot('住所の固定へ');
  if(n===2)return guideHead('このPCの住所が変わらないようにします','PCを再起動しても同じ番号を使えるように、ルーターで「予約」します。番号が変わると、ほかの端末から保育ICTを見つけられなくなります。')+
    tip('ここはルーターで行う作業です','園のルーターを管理している方と進めます。設定のログイン情報が分からない場合は、下の「担当者に相談する」から必要な内容を確認できます。')+
    work('行うこと',`<ol><li>園のルーターの設定画面を開きます。開き方はすぐ下で確認できます。</li><li>「DHCP固定割当」「アドレス予約」などの項目を探します。</li><li>このPCを選び、下のIPアドレスを予約して保存します。</li></ol>`)+
    `<details><summary>ルーターの設定画面は、どう開く？</summary><ol class="numbered"><li>ルーター本体のラベルか、園のネットワーク資料でメーカー・型番を確認します。</li><li>その機種の説明書で「設定画面の開き方」を確認します。管理業者が設置した機器は、業者に連絡します。</li><li>新しいブラウザーのタブを開き、指定された管理アドレスを入力します。</li><li>ルーター用の管理IDでログインします。保育ICTのIDとは別のものです。</li></ol><p>このPCのゲートウェイ：${esc(selectedAdapter().gateway||'未検出')}。ルーターの管理画面のアドレスと同じとは限りません。開き方は機種の説明書か担当者に確認してください。</p></details>`+
    `<dl class="review-list">${row('予約するIP',s.v.ip)}${row('このPCの名前',selectedAdapter().pcName||'未検出')}${row('MACアドレス',selectedAdapter().mac||'未検出')}</dl><details><summary>ルーターの操作例を見る</summary><p>画面名はメーカー・機種により変わります。PC名だけで判別できないときは、MACアドレスで照合します。</p><p><a class="guide-link" href="https://www.buffalo.jp/support/faq/detail/15917.html" target="_blank" rel="noreferrer">Buffaloの公式案内：特定端末に同じIPを割り当てる</a></p><p>対象機種が違う場合や、設定を保存できない場合は担当者に依頼してください。</p></details>`+
    check('ipReserved','ルーターで、このPCのIP予約を保存しました','設定画面で、このPCと上の番号が対応していることを確認します。')+
    `<p class="subtle">このチェックは作業の記録です。アプリから、ルーターの予約内容を自動確認することはできません。</p>`+guideFoot('アドレスの方式を選ぶ');
  if(n===3)return guideHead('園内で開くアドレスの用意方法を選びます','どちらの方法でも、まず園内だけで使えます。園で準備できるものに合わせて選んでください。')+
    `<label class="guide-choice"><input type="radio" name="tls" value="domain" ${s.v.tls==='domain'?'checked':''}><span><strong>園が管理するドメインを使う</strong>例：hoikuict.sakura.example<small>必要なもの：園用ドメインを管理するCloudflareアカウントと、その管理者の協力。<br>対応する端末では、園内証明書を個別に登録する作業を省けます。後の園外利用でも同じ名前を使えます。</small></span></label>`+
    `<label class="guide-choice"><input type="radio" name="tls" value="internal" ${s.v.tls==='internal'?'checked':''}><span><strong>園内専用の名前を使う</strong>例：hoikuict.home.arpa<small>ドメインの契約は不要です。代わりに、使うPC・タブレットすべてへ証明書を登録します。<br>後で園外から使うときは、公開用のアドレスを別に用意します。</small></span></label>`+
    tip('どちらにも、園内で名前をつなぐ設定が必要です','あとで「この名前はこのPCです」と教える設定を案内します。ルーターが対応していない場合は、ネットワーク担当者の作業が必要になります。')+guideFoot('開く名前を決める');
  if(n===4){
    const domain=s.v.tls==='domain';
    return guideHead(domain?'園が管理する名前を入力します':'園内だけで使う名前を決めます',domain?'園のドメイン管理者と、保育ICTに使う名前を決めてください。すでに使っているホームページやメールの設定を置き換えない名前にします。':'園内の端末でブラウザーに入力する名前です。この例を使う場合も、園内に同じ名前がないか担当者に確認します。')+
      `<div class="fields">${domain?input('hostname','園内で開くホスト名','text','入力例：hoikuict.sakura.example。https:// と末尾の / は付けません。'):input('localHostname','園内専用のホスト名','text','入力例：hoikuict.home.arpa')}</div>`+
      `<p>ブラウザーで開くアドレス</p><p class="url-display">${selectedHost()?'https://'+esc(selectedHost()):'名前を入力すると表示します'}</p>`+
      (domain?check('domainReady','このドメインをCloudflareで管理していることを確認しました','アカウントを持っているだけでなく、このドメインの設定を管理できる必要があります。'):`<p class="subtle">園内専用の名前は .home.arpa で終わる名前にします。園外からはこの名前で開けません。</p>`)+
      tip('まだアドレスは使える状態ではありません','次に暗号化の準備をし、そのあと、この名前をPCの番号に結び付けます。')+guideFoot('暗号化の準備へ');
  }
  if(n===5)return certificateGuide();
  if(n===6)return guideHead('この名前で、このPCを見つけられるようにします','「園内DNS」は、アドレスの名前からPCの番号を調べる仕組みです。園の端末が、このPCの番号を受け取れるよう設定します。')+
    `<div class="mini-map"><span>${esc(selectedHost())}</span><b>→</b><span>${esc(s.v.ip)}</span></div>`+
    work('ルーター・DNSを管理する方に行っていただくこと',`<ol><li>園の端末が使うDNSの設定画面を開きます。</li><li>「ローカルDNS」「ホスト名の登録」などで、上の名前とIPアドレスを登録します。</li><li>サーバーPCと利用端末が、そのDNSを使う状態にします。</li></ol>`)+
    `<details><summary>ルーターに設定項目が見つからない場合</summary><p>機種によっては、この機能がありません。IP予約だけでは、名前で接続できるとは限りません。</p><p>下の相談ボタンから、名前・IP・必要な設定をまとめた依頼文を表示できます。担当者が園内DNSを用意してから、続きへ戻ってください。</p></details>`+
    check('dnsReady','園内DNSに、上の名前とIPアドレスを登録しました','分からない場合はチェックせず、担当者に確認してください。次の画面で、このPCから名前を引けるか調べます。')+
    (s.v.tls==='domain'?tip('「証明書用のDNS」とは作業場所が異なります','ここで設定するのは、園内の端末がPCを見つけるための対応です。Cloudflareの証明書用トークンを入力するだけでは、この対応は作られません。'):tip('使う端末すべてで、この名前を調べられるようにします','このPCだけで名前が見つかっても、ほかの端末から使えるとは限りません。別のPC・タブレットでの確認も、最後に行います。'))+guideFoot('準備できたか確認する');
  return readinessGuide();
}
function certificateGuide(){
  if(s.v.tls==='internal')return guideHead('園内証明書を使う準備をします','通信を暗号化するために、この園用の証明書を使います。設定を適用したあと、利用する各端末に登録します。')+
    work('今、準備すること','<ol><li>保育ICTを使うPC・タブレットを確認します。</li><li>それぞれで設定を変更できる人を確認します。</li><li>園が管理している端末の場合は、端末の管理担当者と登録方法を確認します。</li></ol>')+
    tip('登録作業は、サーバーを準備したあとに行います','後の「動作確認」で、このアプリが用意した園内証明書を保存し、端末へ登録します。OSや管理設定に合わせた手順が必要です。ブラウザーの警告を無視して使う方法にはしません。')+
    check('trustPlan','利用する端末と、証明書を登録する担当者を確認しました','これは準備の確認です。端末への登録完了ではありません。')+guideFoot('名前とPCを結ぶ設定へ');
  const page=s.tokenStep||0;
  const head=guideHead('証明書を用意するための接続キーを準備します','接続キー（APIトークン）は、園のドメインを管理する方に作っていただきます。アプリが証明書を取得・更新するために使います。');
  const mini=`<p class="guide-status">接続キーの案内　${page+1} / 3</p>`;
  let body='';
  if(page===0)body=work('1. 作成画面を開く','<ol><li>園のドメインを管理しているCloudflareへログインします。</li><li>プロフィールの「API Tokens」を開きます。</li><li>「Create Token」から「Edit zone DNS」のテンプレートを選びます。</li></ol>')+
    `<p><a class="guide-link" href="https://developers.cloudflare.com/fundamentals/api/get-started/create-token/" target="_blank" rel="noreferrer">Cloudflareの公式案内を見る</a></p>`;
  if(page===1)body=work('2. この園のドメインだけに権限を付ける',`<p>作成画面で、次の2つの権限を指定します。</p><dl class="review-list">${row('DNSの編集','Zone → DNS → Edit')}${row('ドメイン情報の参照','Zone → Zone → Read')}${row('対象の範囲','この園で使う1つのドメイン')}</dl><p>「Zone Resources」は「Include → Specific zone」で園のドメインを選び、内容を確認して作成します。</p>`)+
    tip('このキーでできること','対象ドメインのDNSを変更できます。全ドメインやアカウント全体のキーではなく、必要なドメインに限定します。証明書の自動更新でも使います。');
  if(page===2)body=work('3. 作成された接続キーを入力する','<p>作成直後に表示されるキーを、この欄へ貼り付けます。説明画面や相談文には貼り付けないでください。</p>')+
    `<div class="fields">${input('dnsToken','証明書用のDNS接続トークン','password','対象ドメインに限定した接続キーを入力します。画面を閉じると再入力が必要です。')}</div>`+
    tip('証明書を発行するのは、最後の適用時です','このあとキーの有効性と対象ドメインを確認します。発行やDNSへの書き込みは、設定を適用するときに行います。');
  return head+mini+body+`<div class="guide-token-nav">${page?button('guide-token-back','前の説明へ','secondary'):''}${page<2?button('guide-token-next','説明の続きへ','primary'):''}</div>`+guideFoot('名前とPCを結ぶ設定へ',page<2);
}
function readinessGuide(){
  const result=s.netOutcome;
  const status=(key)=>!result?'未確認':result[key]?'✓ 確認できました':'要確認';
  return guideHead('接続の準備を確認します','入力した設定を確かめます。うまくいかない項目があれば、その作業まで戻って直せます。')+
    `<dl class="review-list">${row('開く予定のURL','https://'+selectedHost())}${row('PCの番号',s.v.ip)}${row('接続を許可する範囲',s.v.subnet)}</dl><ul class="guide-checks" aria-live="polite"><li><b class="${result?.ip?'ok':result?'bad':''}">PCの接続先：${status('ip')}</b><small>今のIPが設定と一致し、園のネットワークにつながっているか。</small></li><li><b class="${result?.dns?'ok':result?'bad':''}">名前からPCを探す：${status('dns')}</b><small>このPCで名前を調べたとき、${esc(s.v.ip)}になるか。</small></li><li><b class="${result?.tls?'ok':result?'bad':''}">暗号化の準備：${status('tls')}</b><small>${s.v.tls==='domain'?'トークンの有効性と、対象ドメインを参照できるか。DNSへの書き込み・証明書の発行は適用時に確認します。':'各端末に証明書を登録する準備ができているか。'}</small></li></ul>`+
    `${s.netDetails?Object.entries(s.netDetails).filter(([,r])=>!r.passed).map(([key,r])=>`<p class="result error">${esc(({ip:'PCの接続',dns:'名前の確認',tls:'暗号化の準備'})[key])}：${esc(r.message)}</p>`).join(''):''}${button('guide-check',result?'もう一度確認する':'準備を確認する','secondary')}`+
    (result&&!result.ip?tip('PCの番号を見直してください',`今の接続情報と設定が一致していません。園のネットワークにつながっているか、予約した番号になっているかを確認します。<div class="inline-action">${button('guide-go-1','園の接続へ戻る','secondary')}</div>`):'')+
    (result&&!result.dns?tip('名前とIPの対応を見直してください',`園内DNSに登録した名前と番号、利用しているDNSを担当者に確認します。<div class="inline-action">${button('guide-go-6','名前とPCの設定へ戻る','secondary')}</div>`):'')+
    (result&&!result.tls?tip('暗号化の準備を見直してください',`${s.v.tls==='domain'?'対象ドメインと、キーの有効性・権限を確認してください。':'端末への証明書登録を行う担当者を確認してください。'}<div class="inline-action">${button('guide-go-5','暗号化の準備へ戻る','secondary')}</div>`):'')+
    tip('実際の接続は、設定を適用したあとに確認します','今は準備の確認です。HTTPSでのログインと、ほかの端末からの接続は、最後の「動作確認」で行います。')+
    `<p class="next-up">次は、登録案内などに使う送信用メールを設定します。</p>`+guideFoot('メールの設定へ',!s.checks.dns);
}
function validGuideNetwork(){
  if(!required(['ip','subnet']))return false;
  const parts=s.v.subnet.split('/');const [network,prefix]=parts;
  if(!ipv4(s.v.ip)||!ipv4(network)||parts.length!==2||!/^\d+$/.test(prefix)||+prefix<16||+prefix>30)return fail('番号と園内範囲を確認してください。例：192.168.10.20 と 192.168.10.0/24。','subnet');
  const toNumber=ip=>ip.split('.').reduce((n,a)=>(n*256+Number(a))>>>0,0);
  const mask=(0xffffffff<<(32-Number(prefix)))>>>0;
  const privateIP=ip=>ip.startsWith('10.')||ip.startsWith('192.168.')||(ip.startsWith('172.')&&+ip.split('.')[1]>=16&&+ip.split('.')[1]<=31);
  if(!privateIP(s.v.ip)||!privateIP(network)||((toNumber(network)&mask)>>>0)!==toNumber(network)||((toNumber(s.v.ip)&mask)>>>0)!==toNumber(network))return fail('園内用の番号と、そこを含む範囲を指定してください。分からない場合は読み取った候補へ戻し、担当者に確認してください。','subnet');
  return true;
}
function validateGuideStep(){
  const n=s.netStep||0;
  if(n===1){if(!validGuideNetwork())return false;if(!s.v.networkConfirmed)return fail('園の職員用ネットワークであることを確認してください。');}
  if(n===2&&!s.v.ipReserved)return fail('ルーターでのIP予約ができたら、確認のチェックを付けてください。まだの場合は、担当者に相談して中断できます。');
  if(n===3&&!['domain','internal'].includes(s.v.tls))return fail('準備できるものに合わせて、どちらかを選んでください。分からない場合は、担当者への相談内容を表示できます。');
  if(n===4){
    const key=s.v.tls==='domain'?'hostname':'localHostname';
    if(!required([key]))return false;
    if(!hostnameOK(s.v[key].trim()))return fail('名前だけを入力してください。https:// や末尾の / は付けません。',key);
    if(s.v.tls==='internal'&&!s.v.localHostname.trim().toLowerCase().endsWith('.home.arpa'))return fail('園内専用の名前は .home.arpa で終わる形にします。例：hoikuict.home.arpa。',key);
    if(s.v.tls==='domain'&&/\.(home\.arpa|local|localhost|example|test|invalid)$/i.test(s.v.hostname.trim()))return fail('この方式には、園が所有・管理するドメインの名前を入力します。',key);
    if(s.v.tls==='domain'&&!s.v.domainReady)return fail('このドメインをCloudflareで管理しているか、園の管理者に確認してください。');
  }
  if(n===5){if(s.v.tls==='domain'&&!required(['dnsToken']))return false;if(s.v.tls==='internal'&&!s.v.trustPlan)return fail('利用する端末と、証明書を登録する担当者を確認してください。');}
  if(n===6&&!s.v.dnsReady)return fail('名前とPCの対応を園内DNSへ登録してから進みます。担当者への依頼文を表示して、中断することもできます。');
  if(n===7&&!s.checks.dns)return fail('「準備を確認する」を押し、要確認の項目を見直してください。');
  return true;
}
function showHelp(){
  const selected=s.v.tls==='domain'?'園用ドメイン':s.v.tls==='internal'?'園内専用の証明書':'未選択（方式から相談したい）';
  document.querySelector('#help-title').textContent='担当者に渡す相談内容';
  document.querySelector('#help-text').value=[
    'オープン保育ICTを、まず園内だけで使う準備について相談します。',
    `困っている作業：${guideNames[s.netStep||0]}`,`PC名：${selectedAdapter().pcName||'未検出'}`,
    `使うIP：${s.v.ip||'未定'}`,`接続を許可する範囲：${s.v.subnet||'未定'}`,
    `開く名前：${selectedHost()||'未定'}`,`方式：${selected}`,'',
    '1. このPCへのIP固定予約を設定できるか確認してください。',
    '2. 園内DNSで、上の名前がこのPCのIPを返すよう設定できるか確認してください。',
    '3. 各利用端末が同じ園内DNSを使い、接続できるか確認してください。',
    s.v.tls==='domain'?'4. ドメインをCloudflareで管理できるか、証明書用の限定トークンを用意できるか確認してください。':s.v.tls==='internal'?'4. 園内証明書を各PC・タブレットに登録する担当者と方法を確認してください。':'4. 園用ドメイン方式と園内証明書方式の、どちらを準備できるか相談したいです。',
    'ルーターの外部向けポート開放や、園外公開は今回の作業に含みません。',
    'トークンやパスワードは、この依頼文には記載しません。'
  ].join('\n');
  document.querySelector('#help-dialog').showModal();
}
function mailHead(heading,description){
  const stage=s.mailStep||0;const gmail=s.v.mailProvider!=='custom';
  return `<p class="eyebrow">園内LANの設定 ・ 3 / 6</p><div class="guide-meter"><span>送信用メールをひとつずつ</span><span>${stage+1} / ${gmail?5:2}　${gmail?gmailNames[stage]:'メール設定'}</span></div><h2 tabindex="-1">${heading}</h2><p class="intro">${description}</p>`;
}
function mailFoot(label='次へ'){
  return `<div class="guide-help">${button('mail-help','分からない・担当者に相談する','quiet')}</div><div class="guide-foot">${button('pause','ここで中断する','quiet')}<div class="buttons">${button('mail-back','戻る','secondary')}${button('mail-next',label)}</div></div>`;
}
function mailGuidePage(){
  const n=s.mailStep||0;
  if(n===0)return mailHead('どのメールから送りますか？','保護者への登録案内や、パスワード再設定のメールに使います。受信した方には、ここで選ぶメールアドレスが送信元として表示されます。')+
    `<label class="guide-choice"><input type="radio" name="mailProvider" value="gmail" ${s.v.mailProvider==='gmail'?'checked':''}><span><strong>Gmailを使う</strong>@gmail.com のアドレス、またはGoogle Workspaceで使う園のアドレス。<small>接続先と番号は自動入力します。Google側でアプリパスワードを作る手順を案内します。</small></span></label><label class="guide-choice"><input type="radio" name="mailProvider" value="custom" ${s.v.mailProvider==='custom'?'checked':''}><span><strong>ほかの送信用メールを使う</strong>園のメール提供元や管理担当者から、接続情報を受け取って設定します。<small>この導入アプリでは、STARTTLSで接続できるSMTPサーバーを設定します。</small></span></label>`+
    tip('園で管理できるアドレスを使います','担当者が交代しても引き継げるアドレスを用意してください。Gmailを使う場合は、サーバーPCからインターネットへの接続が必要です。園内だけで保育ICTを使う場合も同じです。')+mailFoot('選んだメールで進む');
  if(s.v.mailProvider==='custom')return mailHead('メール提供元の情報を入力します','契約しているメールサービスの案内や、園の担当者から受け取った情報を使います。')+
    `<div class="fields"><div class="two-col">${input('smtpHost','メールサーバー（SMTP）')}${input('smtpPort','メールの接続ポート','number','STARTTLS対応。提供元の指定を確認してください。')}</div>${input('mailFrom','送信元メールアドレス','email')}${input('smtpUser','メールのログインID','text','認証が不要な園内メールサーバーでは空欄',true)}${input('smtpPassword','メールのパスワード','password','提供元のアプリパスワード等を使います。',true)}${input('testRecipient','確認メールの送信先','email','自分で受信を確認できる宛先を指定します。')}</div>`+
    `<p>暗号化：STARTTLS。確認メールは指定した1つの宛先に送ります。</p>${button('mail-test','確認メールを送る','secondary')}${mailResult()}${check('mailReceived','確認メールを受信できました')}`+mailFoot('バックアップの設定へ');
  if(n===1)return mailHead('Gmailの送信元を決めます','このあとGoogleで準備するときも、ここに入力したアドレスのアカウントを使います。')+
    `<div class="fields">${input('mailFrom','送信元のGmailアドレス','email','Gmailで使っているメールアドレス全体を入力します。')}</div>`+
    `<details><summary>Google Workspace（園の独自アドレス）の場合</summary><p>Gmailで使っている園のアドレスを入力します。アプリパスワードを利用できるかは、組織の設定にもよるため、Google Workspaceの管理者へ確認してください。</p><p>管理者からSMTPリレーなど別の設定を案内された場合は「ほかの送信用メールを使う」を選びます。</p></details>`+
    tip('アドレスは2つの用途に自動設定します','メールの送信元と、Gmailに接続するためのログインIDに同じアドレスを使います。あとで送信元を変えた場合は、新しいアカウントで準備し直します。')+mailFoot('Google側の準備へ');
  if(n===2)return mailHead('Googleで2段階認証を確認します','アプリパスワードを作るために、先にGoogle側の準備を行います。すでに2段階認証を使っている場合は、有効になっていることを確認してください。')+
    `<p class="url-display">${esc(s.v.mailFrom)}</p>`+
    work('Googleの画面で行うこと','<ol><li>上のアドレスのGoogleアカウントを開きます。複数のアカウントを使っている場合は、右上のアカウントを確認します。</li><li>「セキュリティ」または「セキュリティとログイン」から「2段階認証プロセス」を開きます。</li><li>未設定ならGoogleの案内に沿って設定し、この画面へ戻ります。</li></ol>')+
    `<p><a class="guide-link" href="https://support.google.com/accounts/answer/185839?hl=ja" target="_blank" rel="noreferrer">Google公式：2段階認証の設定手順</a></p>`+
    check('googleReady','送信元のアカウントで2段階認証が有効になっています','上に表示された送信元のGoogleアカウントで確認します。')+
    `<details><summary>Googleの設定を自分で変更できない場合</summary><p>園が管理するアカウントは、管理担当者と進めてください。「担当者に相談する」から、準備してほしい内容を表示できます。</p></details>`+mailFoot('アプリパスワードの準備へ');
  if(n===3)return mailHead('保育ICT用のアプリパスワードを用意します','Googleで発行する、16文字の接続用パスワードです。この導入アプリのGmail送信に使います。')+
    work('Googleの画面で行うこと',`<ol><li><a class="guide-link" href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer">Googleのアプリパスワード画面</a>を開き、${esc(s.v.mailFrom)} のアカウントであることを確認します。</li><li>アプリ名に「オープン保育ICT」など、用途が分かる名前を付けて作成します。</li><li>表示されたアプリパスワードを、下の欄へ入力します。</li></ol>`)+
    `<div class="fields">${input('smtpPassword','Gmailのアプリパスワード','password','普段のGoogleログイン用パスワードは入力しません。画面を閉じると再入力が必要です。')}</div>`+
    `<details><summary>「アプリパスワード」が表示されない・作れない場合</summary><p>2段階認証の状態と、ログインしているアカウントを確認します。組織のアカウント、セキュリティキーだけでの2段階認証、高度な保護機能などにより利用できない場合があります。</p><p>園の管理者に確認するか、使える別の送信方法を相談してください。</p><a class="guide-link" href="https://support.google.com/accounts/answer/185833?hl=ja" target="_blank" rel="noreferrer">Google公式：アプリパスワードの説明</a></details>`+
    `<details><summary>自動入力した接続情報を見る</summary><dl class="review-list">${row('SMTPサーバー',s.v.smtpHost)}${row('接続ポート',s.v.smtpPort)}${row('暗号化','STARTTLS')}${row('ログインID',s.v.smtpUser)}${row('送信元',s.v.mailFrom)}</dl></details>`+mailFoot('確認メールの送信へ');
  return mailHead('確認メールを受け取ってみましょう','自分で開けるメールアドレスへ1通送り、届いたことを確認します。宛先は送信元と同じアドレスでも構いません。')+
    `<dl class="review-list">${row('送信元',s.v.mailFrom)}${row('件名','オープン保育ICT：導入時の確認メール')}</dl><div class="fields">${input('testRecipient','確認メールの送信先','email','この欄に入力した宛先だけに確認メールを送ります。')}</div>${button('mail-same-recipient','送信元と同じアドレスにする','secondary')}`+
    `<div class="inline-action">${button('mail-test','確認メールを送る','primary')}</div>${mailResult()}`+
    `<p class="subtle">確認メールは、上に入力した宛先へ1通送ります。</p>`+
    check('mailReceived','確認メールを受信できました','受信トレイと迷惑メールフォルダーを確認し、届いたらチェックを付けます。')+
    `<details><summary>受信できないときは</summary><p>入力した宛先に誤りがないか確認し、迷惑メールフォルダーも見てください。送信失敗の場合は、表示された原因を確認して再試行します。</p><p>Googleの通常のパスワードを変更すると、発行済みのアプリパスワードは無効になります。その場合は新しく発行して設定し直します。</p></details>`+mailFoot('バックアップの設定へ');
}
function mailResult(){return `<div id="mail-result">${mailResultBody()}</div>`;}
function mailResultBody(){
  if(s.mailError==='auth'&&s.v.mailProvider==='gmail')return `<div class="result error" role="alert"><strong>Gmailへの接続が認められませんでした</strong><p>送信元のアカウントで作ったアプリパスワードか確認してください。通常のログイン用パスワードでは接続できません。</p>${button('mail-fix-password','アプリパスワードの説明へ戻る','secondary')}</div>`;
  if(s.mailError==='connection')return `<div class="result error" role="alert">メールサーバーへ接続できませんでした。インターネット接続と、送信用メールへの接続が許可されているか確認します。</div>`;
  return checkResult('mail','メールサーバーが確認メールを受け付けました');
}
function setMailProvider(provider){
  const old=s.v.mailProvider;
  if(old===provider)return;
  if(old)s.mailDrafts[old]=Object.fromEntries(mailKeys.map(k=>[k,s.v[k]]));
  const draft=s.mailDrafts[provider];
  if(draft)Object.assign(s.v,draft);
  else if(provider==='gmail')Object.assign(s.v,{smtpHost:'smtp.gmail.com',smtpPort:'587',smtpUser:'',smtpPassword:'',mailFrom:'',testRecipient:'',googleReady:false});
  else Object.assign(s.v,{smtpHost:'',smtpPort:'587',smtpUser:'',smtpPassword:'',mailFrom:'',testRecipient:'',googleReady:false});
  s.v.mailProvider=provider;s.v.mailReceived=false;delete s.checks.mail;s.mailError='';
}
function validateMailInput(){
  if(!required(['smtpHost','smtpPort','mailFrom','testRecipient']))return false;
  for(const key of ['mailFrom','testRecipient'])if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.v[key]))return fail('メールアドレス全体を入力してください。',key);
  if(!portOK(s.v.smtpPort))return fail('接続ポートを1〜65535の範囲で指定してください。','smtpPort');
  if(s.v.mailProvider==='gmail'){
    if(!s.v.googleReady||s.v.smtpPassword.replace(/ /g,'').length!==16)return fail('Google側の準備と、16文字のアプリパスワードを確認してください。');
    s.v.smtpPassword=s.v.smtpPassword.replace(/ /g,'');
  }else if(s.v.smtpUser&&!s.v.smtpPassword)return fail('ログインIDを指定した場合は、メールのパスワードも入力してください。','smtpPassword');
  return true;
}
function mailHelp(){
  document.querySelector('#help-title').textContent='メール担当者に渡す相談内容';
  document.querySelector('#help-text').value=[
    'オープン保育ICTから登録案内やパスワード再設定メールを送るための設定について相談します。',
    `送信方法：${s.v.mailProvider==='gmail'?'Gmail／Google Workspace':'ほかのメール（または未選択）'}`,
    `送信元：${s.v.mailFrom||'未定'}`,
    s.v.mailProvider==='gmail'?'送信元のGoogleアカウントで、2段階認証とアプリパスワードを利用できるか確認してください。':'STARTTLS対応のSMTPサーバー、ポート、ログインIDと認証方法を教えてください。',
    '利用できない場合は、この導入アプリで使える送信方法を相談したいです。',
    'パスワードやアプリパスワードは、この依頼文には記載しません。'
  ].join('\n');document.querySelector('#help-dialog').showModal();
}
