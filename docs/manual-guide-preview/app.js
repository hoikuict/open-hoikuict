'use strict';
const screenshotSizes = {"child-new-empty": [1265, 2596], "child-new-filled": [1265, 2596], "child-new-partial": [1265, 2596], "monthly-confirm": [1265, 1501], "monthly-empty": [1265, 1202], "monthly-error": [1265, 1283], "monthly-filled": [1265, 1202], "monthly-list": [1265, 807], "parent-form-empty": [1265, 1175], "parent-form-filled": [1265, 1274], "parent-form-partial": [1265, 1175], "parent-invite": [1280, 850], "parent-password": [1280, 850], "parent-review": [1265, 1018], "parent-select": [1280, 850], "password-admin": [1280, 720], "password-person": [1280, 720], "phone-empty": [1265, 741], "phone-filled": [1265, 741], "phone-partial": [1265, 741], "phone-saved": [1265, 839], "staff-activate": [1280, 850], "staff-class": [1280, 850], "staff-code": [1280, 850], "staff-list": [1280, 720], "staff-new-empty": [1280, 850], "staff-new-error": [1280, 850], "staff-new-filled": [1280, 850], "staff-new-partial": [1280, 850], "staff-password": [1280, 850]};
const main = document.getElementById('main');
const esc = s => String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// BEGIN UI LABELS
// Only reviewed UI names are decorated; examples, values and errors stay ordinary text.
const uiTerms = Object.fromEntries([
  ['menu',['設定','職員管理','職員権限設定','園児一覧','出欠一覧','出欠確認','保護者アカウント','園児別・月間の登降園修正','パスワード再設定']],
  ['button',['職員を追加','園児を追加','認証管理','担当クラス','権限設定','クラス管理','園児別・月間修正','管理者：まとめて補完','追加する','登録する','キャンセル','一覧へ戻る','編集','有効化コードを発行','コードを確認して次へ','ログイン情報を設定','再設定コードを発行','パスワードを再設定','パスワードを設定する','管理者の方：パスワードを忘れた場合','詳細','閉じる','連絡受付を記録','受付を取り消す','表示する','選択した日の空欄へ入れる','保存内容を確認','○日分をまとめて保存','3日分をまとめて保存','保存せず閉じる','詳細・修正','この日の記録を保存','打刻の取消・履歴を開く','引き継いで追加','在園児の保護者を追加・招待','この保護者を招待','新しい保護者を追加','登録済み・認証管理','初回入力の招待を送信','入力内容を園に提出する','入力をやめる','承認','却下','選択']],
  ['field',['表示名','メールアドレス','権限','表示順','有効','ログインID','発行理由','新しいパスワード','新しいパスワード（確認）','再設定コード','有効化コード','クラス','担当区分','開始日','終了日','主表示にする','所属する家族','兄弟姉妹を選択','姓','名','姓（カナ）','名（カナ）','生年月日','入園日','退園日','在籍状況','家族名','自宅住所','自宅電話番号','在園児','保護者のメールアドレス','確認理由','連絡方法','欠席理由','連絡内容','取消理由','共通の補完理由','共通の降園時刻']]
].flatMap(([kind,names])=>names.map(name=>[name,kind])));
function uiRef(kind,label){
  return `<span class="ui-ref ui-ref--${kind}"><strong>${esc(label)}</strong></span>`;
}
function prose(value){
  const text=String(value);let result='',from=0;
  for(const match of text.matchAll(/「([^「」]+)」/g)){
    result+=esc(text.slice(from,match.index));
    const kind=Object.hasOwn(uiTerms,match[1])?uiTerms[match[1]]:null;
    result+=kind?uiRef(kind,match[1]):esc(match[0]);from=match.index+match[0].length;
  }
  return result+esc(text.slice(from));
}
function openingPath(path){
  return `<div class="path"><strong>開く順番</strong><ol class="opening-path">${path.split(' → ').map(part=>`<li>${Object.hasOwn(uiTerms,part)?uiRef(uiTerms[part],part):prose(part)}</li>`).join('')}</ol></div>`;
}
function uiLegend(){
  return `<aside class="ui-legend" aria-label="名称の見分け方"><div><strong>本文中の目印</strong><span class="ui-key ui-ref--menu">メニュー・画面</span><span class="ui-key ui-ref--button">ボタン</span><span class="ui-key ui-ref--field">入力欄</span></div><p>枠内の名前を、アプリの画面で探してください。</p></aside>`;
}
// END UI LABELS
const manualArticles = {
  // BEGIN REGISTRATION ARTICLES
  "staff": {
    "title": "新しい職員を登録して、使い始めてもらう",
    "chapter": 0,
    "role": "園の管理者 → 職員本人",
    "tag": "職員登録",
    "imagePrefix": "staff-new",
    "summary": "職員の追加から担当クラス、初回ログインまで、順番に確認します。",
    "goal": "本人が自分のIDでログインし、担当する業務を開ける。",
    "before": "氏名・本人のメールアドレス・必要な権限・担当クラスと開始日を確認します。同じ職員が無効の一覧も含めて登録済みでないか、先に探してください。",
    "path": "管理者でログイン → 設定 → 職員管理 → 職員を追加",
    "keywords": "職員登録 職員追加 新任 入職 採用 アカウント 担任 担当クラス 有効化 初期設定",
    "steps": [
      {
        "title": "管理者：職員の基本情報を登録する",
        "text": "「表示名」と本人の「メールアドレス」を入力します。「権限」は担当業務に合わせて管理者・編集可・閲覧のみから選び、「表示順」と「有効」を確認して「職員を追加」を押します。",
        "image": "staff-new-filled",
        "alt": "職員追加の全入力項目。見本はなこ、架空のメール、編集可、表示順100、有効を選んだ例。",
        "calls": [
          "表示名とメールアドレスを本人と照合します。",
          "必要な権限を選びます。業務別の権限は追加後に設定します。",
          "「職員を追加」で保存され、認証管理へ進みます。"
        ],
        "note": "職員を追加しただけでは、招待メールは送られません。まだ本人のパスワードも設定されていません。保存前なら「キャンセル」でやめられます。",
        "states": [
          [
            "filled",
            "入力済みの例"
          ],
          [
            "empty",
            "未入力の例"
          ],
          [
            "partial",
            "一部入力の例"
          ],
          [
            "error",
            "重複エラーの例"
          ]
        ],
        "stateNotes": {
          "filled": "保存前の入力例です。表示順は園のルールに合わせます。",
          "empty": "表示名とメールアドレスが未入力です。",
          "partial": "表示名だけ入力した状態です。メールアドレスと権限を確認します。",
          "error": "同じメールアドレスが登録済みです。職員一覧に戻り、無効の職員も確認します。重複して作り直しません。"
        }
      },
      {
        "title": "管理者：業務別の権限と担当クラスを設定する",
        "text": "「職員権限設定」で必要な業務を確認します。次に職員一覧へ戻り、本人の「担当クラス」を開きます。「クラス」「担当区分」「開始日」「終了日」「表示順」「主表示にする」を確認し、「追加する」を押します。",
        "image": "staff-class",
        "alt": "担当クラスの全入力欄。さくら組、主担当、開始日2026年11月3日、終了日空欄、表示順100、主表示の例。",
        "calls": [
          "担当するクラスを選びます。",
          "開始日と終了日を確認します。現在日を含む期間が職員ホームの対象です。",
          "「追加する」で担当を保存し、下の担当履歴を確認します。"
        ],
        "note": "権限と担当クラスは別の設定です。担当クラスを追加するだけで、すべての業務が操作できるわけではありません。"
      },
      {
        "title": "管理者：有効化コードを発行して本人へ渡す",
        "text": "職員一覧の本人の「認証管理」を開きます。「ログインID」と「発行理由」を確認して「有効化コードを発行」を押します。表示された案内を印刷するなど、園で決めた方法で本人に渡します。",
        "image": "staff-code",
        "alt": "認証未設定の職員。ログインID、発行理由、有効化コードを発行ボタン。",
        "calls": [
          "初回のログインIDを確認します。",
          "「新規採用職員の初期設定」など、発行する理由を入れます。",
          "本人が作業できるタイミングで発行します。"
        ],
        "note": "コードは30分有効・1回限りです。画面を離れると同じコードを再表示できません。印刷し直しても期限は延びません。"
      },
      {
        "title": "職員本人：案内を開き、コードを入力する",
        "text": "受け取った案内のQRコードまたは初期設定のURLを開き、6文字の有効化コードを入力します。「コードを確認して次へ」を押します。",
        "image": "staff-activate",
        "alt": "職員アカウントの初期設定。本人が有効化コードを入力する画面。",
        "calls": [
          "最新の案内にあるコードを入力します。",
          "「コードを確認して次へ」で本人の設定画面へ進みます。"
        ],
        "note": "期限切れ・使用済みの場合は、管理者に再発行を依頼します。職員をもう一度追加する必要はありません。"
      },
      {
        "title": "職員本人：自分のログイン情報を設定する",
        "text": "画面の氏名と「ログインID」を確認します。必要ならIDを修正し、新しいパスワードを2回入力して「ログイン情報を設定」を押します。パスワードは8〜128文字です。",
        "image": "staff-password",
        "alt": "本人のログインID、新しいパスワード、確認用パスワードと設定ボタン。パスワード欄は未入力の見本。",
        "calls": [
          "次回から使うログインIDを確認します。",
          "本人がパスワードを決め、確認欄にも同じものを入れます。",
          "「ログイン情報を設定」を押すと確定します。"
        ],
        "note": "管理者が本人のパスワードを決める手順ではありません。設定後は、職員ログイン画面でログインします。"
      },
      {
        "title": "本人と管理者：ログインと利用範囲を確かめる",
        "text": "本人が設定したIDでログインし、自分の担当クラスと必要な業務を確認します。管理者は職員一覧で「有効」と認証の「設定済み」を確認します。",
        "note": "入れない場合は、登録メールアドレスと本人が設定したログインIDを取り違えていないか確認します。必要な画面だけ出ない場合は、権限と担当期間を確認します。"
      }
    ],
    "checks": [
      "同じ職員を重複登録していない",
      "有効・業務別権限・担当クラスと期間が合っている",
      "本人が初期設定を終え、自分のIDでログインできた"
    ],
    "faq": [
      [
        "メールアドレスが登録済みと表示された",
        "無効の職員も表示して本人の既存登録を探します。登録済みなら、その職員の編集・認証管理から対応します。"
      ],
      [
        "登録内容を間違えた",
        "保存前なら入力を直すかキャンセルします。保存後は職員一覧の本人の「編集」から直し、権限は「職員権限設定」で確認します。"
      ],
      [
        "担当クラスが出てこない",
        "クラス、開始日・終了日、主表示を確認します。必要な業務の権限も別途確認してください。"
      ],
      [
        "有効化コードの期限が切れた",
        "管理者が本人の認証管理から再発行し、最新の案内を渡します。古いコードや用紙は使いません。"
      ]
    ],
    "source": "staff-registration-manual/",
    "sourceLabel": "職員登録マニュアル：追加・権限・初回設定"
  },
  "child": {
    "title": "園児を1人登録して、台帳に載せる",
    "chapter": 2,
    "role": "園児・家庭情報を登録できる職員",
    "tag": "園児登録",
    "imagePrefix": "child-new",
    "summary": "園児本人、家族、保護者の情報をまとめて登録します。兄弟姉妹がいる場合の選び方も確認できます。",
    "goal": "園児が正しいクラス・家族で台帳に表示される。",
    "before": "氏名・カナ・生年月日・入園日、クラス、家族・保護者の連絡先を用意します。園児がすでに登録されていないか、一覧で確認します。",
    "path": "職員メニュー → 園児一覧 → 園児を追加",
    "keywords": "園児登録 園児追加 入園 子ども 台帳 家族登録 兄弟 姉妹 クラス 新入園児",
    "steps": [
      {
        "title": "登録済みの園児・家族がいないか確認する",
        "text": "「園児一覧」で氏名や生年月日を確認してから「園児を追加」を押します。兄弟姉妹がいる場合は、上の「兄弟姉妹を選択」から対象を選び「引き継いで追加」で家族情報を読み込みます。",
        "note": "新しい家族と、すでにある家族への追加を取り違えないようにします。同じ名字という理由だけで家族を選びません。"
      },
      {
        "title": "家族を選び、園児の情報を入力する",
        "text": "「所属する家族」を選び、「姓」「名」「姓（カナ）」「名（カナ）」「生年月日」「入園日」を入力します。「在籍状況」と「クラス」も確認します。写真、性別、照合用氏名、退園日、アレルギー、医療メモは必要に応じて入力します。下の画像は、保護者欄まで含めた画面全体です。押すと拡大できます。",
        "image": "child-new-filled",
        "alt": "園児追加の全入力項目。家族選択、写真・性別・氏名・カナ・日付・クラス・健康情報、家族と保護者2名分の入力欄、登録・キャンセルまで表示。",
        "calls": [
          "新しい家族を作るか、既存の家族を選びます。",
          "姓・名・カナを資料と見比べます。生年月日・入園日も必須です。",
          "対象のクラスを選びます。なければクラス管理で先に登録します。",
          "すべて確認したあと、最下部の「登録する」で保存します。"
        ],
        "note": "画像は入力済みの例で、まだ保存前です。保護者・家族の欄も次の手順に沿って確認してください。",
        "states": [
          [
            "filled",
            "入力済みの例"
          ],
          [
            "empty",
            "未入力の例"
          ],
          [
            "partial",
            "一部入力の例"
          ]
        ],
        "stateNotes": {
          "filled": "園児と保護者1を入力した例です。保護者2・写真・任意項目も省略せず表示しています。",
          "empty": "新しい家族として登録する未入力の例です。赤い＊の項目は必須です。",
          "partial": "園児の姓だけ入力した例です。残りの必須項目と家族情報を確認します。"
        }
      },
      {
        "title": "家族と保護者の情報を確認して保存する",
        "text": "画面下部の「保護者・家族情報」へ進みます。家族名、自宅住所・電話、保護者1・2それぞれの氏名・カナ・続柄・メール・電話・勤務先を確認します。必要な情報がそろったら「登録する」を押します。",
        "note": "住所や保護者情報は同じ家族の兄弟姉妹で共有します。既存の家族を選んだ場合は変更がほかの園児にも反映される点を確認します。保存前にやめる場合は「キャンセル」です。"
      },
      {
        "title": "台帳を確認し、保護者の招待へ進む",
        "text": "保存後は「園児一覧」と詳細で、氏名・生年月日・入園日・在籍状況・クラス・家族・保護者の連絡先を確かめます。保護者にアプリを使ってもらう場合は、続いて「在園児の保護者を招待する」の手順へ進みます。",
        "note": "園児の台帳登録と、保護者のログイン利用開始は別の手順です。ここにメールアドレスを書いただけでは、保護者の初回設定は完了しません。"
      }
    ],
    "checks": [
      "氏名・カナ・生年月日・入園日を確認した",
      "クラスと所属家族、保護者の連絡先が合っている",
      "保存後の一覧・詳細を確認した。保護者の招待は必要に応じて別途行う"
    ],
    "faq": [
      [
        "兄弟姉妹がすでにいる",
        "既存の園児から家族情報を引き継ぐか、所属する家族から正しい家族を選びます。共有される住所・保護者情報を確認してください。"
      ],
      [
        "クラスが選べない",
        "追加画面の「クラス管理」で登録状況を確認します。操作できない場合は管理者に確認します。"
      ],
      [
        "登録ボタンを押しても先へ進めない",
        "必須の姓・名・カナ・生年月日・入園日と、画面に表示されたエラーを確認します。エラーを直す前に別の園児として作り直しません。"
      ],
      [
        "保存したあと間違いに気づいた",
        "同じ園児の編集画面から訂正し、保存後に一覧・詳細を確認します。家族の変更は兄弟姉妹への影響も確認します。"
      ],
      [
        "保護者2を書けば2人ともログインできる？",
        "台帳の保護者情報だけではログイン利用は始まりません。利用する保護者ごとに、保護者登録の招待と本人の初回設定が必要です。"
      ]
    ],
    "source": "guardian-account-sync/",
    "sourceLabel": "園児・家庭台帳の案内"
  },
  "parent": {
    "title": "在園児の保護者を招待して、使い始めてもらう",
    "chapter": 0,
    "role": "園の担当者 → 保護者本人 → 園の確認担当者",
    "tag": "保護者登録",
    "imagePrefix": "parent-form",
    "summary": "台帳に登録済みの園児について、保護者本人を招待し、提出内容を確認して利用開始につなげます。",
    "goal": "招待した保護者本人がログインし、対象のお子さまを確認できる。",
    "before": "園児を先に台帳へ登録します。招待する保護者本人、園児との関係、本人が受信できるメールアドレスを確認します。",
    "path": "保護者アカウント → 在園児の保護者を追加・招待",
    "keywords": "保護者登録 保護者追加 招待 親 アカウント メール 初回入力 承認 登録申請 利用開始",
    "steps": [
      {
        "title": "園：園児と招待する保護者を選ぶ",
        "text": "「在園児」で対象の園児を選び「選択」を押します。表示された保護者の氏名・続柄を確かめて「この保護者を招待」を押します。台帳にその方がいない場合は「新しい保護者を追加」です。",
        "image": "parent-select",
        "alt": "見本あおいを選び、見本みどり（母）の「この保護者を招待」が表示された選択画面。",
        "calls": [
          "クラス・氏名・生年月日で対象の園児を確かめます。",
          "招待する本人の行を選びます。「登録済み・認証管理」なら既存のアカウントを確認します。"
        ],
        "note": "この手順は在園児向けです。台帳にいない新規入園児の受付や共通QRからの登録は、詳細版の別ルートを使います。"
      },
      {
        "title": "園：本人のメールアドレスへ招待を送る",
        "text": "対象園児と、登録済みの保護者を招待することを確認します。「保護者のメールアドレス」に本人のアドレスを入力し、「初回入力の招待を送信」を押します。",
        "image": "parent-invite",
        "alt": "対象園児、架空の保護者メール、初回入力の招待を送信ボタン。",
        "calls": [
          "対象のお子さまを確認します。",
          "本人が受信できるメールアドレスを照合します。",
          "このボタンを押すと招待メールの送信処理が始まります。"
        ],
        "note": "本番ではメールが送られる操作です。送信前なら「一覧へ戻る」でやめられます。送信後は認証管理の配送状況と、本人の受信を確認します。"
      },
      {
        "title": "保護者本人：自分の情報を確認して園へ提出する",
        "text": "招待メールを開き、対象のお子さまと自分の情報を確認します。氏名・カナ・続柄・電話番号を入力し、勤務先があれば入力します。登録済みの内容が表示された場合は、変更箇所と未入力の必須項目を確認して「入力内容を園に提出する」を押します。",
        "image": "parent-form-filled",
        "alt": "保護者本人の登録画面。対象のお子さまと、氏名・カナ・続柄・電話・勤務先の9項目を表示。",
        "calls": [
          "園に登録済みの本人情報を確認します。",
          "電話番号も含め、必須項目を確認します。",
          "「入力内容を園に提出する」で、園の確認待ちになります。"
        ],
        "note": "お子さまの情報や自宅住所を再入力する画面ではありません。変更があれば園に知らせます。招待リンクは24時間・1回限り、開いた入力画面は2時間有効です。",
        "states": [
          [
            "filled",
            "登録済みの情報を確認する例"
          ],
          [
            "empty",
            "未入力の例"
          ],
          [
            "partial",
            "一部入力の例"
          ]
        ],
        "stateNotes": {
          "filled": "台帳にある本人の情報が初期表示された例です。空欄の勤務先は、勤務先がなければそのままで構いません。",
          "empty": "新しく追加する保護者など、本人情報がまだない場合の例です。必須6項目を入力します。",
          "partial": "姓だけ入力した例です。名・カナ・続柄・電話番号も確認します。"
        }
      },
      {
        "title": "園：本人と園児の対応、提出内容を確認して承認する",
        "text": "「保護者アカウント」の本人の「認証管理」を開き、「登録申請の履歴」で内容を確認します。本人と園児の対応を確認した方法を「確認理由」に記録し、確認のチェックを付けて「承認」を押します。",
        "image": "parent-review",
        "alt": "認証管理の登録申請欄を抜粋。提出された本人の9項目、確認理由、確認チェック、承認と却下ボタン。",
        "calls": [
          "確認した内容と方法を理由に残します。",
          "招待先・保護者と園児の対応・入力内容を確認してチェックします。",
          "「承認」で台帳に反映され、対象園児の閲覧が許可されます。"
        ],
        "note": "承認は内容の閲覧だけとは異なります。間違いや確認不足がある場合は承認せず、本人に確認してください。承認後にパスワード設定の案内が送られます。"
      },
      {
        "title": "保護者本人：案内メールからパスワードを設定する",
        "text": "園の承認後に届いたパスワード設定の案内を開きます。本人が8〜128文字のパスワードを2回入力し、「パスワードを設定する」を押します。",
        "image": "parent-password",
        "alt": "保護者登録のパスワード設定画面。新しいパスワード、確認用、表示切替、パスワードを設定するボタン。",
        "calls": [
          "本人が新しいパスワードを入力します。",
          "同じものを確認欄に入力します。",
          "「パスワードを設定する」で初回設定を完了します。"
        ],
        "note": "園が本人のパスワードを決めたり、聞き取ったりする必要はありません。期限切れの場合は園へ連絡します。"
      },
      {
        "title": "本人と園：ログインして対象のお子さまを確認する",
        "text": "保護者が案内されたログイン画面からログインし、対象のお子さまが表示されるか確認します。園は認証管理で登録の状態を確認します。",
        "note": "別の保護者にも利用してもらう場合は、その本人を別途招待します。兄弟姉妹の閲覧対象も、「保護者アカウント」で個別に確認します。"
      }
    ],
    "checks": [
      "園児と招待する保護者本人を正しく選んだ",
      "提出内容を確認し、理由と確認チェックを付けて承認した",
      "本人が初回設定とログインを終え、対象のお子さまを確認できた"
    ],
    "faq": [
      [
        "招待メールが届かない",
        "宛先と迷惑メールを確認します。園は認証管理の配送状況を確認します。「メールサーバー受付済み」でも受信箱に届いたかは本人に確認してください。"
      ],
      [
        "招待先を間違えて送信した",
        "いったん作業を止め、管理者に対象の申請・アカウントを確認してもらいます。誤った宛先の申請を承認せず、正しい本人の招待にやり直します。"
      ],
      [
        "入力を途中でやめたい",
        "提出前なら「入力をやめる」の確認に従います。未提出の入力は登録完了ではありません。再開時に期限が切れていれば園へ連絡します。"
      ],
      [
        "提出後に間違いが見つかった",
        "園へ知らせ、承認前に内容を確認してもらいます。承認済みの修正は園が台帳・アカウントを確認して対応します。再申請だけで上書きできると考えないでください。"
      ],
      [
        "まだ台帳にいない子ども／共通QRを使いたい",
        "この在園児向けの手順とは入口・入力項目が異なります。下の詳細版で「新規入園の初回入力」「共通QR」のルートを確認します。"
      ]
    ],
    "source": "parent-registration-manual/",
    "sourceLabel": "保護者登録マニュアル：在園児・新規入園・共通QR"
  },
  // END REGISTRATION ARTICLES
  phone: {
    title:'電話で欠席連絡を受けた', chapter:1, role:'出欠確認を操作できる職員', tag:'朝の出欠・連絡',
    summary:'電話や口頭で受けた連絡を記録し、ほかの職員も確認できるようにします。',
    goal:'誰から、どんな連絡を受けたかが受付履歴に残る。',
    before:'園児の名前・対象日・欠席理由・連絡内容を確認します。',
    path:'職員メニュー → 出欠確認 → 対象の園児の「詳細」',
    keywords:'でんわ けっせき 欠勤 休み おやすみ 口頭 アラーム 保護者連絡なし 出欠確認 日次連絡',
    steps:[
      {title:'園児と日付を確認する',text:'「出欠確認」で対象日とクラスを確認し、園児の「詳細」を開きます。下の見本では、すでに目視確認が「病欠」になっている園児を扱います。',image:'phone-empty',alt:'出欠確認の園児詳細。対象日は11月2日、園児は見本あおい。電話・口頭連絡の受付欄は未入力。',calls:['園児名と対象日を確認してから「詳細」を開きます。開いた後は「閉じる」と表示されます。'],note:'電話の受付と目視確認は別の記録です。電話の受付だけで目視確認や登降園の時刻は変わりません。'},
      {title:'受けた連絡を入力する',text:'「電話・口頭連絡の受付」に、次の3項目を入力します。例の文章は、その日に実際に受けた内容へ置き換えてください。',image:'phone-filled',alt:'連絡方法は電話、欠席理由は病欠、連絡内容は保護者から電話で体調不良のため休む旨。入力欄と記録ボタンに番号を表示。',calls:['「連絡方法」：電話か口頭を選びます。','「欠席理由」：「病欠」または「私用休み」を選びます。','「連絡内容」：誰から、どんな連絡を受けたかを書きます。','内容を確かめて「連絡受付を記録」を押します。'],note:'入力しただけでは記録されません。「連絡受付を記録」を押すと保存されます。',states:[['filled','入力済みの例'],['empty','未入力の例'],['partial','一部入力の例']],stateNotes:{filled:'3項目がそろった例です。最後の記録ボタンを押す前に内容を確認します。',empty:'欠席理由と連絡内容が未入力です。連絡方法の初期表示は「電話」です。',partial:'欠席理由だけ選んだ例です。「連絡内容」も入力してから記録します。'}},
      {title:'受付履歴に残ったか確かめる',text:'保存後、連絡の表示と受付履歴を確認します。受付した職員の名前・日時・連絡内容が記録されていれば完了です。',image:'phone-saved',alt:'電話連絡受付・病欠の表示と、受付した職員、日時、内容の履歴。目視確認と同じ病欠のため保護者連絡なしのアラームがなくなっている。',calls:['連絡の欄に「電話連絡受付」が表示されています。','受付履歴に方法・欠席理由・職員名・受付日時・内容が残っています。'],note:'同じ日・同じ欠席理由なら「保護者連絡なし」のアラームが解消します。ほかの不一致があるときは、引き続き確認します。'}
    ],
    checks:['園児と対象日が合っている','受付履歴に、受けた連絡の内容が残っている','アラームが残る場合は、理由を確認した'],
    faq:[['園児や内容を間違えて記録した','詳細の「取消理由」に理由を入力し、「受付を取り消す」を押します。その後、正しい園児・対象日に記録し直します。取消も履歴に残り、アラームは再判定されます。'],['「保護者連絡なし」が消えない','電話の欠席理由と、同じ日の目視確認の欠席理由を見比べます。電話受付は目視確認を自動で変えません。打刻があるのに欠席など、別の理由のアラームも確認します。'],['受付の入力欄が表示されない','「出欠確認」を操作する権限が必要です。園の管理者に、対象の職員でこの操作を行えるか確認してもらいます。'],['入力したまま保存せずにやめたい','「連絡受付を記録」を押す前なら、受付は保存されていません。画面を離れると入力中の内容が残らない場合があるため、必要な連絡は先に記録してください。']],
    source:'daily-work/', sourceLabel:'日々の業務：電話・口頭連絡の受付'
  },
  clock: {
    title:'登園・降園の打刻が抜けている',chapter:1,role:'管理者（まとめて補完する場合）',tag:'登園・降園',
    summary:'実際の時刻を確認してから、空欄の日をまとめて補います。',goal:'確認した日の空欄に、実際の登園・降園時刻が保存される。',
    before:'職員の記録などで実際の時刻を確認します。お迎え予定から推測して入力しません。',
    path:'出欠一覧 → 園児別・月間修正 → 管理者：まとめて補完',keywords:'だこく 打刻忘れ 打刻漏れ 登園 降園 未打刻 空欄 時間 まとめて 補完 月間 月末',
    steps:[
      {title:'月・クラス・園児を選ぶ',text:'「園児別・月間修正」で対象月・クラス・園児を選び、「表示する」を押します。記録を見てから「管理者：まとめて補完」を開きます。',image:'monthly-list',alt:'園児別・月間の登降園修正。対象月、クラス、園児の選択欄と管理者まとめて補完ボタン。',calls:['対象月・クラス・園児を確認します。','「管理者：まとめて補完」を押します。'],note:'この例は「空欄をまとめて補う」管理者向けの手順です。記録済みの時刻を直す場合は、日別の修正画面を使います。'},
      {title:'対象日と実際の時刻を入れる',text:'補完する日にチェックを入れます。「共通の降園時刻」に実際の時刻を入れ、「選択した日の空欄へ入れる」を押します。日によって時刻が違う場合は、その日の欄を直します。',image:'monthly-filled',alt:'空欄の時刻をまとめて補完する全入力項目。共通の降園16時30分を3日の空欄に反映し、理由を入力した状態。',calls:['空欄を補う側だけ共通時刻に入力します。','「選択した日の空欄へ入れる」で日ごとの欄へ反映します。','実際の時刻を確かめた方法などを「共通の補完理由」に書きます。'],note:'共通時刻に入力するだけでは各日に入りません。反映ボタンを押してから、違う日の時刻を直します。',states:[['filled','入力済みの例'],['empty','未入力の例'],['error','エラーの例']],stateNotes:{filled:'入力例です。まだ保存はしていません。',empty:'共通時刻・各日の空欄・理由を確認します。保存済みの登園時刻は変更できません。',error:'降園を07:00、登園を08:30とした入力エラーの例です。「降園は登園より後にしてください」と表示されます。入力内容は残るので、実際の時刻を確認して直します。'}},
      {title:'確認して、まとめて保存する',text:'「保存内容を確認」を押し、園児・対象日・変更前後の時刻を見比べます。合っていれば「○日分をまとめて保存」を押します。',image:'monthly-confirm',alt:'見本あおいの3日分の変更前後と「3日分をまとめて保存」ボタン。',calls:['確認欄で園児と日ごとの変更前後を確認します。','最後の「○日分をまとめて保存」で保存します。'],note:'確認画面へ進んだだけでは保存されません。やめる場合は「保存せず閉じる」を押します。'},
      {title:'一覧と修正履歴を確認する',text:'保存後は月間一覧を開き直し、対象日の空欄が埋まったことを確認します。日別の「詳細・修正」で、理由と変更前後の履歴も確かめます。',note:'時刻を保存すると、まだ確定していない延長料金が再計算されます。料金の確認が必要な場合は担当者に伝えます。',calls:['保存した日と時刻を一覧で確認します。','日別の履歴で、修正理由・修正者・変更前後を確認します。']}
    ],
    checks:['予定ではなく、実際の時刻を確認した','対象日・変更前後を確認して、最後の保存ボタンを押した','一覧と修正履歴に反映されている'],
    faq:[['時刻を入力したのにエラーになる','共通時刻の欄だけに入力していないか確認します。「選択した日の空欄へ入れる」を押し、各日の時刻を確認してください。登園・降園とも空欄の日は、時刻を入力するか対象から外します。'],['対象にできない日がある','欠席・未来日・在籍期間外・料金確定済みなどの日は一括補完できません。出欠未確認の日は、実際に出席していたことを確認してから対象にします。'],['保存前にやめたい／保存後に間違いに気づいた','保存前は「保存せず閉じる」を押します。保存後の時刻は、日別の修正画面で理由を付けて訂正します。料金の状態により編集できない場合は、料金担当者へ確認します。'],['このメニューが見当たらない','一括補完は管理者が利用します。「園児別・月間修正」がない場合は、園の運用担当者にアプリの更新状況を確認してもらいます。']],
    source:'daily-work/#bulk-attendance',sourceLabel:'日々の業務：登園・降園時刻の一括補完'
  },
  password:{
    title:'パスワードを忘れてログインできない',chapter:0,role:'職員本人 ＋ 園の管理者',tag:'ログイン・利用開始',
    summary:'管理者に再設定コードを発行してもらい、本人が新しいパスワードを設定します。',goal:'これまでのログインIDと、新しいパスワードでログインできる。',
    before:'園の管理者へ、パスワードを忘れたことを伝えます。職員を新しく登録し直す必要はありません。',
    path:'管理者でログイン → 設定 → 職員管理 → 本人の「認証管理」',keywords:'ログイン パスワード 忘れた 入れない 開けない 再設定 コード 期限切れ',
    steps:[
      {title:'管理者に再設定をお願いする',text:'職員本人は園の管理者に再設定を依頼します。管理者は本人を確認してから、「職員管理」で対象者の「認証管理」を開きます。',image:'staff-list',alt:'職員管理の一覧。見本はなこの氏名・ログインIDを1、同じ行の認証管理ボタンを2で囲んだ架空データの例。',calls:['職員の名前とログインIDを確認し、依頼した本人の行を探します。','同じ行の「認証管理」を開きます。'],note:'管理者本人が入れない場合は、職員ログイン画面の「管理者の方：パスワードを忘れた場合」を使います。'},
      {title:'再設定コードを本人に渡す',text:'管理者が「発行理由」を入力し、「再設定コードを発行」を押します。表示された6文字のコードと再設定画面の案内、有効期限を本人に個別に渡します。',image:'password-admin',alt:'管理者向けの発行理由欄と再設定コードを発行ボタンを番号で案内。',calls:['「発行理由」に「本人からパスワード紛失の申告」などと入力します。','「再設定コードを発行」を押します。'],note:'コードは発行から30分・1回限りです。画面を離れると同じコードは再表示できません。QR付き案内を印刷できる更新版では、用紙を本人に渡せます。'},
      {title:'本人がパスワードを決める',text:'本人が案内された「パスワード再設定」を開きます。受け取ったコードと、新しく決めたパスワードを入力します。管理者が本人のパスワードを決める操作ではありません。',image:'password-person',alt:'職員パスワード再設定。再設定コード、新しいパスワード、確認用パスワード、パスワードを再設定ボタンの全項目。',calls:['最新の再設定コードを入力します。','新しいパスワードを8〜128文字で入力します。','同じパスワードを確認欄にも入力します。','「パスワードを再設定」を押します。'],note:'画面は見本です。ここに実際のコードやパスワードを入力する欄はありません。'},
      {title:'新しいパスワードでログインする',text:'職員ログイン画面に戻り、これまでのログインIDと新しいパスワードでログインします。担当する業務の画面を開けることを確認します。',note:'パスワードの再設定では、ログインIDは変わりません。設定後に使った案内用紙は破棄します。',calls:['ログインIDが合っているか確認します。','ログインでき、担当業務の画面が開くことを確認します。']}
    ],
    checks:['本人が新しいパスワードを設定した','これまでのログインIDでログインできた','担当する業務の画面を開けた'],
    faq:[['コードの期限が切れた／用紙をなくした','管理者に再発行を依頼します。発行から30分の最新コードを使います。印刷し直しても有効期限は延びません。'],['何度も試して利用制限が表示された','繰り返し入力せず、画面の案内に従って時間を置き、管理者へ連絡します。'],['ログインできるが必要な画面を開けない','管理者に「権限設定」と担当クラス・担当期間を確認してもらいます。パスワードを再設定しても、業務の権限は変わりません。'],['管理者本人がログインできない','職員ログイン画面の「管理者の方：パスワードを忘れた場合」から進みます。登録メールで復旧できない場合は、園の運用担当者へ連絡します。']],
    source:'staff-registration-manual/#troubleshooting',sourceLabel:'職員登録マニュアル：パスワードの再設定'
  }
};
let currentArticle='', currentStep=0, allSteps=false, imageState='', checked={};
const titles=['利用を始める','毎日の出欠と連絡','園児・家庭と記録','指導計画をつくる','職員間で共有する','料金と請求を確認する','点検・困ったとき'];
document.getElementById('chapter-nav').innerHTML=titles.map((t,i)=>`<a href="#chapter/${i}"><span class="chapter-number">0${i+1}</span>${t}</a>`).join('');
const crumb=(label,chapter)=>`<div class="breadcrumb"><a href="#home">ホーム</a><span>›</span>${chapter!==undefined?`<a href="#chapter/${chapter}">${titles[chapter]}</a><span>›</span>`:''}<span>${esc(label)}</span></div>`;
const searchBox=()=>`<form class="search-wrap" id="search-form" role="search"><div class="search-box"><label for="search-input" aria-label="マニュアルを検索">⌕</label><input id="search-input" type="search" placeholder="困っていること・やりたいことを入力" autocomplete="off"><button class="primary" type="submit">探す</button></div><div class="search-examples"><span>たとえば</span>${['職員登録','園児登録','保護者登録','打刻忘れ'].map(s=>`<button type="button" data-search="${s}">${s}</button>`).join('')}</div></form>`;
const card=id=>{const a=manualArticles[id];return `<a class="issue-card" href="${['clock','password'].includes(id)?'#help/'+id:'#article/'+id}"><span class="tiny">${a.tag}</span><h3>${a.title}</h3><p>${a.summary}</p><span class="bottom"><span>画面付きで読む · ${a.steps.length}ステップ</span><span aria-hidden="true">→</span></span></a>`;};
function home(){return `<section class="hero"><p class="eyebrow">毎日の「どうする？」を、ひとつずつ。</p><h1>迷ったら、ここから。</h1><p class="lead">忙しい保育の合間にも、必要な手順がすぐ見つかる。<br>画面を見ながら、一緒に進める使い方ガイドです。</p><div class="hero-index" aria-hidden="true">Guide<small>FOR NURSERY STAFF</small></div></section>${searchBox()}<section class="entrances" aria-label="2つの探し方"><a class="entrance emphasis" href="#issues"><small>いま、解決したいことがある</small><h2>こんなときどうする？</h2><p>困っている場面を選んで、解決の手順へ。</p><span class="arrow" aria-hidden="true">↗</span></a><a class="entrance" href="#chapters"><small>仕事の流れを知りたい</small><h2>業務ごとに、順番に読む</h2><p>利用開始から日々の記録、月末の請求まで。</p><span class="arrow" aria-hidden="true">↗</span></a></section><div class="section-head"><h2>登録の準備と、日々の困りごと</h2><span>スクショ付きの代表例</span></div><section class="issue-grid">${Object.keys(manualArticles).map(card).join('')}</section><div class="hint-strip"><strong>画面と同じ言葉で。</strong><span>押すボタンの名前、保存されるタイミング、間違えたときの戻り方まで、ひとつの手順にまとめています。</span></div>`;}
function chapters(){return `${crumb('仕事の流れから読む')}<p class="eyebrow">体系的に読む</p><h1>業務ごとに、順番に。</h1><p class="lead">全7分野・既存の33項目を見渡せます。担当する仕事から選んでください。</p><div class="chapter-grid">${manualChapters.map((c,i)=>`<a class="chapter-card" href="#chapter/${i}"><small>CHAPTER 0${i+1} · ${c.topics.length}項目</small><h2>${titles[i]} →</h2><p>${c.description}</p></a>`).join('')}</div><p class="notice">「画面付きの試作」と「現在公開されている資料」を分けて表示しています。既存資料は別のタブで開きます。</p>`;}
function articleLink(id){const a=manualArticles[id];return `<a class="topic" href="#article/${id}"><span><strong>${a.title}</strong><small>${a.role} · ${a.steps.length}ステップ</small></span><span class="badge">画面付きの試作 →</span></a>`;}
function referenceLink(t){return `<a class="topic" href="${esc(t.url)}" target="_blank" rel="noopener"><span><strong>${esc(t.title)}</strong><small>${esc(t.role)} · 既存資料を別タブで開く</small></span><span class="badge reference">${esc(t.kind)} ↗</span></a>`;}
function chapter(i){const c=manualChapters[i];return `${crumb(titles[i])}<p class="eyebrow">CHAPTER 0${i+1}</p><h1>${titles[i]}</h1><p class="lead">${c.description}</p>${Object.values(manualArticles).some(a=>a.chapter===i)?`<h2>画面を見ながら進める</h2><div class="topic-list">${Object.entries(manualArticles).filter(([,a])=>a.chapter===i).map(([id])=>articleLink(id)).join('')}</div>`:''}<div class="section-head"><h2>順番に読む・詳しく確認する</h2><span>現在の公開資料</span></div><div class="topic-list">${c.topics.map(referenceLink).join('')}</div><p class="source-note">この分野の既存${c.topics.length}項目を掲載しています。概要・仕様の資料は、今後の画面付き手順の整備候補です。</p>`;}
function issues(){return `${crumb('こんなときどうする？')}<p class="eyebrow">場面から探す</p><h1>いま、どんなことで困っていますか。</h1><p class="lead">機能の名前が分からなくても大丈夫。近い場面を選んでください。</p>${searchBox()}<section class="issue-grid">${Object.keys(manualArticles).map(card).join('')}</section><div class="notice"><strong>この試作版では、登録3種と日々の困りごと、計6つの場面を試せます。</strong>ほかの業務は「仕事の流れから読む」から、現在の公開資料を確認できます。</div><a href="#chapters">業務別の目次を見る →</a>`;}
const helpOptions={
  clock:[['空欄の時刻を、まとめて入れたい','実際の時刻が分かっている・管理者が操作する','#article/clock'],['すでに入っている時刻が間違っている','空欄の補完ではなく、日ごとの訂正','#answer/clock-correct'],['実際の時刻がまだ分からない','まず園内の記録や保護者に確認する','#answer/clock-unknown']],
  password:[['パスワードを忘れた','管理者に再設定を依頼する','#article/password'],['コードの期限が切れている','最新のコードを管理者に発行してもらう','#answer/code'],['ログインはできるが、必要な画面が出ない','権限・担当クラスを確認する','#answer/access']]
};
function help(id){return `<div class="diagnosis">${crumb('状況を確かめる')}<p class="eyebrow">こんなときどうする？</p><h1>${id==='clock'?'打刻の記録は、どんな状態ですか。':'どこで進めなくなりましたか。'}</h1><p class="lead">状況によって、対応する手順が変わります。</p><div class="choices">${helpOptions[id].map(([title,desc,url])=>`<a href="${url}" class="topic"><span><strong>${title}</strong><small>${desc}</small></span><span aria-hidden="true">→</span></a>`).join('')}</div><a href="#issues">← 場面を選び直す</a></div>`;}
const answers={
  'clock-correct':['日別の修正画面で訂正します。','「園児別・月間修正」で対象の月・園児を選び、該当日の「詳細・修正」へ進みます。実際の時刻と補記・修正理由を入力し、「この日の記録を保存」を押します。料金が確定済みなどの場合は編集できません。','保存したあとに日別の履歴を確認してください。打刻そのものの取消は「打刻の取消・履歴を開く」から進む別の操作です。','clock'],
  'clock-unknown':['実際の時刻を確認してから進めます。','職員の記録や保護者への確認などで、その日の実際の登園・降園時刻を確かめます。お迎え予定は実際の降園時刻とは別なので、そのまま写さないでください。','分かった日だけ対象にします。出欠未確認の日も、実際の出席を確認してから選びます。','clock'],
  code:['管理者にコードの再発行をお願いします。','職員用の再設定コードは発行から30分・1回限りです。管理者に本人確認のうえ再発行してもらい、最新のコードでやり直します。','用紙を印刷し直しても期限は延びません。古い用紙は破棄してください。','password'],
  access:['権限と担当クラスを確認してもらいます。','園の管理者に、職員管理の「権限設定」と「担当クラス」を確認してもらいます。必要な業務別の権限、担当クラス、担当期間が合っているか確認します。','パスワードの再設定は不要です。担当する業務と、出ていない画面の名前を管理者に伝えてください。','password']
};
function answer(id){const a=answers[id];return `<div class="diagnosis">${crumb('状況に合わせた対応')}<p class="eyebrow">まず、ここを確認</p><h1>${a[0]}</h1><p>${prose(a[1])}</p><div class="notice">${prose(a[2])}</div><div class="related"><a class="primary topic" href="#article/${a[3]}">関連する画面付きの手順を読む →</a><a class="topic" href="#help/${a[3]}">状況を選び直す</a></div></div>`;}
function normalize(s){return s.normalize('NFKC').toLowerCase().replace(/\s+/g,'');}
function search(q){const n=normalize(q), terms=q.normalize('NFKC').trim().split(/[\s　]+/).filter(Boolean);const expansions=[];if(/欠席|電話|でんわ|休み/.test(n))expansions.push('phone');if(/打刻|だこく|登園|降園|補完/.test(n))expansions.push('clock');if(/ログイン|パスワード|コード/.test(n))expansions.push('password');const matches=Object.entries(manualArticles).filter(([id,a])=>expansions.includes(id)||(terms.length&&terms.every(t=>normalize(a.title+a.keywords+a.summary).includes(normalize(t)))));const refs=manualChapters.flatMap(c=>c.topics).filter(t=>terms.length&&terms.every(w=>normalize(t.title+t.role).includes(normalize(w))));return `${crumb('検索結果')}<h1>必要な手順を探す</h1>${searchBox()}<p class="search-status" role="status">${q?`「${esc(q)}」：画面付き ${matches.length}件・既存資料 ${refs.length}件`:'困っていることや、やりたいことを入力してください。'}</p>${matches.length?`<h2>画面を見ながら進める</h2><div class="topic-list">${matches.map(([id])=>articleLink(id)).join('')}</div>`:''}${refs.length?`<div class="section-head"><h2>現在の公開資料</h2></div><div class="topic-list">${refs.map(referenceLink).join('')}</div>`:''}${q&&!matches.length&&!refs.length?`<div class="empty-result"><h2>ぴったりの手順が見つかりませんでした。</h2><p>「打刻忘れ」「職員登録」のような短い言葉で試してください。<br>この試作版で画面付きの手順があるのは6例です。</p><a href="#chapters">業務別の目次から探す →</a></div>`:''}`;}
function renderStep(a,i,print=false){const s=a.steps[i];const prefix=a.imagePrefix||(currentArticle==='phone'?'phone':'monthly');let image=s.image;if(s.states&&imageState&&!print)image=prefix+'-'+imageState;return `<section class="step-body" id="${print?'print-':''}step-${i}"><div class="step-heading"><span class="number">${i+1}</span><h2>${s.title}</h2></div><p>${prose(s.text)}</p>${s.states&&!print?`<label class="state-select">見本の状態 <select data-state-step="${i}" aria-label="見本の状態">${s.states.map(([v,l])=>`<option value="${v}"${(imageState||s.states[0][0])===v?' selected':''}>${l}</option>`).join('')}</select></label><p class="state-explanation">${prose(s.stateNotes[imageState||s.states[0][0]])}</p>`:''}${image?`<figure class="screen"><button type="button" data-zoom="${image}" data-caption="${esc(s.states&&imageState&&!print?s.stateNotes[imageState]:s.alt)}" aria-label="手順${i+1}の画面を拡大"><img width="${screenshotSizes[image][0]}" height="${screenshotSizes[image][1]}" src="assets/${image}.jpg?v=20261103-v5" alt="${esc(s.states&&imageState&&!print?s.stateNotes[imageState]:s.alt)}"></button><figcaption><span>配備記録に対応する画面の見本・架空データ${image.startsWith('monthly-')&&image!=='monthly-list'?'／入力欄を縦に展開':''}</span><span>画像を押すと拡大 ↗</span></figcaption></figure>`:''}${s.calls?`<ol class="callouts">${s.calls.map((c,k)=>`<li><span class="number">${k+1}</span><span>${prose(c)}</span></li>`).join('')}</ol>`:''}${s.note?`<div class="notice ${i===a.steps.length-2?'warm':''}">${prose(s.note)}</div>`:''}</section>`;}
function article(id){const a=manualArticles[id];return `${crumb('画面付きの手順',a.chapter)}<div class="article-meta"><span class="badge">${a.tag}</span><span>${a.role}</span><span>全${a.steps.length}ステップ</span></div><h1 class="article-title">${a.title}</h1><p class="lead">${a.summary}</p><dl class="article-intro"><div><dt>この手順でできること</dt><dd>${a.goal}</dd></div><div><dt>始める前に</dt><dd>${prose(a.before)}</dd></div></dl>${openingPath(a.path)}${uiLegend()}<div class="reader-controls"><div class="segmented" aria-label="読み方"><button data-reader="step" aria-pressed="${!allSteps}">1つずつ読む</button><button data-reader="all" aria-pressed="${allSteps}">まとめて読む</button></div><button data-print>この手順を印刷</button></div><div class="reader screen-only">${allSteps?`<div class="all-steps">${a.steps.map((_,i)=>renderStep(a,i)).join('')}</div>`:`<nav class="step-nav" aria-label="操作手順">${a.steps.map((s,i)=>`<button data-step="${i}" ${i===currentStep?'aria-current="step"':''}><span class="number">${i+1}</span><span>${s.title}</span></button>`).join('')}</nav><div>${renderStep(a,currentStep)}<div class="next-prev"><button data-step="${currentStep-1}" ${currentStep===0?'disabled':''}>← 前の手順</button><span>${currentStep+1} / ${a.steps.length}</span>${currentStep<a.steps.length-1?`<button class="primary" data-step="${currentStep+1}">次の手順へ →</button>`:`<button class="primary" data-check-jump>完了を確認する ↓</button>`}</div></div>`}</div><div class="print-only">${a.steps.map((_,i)=>renderStep(a,i,true)).join('')}</div><section class="checklist" id="completion"><h2>ここまでできたら、完了です。</h2><p>読みながら確認するためのチェックです。実際の業務データには反映されません。</p>${a.checks.map((c,i)=>`<label><input type="checkbox" data-check="${i}" ${checked[id]?.includes(i)?'checked':''}>${prose(c)}</label>`).join('')}<div class="check-progress" role="status">${completionText(id)}</div></section><section class="faq"><h2>うまくいかない・間違えたとき</h2>${a.faq.map(([q,ans])=>`<details><summary>${q}</summary><p>${prose(ans)}</p></details>`).join('')}</section><div class="related"><a href="#chapter/${a.chapter}">← ${titles[a.chapter]}の目次</a><span>·</span><a href="#issues">ほかの困りごとを見る</a></div><details class="source-note"><summary>この見本の対象版・参照した資料</summary><p>2026-11-01〜03の配備記録と保存済みテンプレートをもとに、架空データで画面を表示して撮影しました。園の実データ・実機の画面は撮影していません。外枠は撮影用に整理し、一括補完の画面は入力欄を縦に展開しています。保護者の承認画面は登録申請欄を抜粋しています。実際の園での表示・文言の最終確認は今後行います。モック作成日：2026-11-03。</p><a href="https://open.hoikuict.net/${a.source}" target="_blank" rel="noopener">${a.sourceLabel}（公開中の資料）↗</a></details>`;}
function completionText(id){const count=(checked[id]||[]).length;return count===manualArticles[id].checks.length?'✓ すべて確認できました。':`${count} / ${manualArticles[id].checks.length} 項目を確認済み`;}
function renderRoute(focus=true){let parts=location.hash.slice(1).split('/');let [page,arg]=parts;document.getElementById('sidebar').classList.remove('open');document.getElementById('menu-toggle').setAttribute('aria-expanded','false');let html;switch(page){case 'chapters':html=chapters();break;case 'chapter':html=manualChapters[+arg]?chapter(+arg):chapters();break;case 'issues':html=issues();break;case 'help':html=helpOptions[arg]?help(arg):issues();break;case 'answer':html=answers[arg]?answer(arg):issues();break;case 'search':{let q='';try{q=decodeURIComponent(parts.slice(1).join('/'));}catch{}html=search(q);break;}case 'article':if(manualArticles[arg]){if(currentArticle!==arg){currentStep=0;imageState='';allSteps=false;}currentArticle=arg;html=article(arg);break;}default:html=home();}
main.innerHTML=html;document.querySelectorAll('#sidebar nav a').forEach(a=>{const active=a.getAttribute('href')===(location.hash||'#home');a.classList.toggle('current',active);if(active)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
if(page==='search'){try{main.querySelector('#search-input').value=decodeURIComponent(parts.slice(1).join('/'));}catch{}}
bind();document.title=(main.querySelector('h1')?.textContent||'使い方ガイド')+'｜オープン保育ICT・モック';if(focus){window.scrollTo(0,0);main.focus({preventScroll:true});}}
function updateReader(){const y=window.scrollY;main.innerHTML=article(currentArticle);bind();window.scrollTo(0,y);}
function bind(){main.querySelector('#search-form')?.addEventListener('submit',e=>{e.preventDefault();location.hash='search/'+encodeURIComponent(main.querySelector('#search-input').value.trim());});main.querySelectorAll('[data-search]').forEach(b=>b.addEventListener('click',()=>location.hash='search/'+encodeURIComponent(b.dataset.search)));
main.querySelectorAll('[data-step]').forEach(b=>b.addEventListener('click',()=>{currentStep=+b.dataset.step;imageState='';updateReader();main.querySelector('.step-body').scrollIntoView({block:'start'});main.querySelector('.step-heading h2').setAttribute('tabindex','-1');main.querySelector('.step-heading h2').focus({preventScroll:true});}));
main.querySelectorAll('[data-reader]').forEach(b=>b.addEventListener('click',()=>{allSteps=b.dataset.reader==='all';imageState='';updateReader();main.querySelector(`[data-reader="${allSteps?'all':'step'}"]`).focus({preventScroll:true});}));
main.querySelectorAll('[data-state-step]').forEach(s=>s.addEventListener('change',()=>{imageState=s.value;updateReader();main.querySelector('[data-state-step]').focus({preventScroll:true});}));
main.querySelectorAll('[data-zoom]').forEach(b=>b.addEventListener('click',()=>{const dialog=document.getElementById('image-dialog');document.getElementById('zoom-image').src='assets/'+b.dataset.zoom+'.jpg?v=20261103-v5';document.getElementById('zoom-image').alt=b.dataset.caption;document.getElementById('image-title').textContent='画面を拡大して確認';dialog.showModal();}));
main.querySelector('[data-print]')?.addEventListener('click',()=>window.print());main.querySelector('[data-check-jump]')?.addEventListener('click',()=>{document.getElementById('completion').scrollIntoView();main.querySelector('[data-check]').focus({preventScroll:true});});
main.querySelectorAll('[data-check]').forEach(c=>c.addEventListener('change',()=>{checked[currentArticle]=Array.from(main.querySelectorAll('[data-check]:checked')).map(e=>+e.dataset.check);main.querySelector('.check-progress').textContent=completionText(currentArticle);}));}
document.getElementById('close-image').addEventListener('click',()=>document.getElementById('image-dialog').close());
document.getElementById('font-toggle').addEventListener('click',e=>{const large=document.body.classList.toggle('large-text');e.currentTarget.setAttribute('aria-pressed',String(large));e.currentTarget.textContent=large?'文字を標準に':'文字を大きく';});
document.getElementById('menu-toggle').addEventListener('click',e=>{e.currentTarget.setAttribute('aria-expanded',String(document.getElementById('sidebar').classList.toggle('open')));});
document.querySelector('.skip').addEventListener('click',e=>{e.preventDefault();main.focus();main.scrollIntoView();});
window.addEventListener('hashchange',()=>renderRoute());renderRoute(false);
