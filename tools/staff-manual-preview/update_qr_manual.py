"""Apply the QR-first editorial correction without changing business screens."""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def read(name):return json.loads((HERE/name).read_text(encoding='utf-8'))
def write(name,data):(HERE/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

a=read('admission_articles.json')
invite=a.pop('child-new-family',a.get('child-new-invite'))
invite.update(title='個別に案内する：園児・家族がまだ未登録の場合',tag='補助の手順／個別招待',
    summary='基本の受付は共通QRです。園から特定の保護者へ直接案内するときは、この個別招待を使います。園児・家族がまだ登録されていない家庭が対象です。',
    relatedArticles=['parent-qr','child-sibling','parent','child'])
invite['steps'][2]['note']=invite['steps'][2]['note'].replace('別途招待が必要です','本人のメールアドレスで別途申請または招待が必要です')
invite['steps'][-1]['note']=invite['steps'][-1]['note'].replace('別途招待します','別途申請または招待を案内します')
a['child-new-invite']=invite
s=a['child-sibling']
s['summary']='先に既存の家族と保護者アカウントを確認します。新入園児を同じ家族へ追加し、利用中の保護者には閲覧対象を追加します。初めてアカウントを作る保護者だけ、共通QRで受け付けます。'
s['before']+=' 保護者がすでにアカウントを持っているかも確認します。利用中・停止中・初回手続き中で対応が異なります。'
s['steps'][0]['text']+=' 「保護者アカウント」で本人の登録・利用状態も確認します。利用中ならQRで再申請せず、後半の閲覧対象の追加へ進みます。'
# Idempotent for later rebuilds.
s['steps'][0]['text']=s['steps'][0]['text'].replace(' 「保護者アカウント」で本人の登録・利用状態も確認します。利用中ならQRで再申請せず、後半の閲覧対象の追加へ進みます。'*2,' 「保護者アカウント」で本人の登録・利用状態も確認します。利用中ならQRで再申請せず、後半の閲覧対象の追加へ進みます。')
s['steps'][5]={
    'title':'アカウントがない保護者だけ、共通QRで受け付ける',
    'text':'本人のアカウントがまだなければ、共通QRの手順で申請・入力を案内します。園が承認するときは、「承認先の園児・保護者」で、この手順で同じ家族へ登録した新入園児と保護者本人を選びます。',
    'image':'qr-review-existing',
    'alt':'共通QR申請の承認欄。登録済みの新入園児と保護者本人を承認先に選んだ例。',
    'calls':['新入園児と本人の組み合わせを選びます。上の兄弟姉妹を代わりに選びません。','本人と内容を確認した理由を残します。','園児・保護者の対応と提出内容を確認してチェックします。','確認後に「承認」で反映します。'],
    'note':'「台帳にいないため、新しい園児・家族を登録する」は選びません。既存の家族と分かれてしまいます。候補が出ない場合は、家族・保護者欄・既存アカウントを管理者へ確認します。利用中・停止中・手続き中のアカウントを新しく作り直しません。'
}
s['steps']=s['steps'][:6]+[{
    'title':'保護者に、新しいお子さまが見えるか確認してもらう',
    'text':'既存アカウントを使う方はログイン後の画面を開き直し、新しく入園するお子さまが表示されるか確認してもらいます。初回登録の方は園の承認後のメールからパスワードを設定し、ログインして確認します。',
    'note':'もう1人の保護者が利用する場合も、その本人のアカウントと閲覧対象を別々に確認します。共通QRの詳しい流れは下の関連手順にあります。'
}]
s['relatedArticles']=['parent-qr','parent','child']
s['faq']=[item for item in s['faq'] if item[0]!='共通QRから申請してもらった場合は？']+[
    ['共通QRから申請してもらった場合は？','先に新入園児を既存の家族へ登録し、承認先にその園児と保護者本人を選びます。申請するお子さまの氏名・生年月日と一致する必要があり、兄弟姉妹を代わりに選ぶことはできません。すでに本人のアカウントがある場合は、承認前に管理者へ確認します。']]
write('admission_articles.json',a)
r=read('registration_articles.json')
r['parent']['title']='個別に案内する：登録済み園児の保護者を招待する'
r['parent']['tag']='補助の手順／個別招待'
r['parent']['summary']='基本の受付は共通QRです。園から本人を指定して案内するときは、登録済みの園児・保護者を選んで個別招待します。'
r['parent']['relatedArticles']=['parent-qr','child-sibling','child-new-invite']
write('registration_articles.json',r)

p=HERE/'build_registration_articles.py';t=p.read_text(encoding='utf-8')
t=t.replace('articles={**admissions,**articles}',"articles={**admissions,**json.loads((HERE/'qr_article.json').read_text(encoding='utf-8')),**articles}")
t=t.replace("['child-sibling','child-new-family','parent']","['parent-qr','child-sibling','parent']")
t=t.replace('==43','==57').replace("article['imagePrefix']+'-'+state","step.get('imagePrefix',article['imagePrefix'])+'-'+state")
t=t.replace('Built 5 registration articles; 8 articles and 43 screenshots total.','Built 6 registration articles; 9 articles and 57 screenshots total.')
p.write_text(t,encoding='utf-8')

p=HERE/'dist/app.js';t=p.read_text(encoding='utf-8')
t=t.replace("const prefix=a.imagePrefix||", "const prefix=s.imagePrefix||a.imagePrefix||")
t=t.replace("let [page,arg]=parts;", "let [page,arg]=parts;if(page==='article'&&arg==='child-new-family')arg='parent-qr';")
# Update existing navigation in addition to its reusable builder.
t=t.replace("['child-sibling','child-new-family']","['child-sibling','parent-qr']")
t=t.replace("'#article/child-new-family'","'#article/parent-qr'")
t=t.replace('保護者へ初回入力を依頼し、園が確認して登録する','共通QRで申し込み、園が確認・承認する')
t=t.replace('新入園児の2つの登録手順を含む8つの場面','共通QRの受付と新入園児の登録を含む9つの場面').replace('画面付きの手順があるのは8例','画面付きの手順があるのは9例')
p.write_text(t,encoding='utf-8')
p=HERE/'build_admission_navigation.py';t=p.read_text(encoding='utf-8')
t=t.replace('child-new-family','parent-qr').replace('保護者へ初回入力を依頼し、園が確認して登録する','共通QRで申し込み、園が確認・承認する')
t=t.replace('新入園児の2つの登録手順を含む8つの場面','共通QRの受付と新入園児の登録を含む9つの場面').replace('画面付きの手順があるのは8例','画面付きの手順があるのは9例')
t=t.replace('モック v1.4','モック v1.5').replace('画面付きの手順：新入園2通りを含む8例','画面付きの手順：共通QR・新入園児など9例')
p.write_text(t,encoding='utf-8')
p=HERE/'dist/index.html';t=p.read_text(encoding='utf-8').replace('モック v1.4','モック v1.5').replace('画面付きの手順：新入園2通りを含む8例','画面付きの手順：共通QR・新入園児など9例')
if 'href="#article/parent-qr"' not in t:t=t.replace('<p class="nav-label">業務別の目次</p>','<a href="#article/parent-qr" class="nav-main">共通QRで受付する <span>→</span></a>\n        <p class="nav-label">業務別の目次</p>')
p.write_text(t,encoding='utf-8')
p=HERE/'ui-labels.js';t=p.read_text(encoding='utf-8')
t=t.replace("'まだ園児台帳にいない子どもの新規入園受付']","'まだ園児台帳にいない子どもの新規入園受付','共通QR・申請受付','新しい申請の受付を開始する','新しい申請の受付を停止する','案内を印刷','QR画像を保存','登録案内メールを受け取る']")
t=t.replace("'閲覧を許可する園児']","'閲覧を許可する園児','保護者ご本人のメールアドレス','承認先の園児・保護者']")
p.write_text(t,encoding='utf-8')
for name in ['publish_assets.py','build_standalone.py']:
 p=HERE/name;t=p.read_text(encoding='utf-8').replace('43','57').replace('47','61').replace('20261103-v6','20261103-v7').replace('v1.4','v1.5');p.write_text(t,encoding='utf-8')
print('Updated the common-QR primary route and preserved individual invitation alternatives.')
