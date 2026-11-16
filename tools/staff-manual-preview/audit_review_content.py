"""Apply SD-025 corrections to source articles and numbered screenshot explanations."""
from pathlib import Path
import json
import re

HERE=Path(__file__).resolve().parent
CALLS={
 'app-contact-top':['園に行く日は「出席」を選びます。'],
 'app-contact-care':['測った体温を入れます。','寝た時刻を入れます。右の「起床」には起きた時刻を入れます。'],
 'app-contact-bottom':['園へ伝えたいことを書きます。','内容を確かめて「保存する」を押します。'],
 'app-home-saved':['「日次連絡を保存しました。」と出たことを確かめます。','お子さまの名前を確かめ、その下に出ている送信済みの内容を見ます。'],
 'app-menu':['「メニュー」を開き、「日次連絡履歴」を選びます。'],
 'app-reply':['「園からの返信」を読みます。返信の日時と、誰からの返信かも確かめられます。'],
 'app-pickup-empty':['お迎えの時と分を選び、上の「選択中」の時刻を確かめます。','お迎えに来る人を選びます。','補食が必要か、不要かを選びます。'],
 'app-pickup-save':['内容を確かめて「予定を保存」を押します。'],
 'app-pickup-reopen':['予定を確認するお子さまの名前です。下に日付も出ています。','保存した予定時刻が出ています。例は16:30です。','保存したお迎えの人です。例は母です。','保存した補食の選択です。例は不要です。'],
 'parent-password':['本人が新しいパスワードを入力します。','同じパスワードをもう一度入力します。','「パスワードを設定する」を押して設定を終えます。'],
 'qr-settings-closed':['園の申請ページのアドレスを確認します。画像のアドレスは説明用です。','「新しい申請の受付を開始する」を押します。'],
 'qr-settings-open':['「案内を印刷」で配布用の案内を印刷します。','画像として配る場合は「QR画像を保存」を押します。'],
 'qr-apply-filled':['保護者本人のメールアドレスを入れます。','「登録案内メールを受け取る」を押します。'],
 'qr-form-filled':['入園するお子さまの情報を入れます。','保護者本人の情報を入れます。','もう1人の保護者の情報も必要な場合は、ここを開きます。','内容を確かめて「入力内容を園に提出する」を押します。'],
 'qr-review-new':['新しい園児として登録するか、登録済みの園児とひもづけるかを確かめます。','確認した内容や、判断の理由を記入します。','申請者とお子さまの関係を確認できたら、チェックします。','内容と承認先が正しければ「承認」を押します。'],
 'terminal-confirm':['お子さまの名前と、お迎え予定を確かめます。','合っていれば「決定」を押します。'],
 'terminal-arrival':['お子さまの名前を確かめます。','名前が合っていたら「登園する」を押します。'],
 'terminal-arrival-done':['「登園を受け付けました。」と出たことを確かめます。'],
 'terminal-classes':['お子さまのクラスを選びます。'],
 'terminal-names':['お子さまの名前を選びます。'],
 'terminal-departure-filled':['お子さまの名前を確かめます。','実際にお迎えに来た人を選びます。','「降園する」を押します。'],
 'terminal-departure-done':['「降園を受け付けました。」と出たことを確かめます。'],
}
for name in ['partial','filled','error']:CALLS['app-pickup-'+name]=CALLS['app-pickup-empty']
CALLS['qr-review-existing']=CALLS['qr-review-new']

def marks(image):
    p=HERE/'dist/screens'/f'{image}.html'
    if not p.exists():return []
    html=p.read_text(encoding='utf-8')
    return [json.loads(m[0]) for m in re.findall(r'mark\(("(?:\\.|[^"\\])*"),(\d+)\);',html)]

def apply_review(articles):
    if 'parent-app-home' in articles:
        a=articles['parent-app-home']
        a['steps'][4]['note']='「登録情報」は、自分のメール・電話・住所・勤務先を直して保存する画面です。「子ども情報変更申請」は、お子さまの情報の変更を園へ申請する画面です。'
        faq=['「登録情報」を押したら、変更申請の画面が出ました','園の家族台帳に保護者情報がひもづいている場合は、「登録情報」からも「子ども情報変更申請」へ移ることがあります。その画面では、入力した内容を園へ申請します。分からないときは園に確認してください。']
        if faq not in a['faq']:a['faq'].append(faq)
    if 'parent-app-notices' in articles:
        articles['parent-app-notices']['steps'][3]['text']='「本日の出欠確認のお願い」が来たら、内容を読みます。「出席・欠席を連絡する」を押し、連絡を入力して保存してください。'
    if 'parent-app-pickup' in articles:
        a=articles['parent-app-pickup']
        a['steps'][2].update(image='app-pickup-save',compact=True,alt='お迎え予定の入力画面の下部。①予定を保存ボタン。')
        a['steps'][3].update(image='app-pickup-reopen',alt='保存した日のお迎え予定を開き直した画面の例。①お子さまの名前、②16:30、③母、④補食は不要。',note='画像は、同じ日付で開き直したときの見本です。予定の保存だけでは、登園・降園の受付はされません。園の受付画面でも操作してください。')
    if 'staff' in articles:
        a=articles['staff']
        for s in a['steps']:
            if s['title'].startswith('管理者：権限') or '「職員権限設定」で必要な業務' in s['text']:
                s['text']=s['text'].replace('「職員権限設定」で必要な業務を確認します。','職員一覧の「権限設定」を押すと、「職員権限設定」の画面が開きます。必要な業務の権限を確認します。')
        a['faq']=[[q,ans.replace('権限は「職員権限設定」で確認します。','権限は、職員一覧の「権限設定」から「職員権限設定」の画面を開いて確認します。')] for q,ans in a['faq']]
    if 'child' in articles:
        for s in articles['child']['steps']:
            if '保護者・家族情報' in s['text']:
                extra='保護者2の「続柄」に最初から「母」と出ても、保護者2を登録済みという意味ではありません。記入する場合は、その方との実際の続柄を確かめてください。'
                if extra not in s.get('note',''):s['note']=(s.get('note','')+' '+extra).strip()
    for a in articles.values():
        for s in a['steps']:
            if s.get('image') in CALLS and (not s.get('calls') or s['image'].startswith('app-pickup')):s['calls']=CALLS[s['image']]
            if s.get('states'):
                by_state={}
                for key,_ in s['states']:
                    image=(s.get('imagePrefix') or a.get('imagePrefix',''))+'-'+key
                    selectors=marks(image)
                    if image in CALLS:by_state[key]=CALLS[image]
                    elif not selectors:by_state[key]=[]
                    elif len(selectors)==len(s.get('calls',[])):by_state[key]=s['calls']
                s['stateCalls']=by_state
