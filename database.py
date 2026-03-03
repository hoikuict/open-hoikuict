from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import text
from datetime import date

DATABASE_URL = "sqlite:///./hoikuict.db"
engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
    _migrate_add_child_columns()


def _migrate_add_child_columns():
    """既存DBに自宅住所・電話カラムを追加（マイグレーション）"""
    try:
        with engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(children)"))
            cols = [row[1] for row in result]
            if not cols:
                return  # テーブル未作成（初回）
            if "home_address" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN home_address VARCHAR"))
            if "home_phone" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN home_phone VARCHAR"))
            if "older_sibling_id" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN older_sibling_id INTEGER REFERENCES children(id)"))
            conn.commit()
    except Exception:
        pass  # テーブルがない場合はスキップ


def seed_sample_data():
    """開発用サンプルデータ投入"""
    from models import Child, ChildStatus, Guardian
    with Session(engine) as session:
        # すでにデータがあればスキップ
        from sqlmodel import select
        if session.exec(select(Child)).first():
            return

        samples = [
            Child(last_name="田中", first_name="さくら", last_name_kana="タナカ", first_name_kana="サクラ",
                  birth_date=date(2020, 4, 5), enrollment_date=date(2023, 4, 1), status=ChildStatus.enrolled,
                  home_address="東京都渋谷区〇〇1-2-3", home_phone="03-1234-5678",
                  extra_data={"allergy": ["卵"], "medical_notes": "特になし"}),
            Child(last_name="佐藤", first_name="はると", last_name_kana="サトウ", first_name_kana="ハルト",
                  birth_date=date(2019, 8, 12), enrollment_date=date(2022, 4, 1), status=ChildStatus.enrolled,
                  home_address="東京都新宿区△△4-5-6", home_phone="03-2345-6789",
                  extra_data={"allergy": [], "medical_notes": "喘息あり"}),
            Child(last_name="鈴木", first_name="ゆい", last_name_kana="スズキ", first_name_kana="ユイ",
                  birth_date=date(2021, 1, 20), enrollment_date=date(2024, 4, 1), status=ChildStatus.enrolled,
                  home_address="東京都港区□□7-8-9", home_phone="03-3456-7890",
                  extra_data={"allergy": ["小麦", "乳"], "medical_notes": ""}),
            Child(last_name="山田", first_name="こうた", last_name_kana="ヤマダ", first_name_kana="コウタ",
                  birth_date=date(2018, 11, 3), enrollment_date=date(2021, 4, 1),
                  withdrawal_date=date(2024, 3, 31), status=ChildStatus.graduated,
                  home_address="東京都目黒区××10-11-12", home_phone="03-4567-8901",
                  extra_data={"allergy": [], "medical_notes": ""}),
            Child(last_name="伊藤", first_name="みお", last_name_kana="イトウ", first_name_kana="ミオ",
                  birth_date=date(2020, 6, 15), enrollment_date=date(2023, 4, 1), status=ChildStatus.enrolled,
                  home_address="東京都世田谷区◇◇13-14-15", home_phone="03-5678-9012",
                  extra_data={"allergy": ["そば"], "medical_notes": "エピペン携帯"}),
        ]
        for child in samples:
            session.add(child)
        session.flush()  # IDを取得するため

        # 保護者データ（1人または2人、就労の場合は勤務先情報）
        guardians_data = [
            (1, "田中", "健一", "タナカ", "ケンイチ", "父", "090-1111-2222", "株式会社A", "東京都中央区", "03-1111-2222", 1),
            (1, "田中", "美咲", "タナカ", "ミサキ", "母", "090-2222-3333", "B商事", "東京都千代田区", "03-2222-3333", 2),
            (2, "佐藤", "拓也", "サトウ", "タクヤ", "父", "090-3333-4444", "C建設", "東京都品川区", "03-3333-4444", 1),
            (2, "佐藤", "由美", "サトウ", "ユミ", "母", None, None, None, None, 2),  # 専業主婦
            (3, "鈴木", "一郎", "スズキ", "イチロウ", "父", "090-5555-6666", "D工業", "神奈川県横浜市", "045-5555-6666", 1),
            (3, "鈴木", "裕子", "スズキ", "ユウコ", "母", "090-6666-7777", "E病院", "東京都渋谷区", "03-6666-7777", 2),
            (4, "山田", "大輔", "ヤマダ", "ダイスケ", "父", "090-7777-8888", "F運輸", "東京都大田区", "03-7777-8888", 1),
            (5, "伊藤", "真理子", "イトウ", "マリコ", "母", "090-9999-0000", "G保育園", "東京都杉並区", "03-9999-0000", 1),
        ]
        for cid, ln, fn, lnk, fnk, rel, ph, wp, wpa, wph, ord in guardians_data:
            session.add(Guardian(child_id=cid, last_name=ln, first_name=fn, last_name_kana=lnk, first_name_kana=fnk,
                                relationship=rel, phone=ph, workplace=wp, workplace_address=wpa, workplace_phone=wph, order=ord))
        session.commit()
