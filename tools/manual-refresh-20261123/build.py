"""Refresh the four reviewed manual topics; retain unrelated published guides."""
from pathlib import Path
from html import escape
import json,re,subprocess
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
DOCS=ROOT/'docs'; GUIDE=DOCS/'manual-guide-preview'; ASSETS=GUIDE/'assets'
DEST=GUIDE/'refresh-20261123'; DEST.mkdir(exist_ok=True)
def size(name):
 with Image.open(ASSETS/(name+'.jpg')) as im:return list(im.size)
def picture(name,caption,prefix='../assets/'):
 name='r2-'+name;w,h=size(name);src=prefix+name+'.jpg'
 return f'<figure><a href="{src}" aria-label="{escape(caption)}（画像を拡大）"><img src="{src}" width="{w}" height="{h}" alt="{escape(caption)}" loading="lazy"></a><figcaption>{caption}</figcaption></figure>'
def step(title,text,image,note='',**kw):
 return dict(title=title,text=text,image='r2-'+image,alt=title+'。架空データの現在の画面。',note=note,calls=[],**kw)
def section(key,title,texts,photos=()):return key,title,''.join('<p>'+x+'</p>' for x in texts)+''.join(picture(*x) for x in photos)
def page(slug,title,intro,sections):
 nav=''.join(f'<li><a href="#{k}">{t}</a></li>' for k,t,_ in sections)
 body=''.join(f'<section class="panel" id="{k}"><h2><span class="step">{i}</span>{t}</h2>{b}</section>' for i,(k,t,b) in enumerate(sections,1))
 (DEST/(slug+'.html')).write_text(f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,follow">
<title>{title}｜画面付きの使い方ガイド</title><link rel="stylesheet" href="../plans/style.css"><link rel="stylesheet" href="../plans/forms.css"></head>
<body><main id="top"><header><a href="../index.html#home">使い方ガイド</a><a href="index.html">今回更新した手順</a></header>
<h1>{title}</h1><p class="intro">{intro}</p><nav class="contents" aria-label="このページの目次"><strong>このページでできること</strong><ul>{nav}</ul></nav>
<p class="shot-note">2026年11月23日更新。画面の人物・記録はすべて架空です。画像を押すと拡大できます。</p>{body}
<nav class="foot"><a href="index.html">今回更新した手順へ</a><a href="#top">このページの先頭へ</a></nav></main></body></html>''',encoding='utf-8')

path=GUIDE/'app.js';js=path.read_text(encoding='utf-8')
mark='const manualArticles = ';start=js.index(mark)+len(mark);end=js.index('\n};',start)+2
node='C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/bin/node.exe'
articles=json.loads(subprocess.check_output([node,'-e',"const fs=require('fs'),vm=require('vm');process.stdout.write(JSON.stringify(vm.runInNewContext('('+fs.readFileSync(0,'utf8')+')')));"],input=js[start:end].encode('utf-8')))
contact=articles['parent-app-contact']
contact['keywords']+=' 夕食 朝食 食欲 緊急連絡先 連絡順 いつもどおり'
contact['steps']=[
 step('日付とお子さまを確かめて開きます','ホームの日付を確かめ、連絡するお子さまの「日次連絡を入力」を押します。送信済みなら「日次連絡を編集」を押します。','contact-entry','兄弟姉妹がいる場合も、お子さま一人ずつ入力します。別の日を選んだら「日付を変更」を押してください。'),
 step('出席と、当日の緊急連絡先を確かめます','園に行く日は「出席」を選びます。緊急連絡先が同じなら「いつもどおり」、違う日は「今日は変更する」を選び、連絡先と順番を確かめます。','contact-emergency','当日の変更は、このお子さまのこの日だけに保存されます。ほかの日・兄弟姉妹・いつもの連絡順は変わりません。いつもの連絡先が未登録なら、画面の案内から先に登録できます。'),
 step('お迎え予定、体温、睡眠などを入れます','お迎えの予定が分かっていれば入れます。続けて体温、就寝・起床、睡眠メモなどを入力します。','contact-care','園の設定によって表示される項目が異なります。画面に出ている項目を入力してください。お休みする日は「欠席」の手順を使います。'),
 step('前日の夕食と、当日の朝食を分けて入れます','それぞれの日付を確かめ、食欲を「旺盛・普通・あまりない・ない」から選びます。「食べたもの」に内容を書きます。選び直すときは別の食欲を選び、未選択に戻すときは「選択を消す」を押します。','contact-meals','夕食は前日、朝食は連絡する当日です。画面に出ている日付を見て入力してください。'),
 step('下まで確かめて「保存する」を押します','排便、機嫌、咳・鼻水、服薬、体調メモなど、表示されている欄を確認します。最後の「園への連絡事項」に必要なことを書き、「保存する」を押します。','contact-filled','入力しただけでは送信されません。「戻る」で離れる前に保存してください。'),
 step('保存できたことを確かめます','「日次連絡を保存しました。」と出たことを確かめ、お子さまの欄の送信内容を見ます。間違いは同じ日付の「日次連絡を編集」から直し、保存し直します。','contact-saved','出席予定の連絡だけでは登園の受付はされません。急いで伝えたい変更は園にも連絡してください。'),
 step('未入力・入力済み・エラーの見本','下の切り替えで画面全体を確認できます。エラーが出たら案内のある欄を確かめます。','contact-filled','見本の体温は架空の入力例です。画面に出ている上限以上で出席として送れない場合、数値を低く書き換えず園へ連絡してください。',imagePrefix='r2-contact',states=[['empty','未入力'],['filled','入力済み'],['error','エラーの例']],stateNotes={'empty':'入力前の画面です。','filled':'この日だけの連絡先と、前日夕食・当日朝食を含む入力例です。','error':'出席として送れない体温の案内が出た例です。保存前の内容を確認してください。'},stateCalls={'empty':[],'filled':[],'error':[]})]
contact['faq'].append(['項目が見本と違います','園の設定によって項目が表示されない場合があります。入力したい欄がないときは園へ確認してください。']) if not any('見本と違' in x[0] for x in contact['faq']) else None
pickup=articles['parent-app-pickup'];pickup['keywords']+=' 閉園 1分 単位 選べない'
pickup['steps']=[
 step('日付とお子さまを確かめて開きます','ホームで予定を入れる日とお子さまの名前を確かめ、「お迎え予定を登録・変更」を押します。','contact-entry','予定はお子さま・日付ごとに登録します。登園前にも入力できます。'),
 step('閉園より前の時刻を選びます','時と分を選び、上の「選択中」を確かめます。閉園時刻が設定されている場合、その時刻より前だけ選べます。18:30閉園の例では18:30は選べません。','pickup-filled','15分刻み以外は「その他の分を選ぶ」を開きます。画像は1分単位で18:29を選んだ例です。実際の閉園時刻は画面の案内を確認してください。',imagePrefix='r2-pickup',states=[['empty','未入力'],['partial','途中まで'],['filled','入力済み'],['outside','設定変更後の例']],stateNotes={'empty':'時刻・迎えに来る人・補食を選ぶ前の画面です。','partial':'18時だけを選んだ例です。分も選びます。','filled':'閉園18:30より前の18:29、母、補食不要を選んだ例です。','outside':'閉園が18:00に変わり、以前の18:29が範囲外になった例です。新しい閉園時刻より前の時と分を選び直してください。'},stateCalls={'empty':[],'partial':[],'filled':[],'outside':[]}),
 step('来る人と補食を選び、保存します','お迎え予定の人と、補食が必要か不要かを選び、「予定を保存」を押します。「その他」の人が来る場合は、どなたが来るか園にも伝えてください。','pickup-filled','「ホームへ戻る」だけでは今回の変更は保存されません。補食は園の案内に合わせて選びます。'),
 step('開き直して保存した予定を確かめます','同じ日付の「お迎え予定を登録・変更」をもう一度開き、時刻・来る人・補食が残っているか見ます。変更するときも選び直して「予定を保存」を押します。','pickup-reopen','園が閉園時刻を変更した場合は、以前の時刻が範囲外になることがあります。そのまま再保存せず、選べる時刻を選び直します。予定の登録だけでは登園・降園の受付はされません。')]
pickup['faq'].append(['時刻が選べません','閉園より前の時刻を選びます。1分単位は「その他の分を選ぶ」です。時刻の設定が実際の予定と合わないときは園へ確認してください。']) if not any('時刻が選べ' in x[0] for x in pickup['faq']) else None
history=articles['parent-app-history']
history['steps'][2].update(image='r2-parent-reply',alt='職員が公開した返信の表示。架空データの例。',calls=[])
for key in ['parent-app-contact','parent-app-pickup','parent-app-history']:
 start=js.index('  "'+key+'": {');end=js.index('\n  },',start)+4
 replacement='  "'+key+'": '+json.dumps(articles[key],ensure_ascii=False,indent=2).replace('\n','\n  ')
 js=js[:start]+replacement+js[end:]
mark='const screenshotSizes = ';start=js.index(mark)+len(mark);sizes,length=json.JSONDecoder().raw_decode(js[start:])
sizes.update({p.stem:size(p.stem) for p in ASSETS.glob('r2-*.jpg')});js=js[:start]+json.dumps(sizes,ensure_ascii=False)+js[start+length:]
extra=[
 dict(chapter=1,title='保護者の連絡を受け取り、返信する',href='refresh-20261123/daily-contact.html',summary='食事・当日の連絡先を確かめ、返信を下書き保存・公開する。',keywords='日次連絡 返信 食事 夕食 朝食 緊急連絡先 公開'),
 dict(chapter=2,title='基本医療情報を保護者に依頼し、回答を確認する',href='refresh-20261123/medical.html',summary='保護者への記入依頼、回答の比較、書き直し依頼と反映。',keywords='健康 医療 依頼 承認 差し戻し レントゲン'),
 dict(chapter=5,title='請求を取消して修正する・口座情報を保存する',href='refresh-20261123/billing.html',summary='銀行提出前の取消、同月の修正・再出力、家族口座の管理。',keywords='請求 口座 Zengin 取消 再出力 写真代')]
mark='const recentGuides = ';start=js.index(mark)+len(mark);recent,length=json.JSONDecoder().raw_decode(js[start:]);recent=[x for x in recent if not x['href'].startswith('refresh-20261123/')]+extra
js=js[:start]+json.dumps(recent,ensure_ascii=False,indent=2)+js[start+length:];path.write_text(js,encoding='utf-8')
entry=GUIDE/'index.html';entry.write_text(re.sub(r'app\.js\?v=[^"\s]+','app.js?v=20261123-manual-refresh',entry.read_text(encoding='utf-8')),encoding='utf-8')

page('daily-contact','保護者の連絡を受け取り、返信する','職員メニューの「日次連絡」から、その日の家庭からの連絡を確認します。返信は編集できる職員が行います。',[
 section('open','日付・園児を確かめる',['「日次連絡」を開き、日付とクラスを確かめます。対象の園児の詳細を開いてください。'],[('daily-list','日次連絡の一覧。日付と園児を確かめます。')]),
 section('read','家庭からの連絡を読む',['「家庭からの連絡」で、提出者・更新日時・出席や欠席、体温などを読みます。夕食は前日、朝食は当日として、それぞれの食欲と食べたものを確認します。','この日の緊急連絡先が回答されている場合は、その園児・その日付の連絡順を使います。通常の連絡先や兄弟姉妹の連絡先と取り違えないよう、名前と日付を確かめます。園の連絡項目設定によって「対象外」と出る項目もあります。'],[('daily-received','家庭からの連絡と、その日の連絡順の例。')]),
 section('draft','園からの連絡を書いて下書き保存する',['「園からの連絡」に、表示されている食事・睡眠などの項目と「連絡メモ」を入力します。途中で保存する場合は「下書き保存」を押します。下書きは保護者には公開されません。','「未送信」や「未送信の変更あり」を確認します。公開済みの返信を書き直して下書き保存した場合、保護者には前に公開した内容が引き続き表示されます。'],[('daily-reply','返信欄と「下書き保存」「保護者に公開」。')]),
 section('publish','確認画面を見て保護者に公開する',['「保護者に公開」を押し、園児名・日付・返信内容を見直します。「修正に戻る」で入力に戻れます。「公開する」を押すと保護者が読めるようになります。','公開後に「公開済み」を確かめます。保護者は日次連絡や履歴から返信を読めます。内容を直した場合は、もう一度確認して公開します。'],[('daily-confirm','内容を見直して「公開する」を押します。'),('parent-reply','保護者に表示された返信の例。')])])

page('medical','基本医療情報を保護者に依頼し、回答を確認する','健康プロフィールから、対象の保護者に記入を依頼できます。依頼は編集できる職員、回答の反映と書き直し依頼は園児台帳の管理権限を持つ職員が行います。',[
 section('open','健康プロフィールから回答の画面へ進む',['健康管理で園児を選び、健康サマリーから「健康プロフィール」を開きます。「保護者への記入依頼・回答の確認」を押してください。'],[('profile-entry','健康プロフィール上部にある、依頼・回答確認への入口。')]),
 section('request','宛先を選んで記入をお願いする',['園児名を確かめ、紐付いている保護者を「宛先」で選び、「記入をお願いする」を押します。依頼は選んだ保護者のホームに表示されます。','有効な保護者アカウントがない場合はその旨が表示されます。園児と保護者の登録を確認してください。別の園児の保護者を宛先にすることはできません。'],[('medical-request','園児名と宛先を確かめて記入を依頼します。')]),
 section('review','現在の内容と回答を見比べる',['回答が届いたら、同じ画面の「依頼と回答の履歴」を開きます。「園で確認中」の回答について、「現在の内容」と「保護者からの回答」を比較します。','血液型、かかりつけ医の名前・電話・住所、希望する搬送先と電話番号を確認します。レントゲン撮影の回答は、画面に表示される質問の条件と回答を一緒に読みます。未回答は事前承諾として扱いません。','保護者が送信しただけでは健康プロフィールに反映されません。兄弟姉妹にも自動で転記されません。'],[('medical-review','「現在の内容」と「保護者からの回答」を比較します。')]),
 section('return','聞き直すときは理由を書いて返す',['「書き直してほしい内容」に確認したい点を書き、「書き直しをお願いする」を押します。理由は必須です。保護者は画面に出るお願いを読み、書き直して回答できます。','この操作では台帳を更新しません。再回答が届いたら、もう一度内容を比較してください。'],[('medical-return','電話番号の確認をお願いする例。')]),
 section('approve','確認した回答を反映する',['内容を確認できたら「確認して反映する」を押します。履歴の確認者・日時を確かめ、健康プロフィールを開いて反映された値を確認します。','ほかの職員などが先に台帳を変更した場合は、そのまま上書きせず画面を開き直して比較します。反映や書き直しのボタンが出ない場合は、園児台帳を管理できる職員へ依頼してください。'],[('medical-approved','確認済みの履歴には、確認した職員と日時が残ります。'),('profile-consent','健康プロフィールで園が確認した回答を確かめます。')])])

page('billing','請求を取消して修正する・口座情報を保存する','Zengin作成後でも、銀行へ提出する前で取消条件を満たしていれば、管理者が同じ月の請求を修正できます。口座情報の管理は、管理者または請求・口座情報管理権限を持つ職員が行います。',[
 section('open','請求月と出力を確かめる',['職員メニューの「請求入力」を開き、対象の月とZengin出力を確認します。管理者に「取消して修正」が表示されている場合、その出力の確認画面を開けます。','銀行に提出済みのファイルは、この操作で銀行側から取り消せません。銀行提出履歴・結果取込・支払済み明細など、取消対象外の状態では修正解除できません。'],[('billing-home','請求月と出力履歴から対象を確かめます。')]),
 section('cancel','理由と銀行未提出を確認して取り消す',['「取消して修正」を押し、対象月・出力を見直します。取消理由を記入し、実際に銀行へ提出していないことを確認してチェックを付けます。','「戻る」なら取消しません。「取消して修正へ進む」を押すと出力を取り消し、同じ月の園児別入力へ進みます。'],[('billing-confirm','理由と銀行未提出を確認した例。')]),
 section('edit','金額を直して保存する',['対象の園児と費目を確認し、編集できる欄の金額を修正して「保存」を押します。画像は写真代を300円から500円へ直す例です。入力中は、保存済みの合計や明細が元の金額のままの場合があります。','自動転送された明細など、直接変更できない欄は取消後も編集できません。該当する元の処理を確認してください。保存せずに画面を離れると入力中の変更は反映されません。'],[('billing-edit','同じ月の写真代を修正して「保存」を押します。')]),
 section('account','家族の口座情報を確認・保存する',['「園児別入力」の「請求詳細」、または請求一覧の「口座情報管理」から対象を開きます。「家族口座情報の編集」で支払方法、口座振替状態、銀行・支店、口座種別・番号・名義、新規コード、受領日、備考などの欄を確認します。','口座は家族単位です。対象の園児と家族を確かめて「口座情報を保存」を押し、開き直して保存内容を確認します。入力だけでは保存されません。権限がない場合は管理できる職員へ依頼してください。'],[('billing-account','家族口座情報の12項目と保存ボタン。')]),
 section('recreate','保存した内容でZenginを再作成する',['「請求一覧へ戻る」で対象月を確かめ、「Zengin作成」を押します。新しい出力の作成日時・金額と、旧出力が「取消済み」になったことを確認してください。','旧出力の履歴には元の金額・取消理由・操作した職員などが残ります。取消済みの出力は再利用できません。必要なファイルは新しく作成した出力から取得します。'],[('billing-recreate','修正を保存した後、対象月の「Zengin作成」を押します。'),('billing-recreated','新しい出力と、取消済みの旧出力が別に残ります。')])])

items=[('../index.html#article/parent-app-contact','日次連絡を送る','保護者向け。夕食・朝食、当日の連絡先、保存。'),('../index.html#article/parent-app-pickup','お迎え予定を入れる・変える','保護者向け。閉園前の時刻と1分単位の選択。'),('../health/index.html','健康管理で園児を探す','一覧の現行画面を確認。'),('../health/profile/index.html','健康プロフィールを書く','現在の搬送先の欄名、保護者の回答を確認。')]+[(x['href'].split('/')[-1],x['title'],x['summary']) for x in extra]
page('index','古い説明と画面を更新した手順','公開済みの資料を現在の操作に合わせて更新しました。保護者・職員それぞれの手順を選んでください。',[section('guides','更新した手順',[f'<a href="{url}">{title}</a> — {desc}' for url,title,desc in items])])

# Refresh only the reviewed health sections; retain the other three health guides.
p=GUIDE/'health/profile/index.html';s=p.read_text(encoding='utf-8')
s=s.replace('「<strong>かかりつけ医</strong>」と「<strong>緊急搬送先</strong>」には、それぞれに対応する電話番号の欄があります。','「<strong>かかりつけ医</strong>」と電話番号・住所、「<strong>希望する搬送先（任意）</strong>」と搬送先電話番号を確認します。')
s=re.sub(r'<figure>.*?profile-basic\.jpg.*?</figure>',picture('profile-basic','現在の基本医療情報。希望する搬送先は任意の欄です。','../../assets/'),s,count=1)
if 'id="parent-answer"' not in s:
 s=s.replace('<li><a href="#flags">','<li><a href="#parent-answer">保護者へ記入を依頼する・回答を確認する</a></li><li><a href="#flags">')
 s=s.replace('<section class="panel" id="flags">','<section class="panel" id="parent-answer"><h2>保護者へ記入を依頼する・回答を確認する</h2><p>上部の「<strong>保護者への記入依頼・回答の確認</strong>」から依頼や回答の比較に進めます。保護者の送信だけでは反映されず、園児台帳を管理できる職員が確認して反映します。</p><p><a href="../../refresh-20261123/medical.html">記入依頼・回答確認・書き直しの画面付き手順</a></p>'+picture('profile-consent','保護者の回答と、園での確認状況を見ます。','../../assets/')+'</section><section class="panel" id="flags">')
s=s.replace('画面は架空の園児の記録です。','2026年11月23日更新。画面は架空の園児の記録です。');p.write_text(s,encoding='utf-8')
p=GUIDE/'health/index.html';s=p.read_text(encoding='utf-8')
for old,new,caption in [('overview','health-overview','現在の健康管理一覧。表示中の人数と園児の行を確認します。'),('filter','health-filter','「アラート」で「対応が必要のみ」、検索で「あおい」を指定した例。')]:
 s=re.sub(r'<figure>.*?images/'+old+r'\.jpg.*?</figure>',picture(new,caption,'../assets/'),s,count=1)
s=s.replace('画面は架空の園児の記録です。','2026年11月23日更新。画面は架空の園児の記録です。');p.write_text(s,encoding='utf-8')

# Keep the text-only parent guide in agreement with the screenshot guide.
p=DOCS/'parent-app-manual.md';s=p.read_text(encoding='utf-8')
for key in ['parent-app-contact','parent-app-pickup']:
 a=articles[key];title=a['title'];link=f'manual-guide-preview/index.html#article/{key}'
 headings=list(re.finditer(r'^## .+$',s,re.M));idx=next(i for i,h in enumerate(headings) if link in s[h.start():headings[i+1].start() if i+1<len(headings) else len(s)])
 begin=headings[idx].start();end=headings[idx+1].start() if idx+1<len(headings) else len(s)
 body=f'## {title}\n\n{a["summary"]}\n\n[この手順をスクショ付きで読む]({link})\n\n'
 body+='\n\n'.join(f'{i}. **{x["title"]}** {x["text"]} {x["note"]}' for i,x in enumerate(a['steps'],1))+'\n\n'
 body+='**困ったとき**\n\n'+'\n'.join('- **'+q+'** '+ans for q,ans in a['faq'])+'\n\n';s=s[:begin]+body+s[end:]
p.write_text(s,encoding='utf-8')
p=DOCS/'extended-care-billing-transfer-spec.md';s=p.read_text(encoding='utf-8').replace('合意・実装した（実機未配備）','合意・実装し、同日13:06 JSTに実機へ配備した')
if 'refresh-20261123/billing.html' not in s:s=s.replace('- 文書バージョン:', '2026-11-23更新：[取消・修正・再出力と口座管理の画面付き手順](manual-guide-preview/refresh-20261123/billing.html)を追加し、冒頭の配備状態を訂正しました。[更新・確認記録](spec-decisions.md#sd-070)。\n\n- 文書バージョン:')
p.write_text(s,encoding='utf-8')
print('Updated parent articles, text guide, 2 health pages, 3 new staff guides, index, billing note')
