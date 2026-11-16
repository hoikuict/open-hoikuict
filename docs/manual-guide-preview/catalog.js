const manualChapters = [
  {
    "name": "導入・利用開始",
    "description": "登録からログインまで、使い始める準備をする。",
    "topics": [
      {
        "title": "導入から利用開始まで",
        "url": "https://open.hoikuict.net/start-manual/",
        "role": "管理者・導入担当",
        "kind": "操作手順",
        "source": "start-manual.md"
      },
      {
        "title": "Windowsの園内LAN・園外利用",
        "url": "https://open.hoikuict.net/windows-server-setup/",
        "role": "導入担当",
        "kind": "操作手順",
        "source": "windows-server-setup.md"
      },
      {
        "title": "TrueNASへの導入",
        "url": "https://open.hoikuict.net/truenas-beginner-installation-guide/",
        "role": "導入担当",
        "kind": "操作手順",
        "source": "truenas-beginner-installation-guide.md"
      },
      {
        "title": "初期台帳のExcel準備・登録",
        "url": "https://open.hoikuict.net/initial-ledger-guide/",
        "role": "台帳担当",
        "kind": "操作手順",
        "source": "initial-ledger-guide.md"
      },
      {
        "title": "職員登録・QR案内・再設定",
        "url": "https://open.hoikuict.net/staff-registration-manual/",
        "role": "管理者・職員本人",
        "kind": "操作手順",
        "source": "staff-registration-manual.md"
      },
      {
        "title": "保護者登録・招待・承認",
        "url": "https://open.hoikuict.net/parent-registration-manual/",
        "role": "管理者・保護者本人",
        "kind": "操作手順",
        "source": "parent-registration-manual.md"
      },
      {
        "title": "保護者の利用停止・再開",
        "url": "https://open.hoikuict.net/parent-account-lifecycle/",
        "role": "管理者",
        "kind": "操作手順",
        "source": "parent-account-lifecycle.md"
      }
    ]
  },
  {
    "name": "日々の業務",
    "description": "朝の出欠、保護者の連絡、登園・降園を確かめる。",
    "topics": [
      {
        "title": "朝の出欠・登降園確認",
        "url": "https://open.hoikuict.net/daily-work/",
        "role": "職員",
        "kind": "概要",
        "source": "daily-work.md"
      },
      {
        "title": "月間の登降園時刻を一括補完",
        "url": "https://open.hoikuict.net/daily-work/#bulk-attendance",
        "role": "管理者",
        "kind": "操作手順",
        "source": "daily-work.md#bulk-attendance"
      },
      {
        "title": "キオスクでの登降園受付",
        "url": "https://open.hoikuict.net/chromebook-guardian-kiosk/",
        "role": "職員・端末担当",
        "kind": "操作手順",
        "source": "chromebook-guardian-kiosk.md"
      },
      {
        "title": "保護者の日次連絡と園からの返信",
        "url": "https://open.hoikuict.net/daily-work/",
        "role": "職員・保護者本人",
        "kind": "概要",
        "source": "daily-work.md"
      },
      {
        "title": "お知らせ・アンケート",
        "url": "https://open.hoikuict.net/screen-transition-list/",
        "role": "職員・保護者本人",
        "kind": "概要",
        "source": "screen-transition-list.md"
      },
      {
        "title": "通知の登録と届かないとき",
        "url": "https://open.hoikuict.net/notifications/",
        "role": "職員・保護者本人",
        "kind": "操作手順",
        "source": "notifications.md"
      }
    ]
  },
  {
    "name": "園児・家庭・記録",
    "description": "園児と家庭の情報、健康や育ちの記録を残す。",
    "topics": [
      {
        "title": "園児・家庭・保護者の台帳編集",
        "url": "https://open.hoikuict.net/guardian-account-sync/",
        "role": "台帳担当",
        "kind": "概要",
        "source": "guardian-account-sync.md"
      },
      {
        "title": "園児・保護者の写真",
        "url": "https://open.hoikuict.net/profile-photos/",
        "role": "職員・保護者本人",
        "kind": "操作手順",
        "source": "profile-photos.md"
      },
      {
        "title": "家庭・園児CSVの取り込み",
        "url": "https://open.hoikuict.net/family-guardian-csv-guide/",
        "role": "台帳担当",
        "kind": "操作手順",
        "source": "family-guardian-csv-guide.md"
      },
      {
        "title": "健康・アレルギー・健診記録",
        "url": "https://open.hoikuict.net/health-record-spec-review/",
        "role": "職員",
        "kind": "仕様",
        "source": "health-record-spec-review.md"
      },
      {
        "title": "子どもの観察記録",
        "url": "https://open.hoikuict.net/child-records-spec/",
        "role": "職員",
        "kind": "仕様",
        "source": "child-records-spec.md"
      },
      {
        "title": "児童票の期間選択・修正",
        "url": "https://open.hoikuict.net/child-records-spec/",
        "role": "職員・確認担当",
        "kind": "仕様",
        "source": "child-records-spec.md"
      }
    ]
  },
  {
    "name": "指導計画",
    "description": "年・月・週・日の計画を順番に確認する。",
    "topics": [
      {
        "title": "年案",
        "url": "https://open.hoikuict.net/specifications/#plans",
        "role": "職員・確認担当",
        "kind": "仕様",
        "source": "specifications.md#plans"
      },
      {
        "title": "月案",
        "url": "https://open.hoikuict.net/monthly-print-export-proposal-2026-09-27/",
        "role": "職員・確認担当",
        "kind": "仕様",
        "source": "monthly-print-export-proposal-2026-09-27.md"
      },
      {
        "title": "週案",
        "url": "https://open.hoikuict.net/spec-weekly-daily-plans/",
        "role": "職員・確認担当",
        "kind": "仕様",
        "source": "spec-weekly-daily-plans.md"
      },
      {
        "title": "日案・文例・振返り",
        "url": "https://open.hoikuict.net/spec-daily-plan-v1/",
        "role": "職員・確認担当",
        "kind": "仕様",
        "source": "spec-daily-plan-v1.md"
      }
    ]
  },
  {
    "name": "職員間の共有",
    "description": "予定、議事録、確認してほしい文書を共有する。",
    "topics": [
      {
        "title": "カレンダーの表示・作成",
        "url": "https://open.hoikuict.net/calendar-display/",
        "role": "職員・管理者",
        "kind": "操作手順",
        "source": "calendar-display.md"
      },
      {
        "title": "職員ルーム・議事録",
        "url": "https://open.hoikuict.net/daily-work/",
        "role": "職員",
        "kind": "概要",
        "source": "daily-work.md"
      },
      {
        "title": "文書の確認依頼",
        "url": "https://open.hoikuict.net/daily-work/",
        "role": "職員・管理者",
        "kind": "概要",
        "source": "daily-work.md"
      },
      {
        "title": "職員ホームと要確認",
        "url": "https://open.hoikuict.net/home-return-notifications/",
        "role": "職員・管理者",
        "kind": "概要",
        "source": "home-return-notifications.md"
      }
    ]
  },
  {
    "name": "料金・請求",
    "description": "認定から延長料金、月末の請求まで確認する。",
    "topics": [
      {
        "title": "保育認定・保育必要量",
        "url": "https://open.hoikuict.net/care-need-certification-spec/",
        "role": "台帳担当・料金担当",
        "kind": "仕様",
        "source": "care-need-certification-spec.md"
      },
      {
        "title": "延長保育料金の設定・月次確認",
        "url": "https://open.hoikuict.net/extended-care-fee-spec/",
        "role": "料金担当",
        "kind": "仕様",
        "source": "extended-care-fee-spec.md"
      },
      {
        "title": "請求への転送・口座情報",
        "url": "https://open.hoikuict.net/extended-care-billing-transfer-spec/",
        "role": "請求担当",
        "kind": "仕様",
        "source": "extended-care-billing-transfer-spec.md"
      }
    ]
  },
  {
    "name": "運用・困ったとき",
    "description": "日々の点検、バックアップ、困ったときの対応。",
    "topics": [
      {
        "title": "バックアップ取得・確認",
        "url": "https://open.hoikuict.net/backup-verification-guide/",
        "role": "運用担当",
        "kind": "操作手順",
        "source": "backup-verification-guide.md"
      },
      {
        "title": "バックアップからの復元",
        "url": "https://open.hoikuict.net/restore-from-app/",
        "role": "運用担当",
        "kind": "概要",
        "source": "restore-from-app.md"
      },
      {
        "title": "毎日の点検・障害時の対応",
        "url": "https://open.hoikuict.net/operations/",
        "role": "運用担当",
        "kind": "概要",
        "source": "operations.md"
      }
    ]
  }
];
