"""Fictional examples for every searchable field in the browser preview.

These are interaction samples, not imported nursery records or AI suggestions.
Keep IDs stable so already-saved preview origins continue to resolve.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

from plan_docs.services.monthly_library import field_definitions, normalize


COMMON = {
    "common:goal": ("安心できる環境で、好きな遊びを見つけて楽しむ。", "身近な人との関わりを楽しみ、自分の気持ちを表す。"),
    "common:home": ("家庭での睡眠や食事の様子を伝え合う。", "園で楽しんだ遊びや子どもの姿を家庭に伝える。"),
    "common:review": ("好きな遊びを繰り返し楽しむ姿が見られた。", "一人ひとりの思いを受け止める時間をさらに確保したい。"),
}
PERSONAL = (
    {
        "life": ("保育者に気持ちを受け止めてもらい、安心して過ごす。", "一人ひとりの生活リズムに合わせて休息する。"),
        "play": ("音のする玩具に手を伸ばして楽しむ。", "保育者と顔を見合わせてやり取りを楽しむ。"),
        "help": ("手を伸ばして触れられる位置に玩具を用意する。", "表情や声を受け止め、ゆったりと関わる。"),
        "review": ("保育者の声に反応して笑顔を見せていた。", "興味のある玩具へ自分から手を伸ばしていた。"),
    },
    {
        "life": ("保育者と一緒に手洗いをする。", "食事や着替えで自分でやってみようとする。"),
        "play": ("容器に物を入れたり出したりして楽しむ。", "保育者と一緒に見立て遊びを楽しむ。"),
        "help": ("安心して歩いたり探索したりできる場所を用意する。", "しぐさや言葉から思いを受け止めて応答する。"),
        "review": ("自分でやってみようとする姿が増えた。", "好きな玩具を見つけて繰り返し遊んでいた。"),
    },
    {
        "life": ("保育者に見守られながら手洗いや着替えをする。", "生活の中で自分の思いを言葉やしぐさで伝える。"),
        "play": ("友達や保育者と簡単なごっこ遊びを楽しむ。", "身近な素材を並べたり組み合わせたりして遊ぶ。"),
        "help": ("自分で選べるように遊具や素材を取り出しやすく置く。", "友達と関わる場面で互いの思いを言葉にして伝える。"),
        "review": ("友達の遊びに関心をもち、まねをして楽しんでいた。", "気持ちを伝えようとする姿を丁寧に受け止めていきたい。"),
    },
)
GROUP = {
    "care": (
        ("安心して気持ちを表し、落ち着いて過ごす。", "体調に合わせて休息し、心地よく生活する。"),
        ("一人で落ち着いて過ごせる場所を用意する。", "室温や換気に配慮し、休息できる環境を整える。"),
        ("困ったときに保育者へ気持ちを伝えようとする。", "疲れを感じたときに休みたいことを伝える。"),
        ("一人ひとりの気持ちを受け止め、安心できるよう関わる。", "表情や活動の様子から疲れに気づき、休息を促す。"),
    ),
    "health": (
        ("体を動かす心地よさを感じながら遊ぶ。", "手洗いなどの生活習慣を身につけていく。"),
        ("走る、跳ぶなどの動きを楽しめる場を用意する。", "手洗いの手順を見て分かるように掲示する。"),
        ("好きな運動遊びを見つけて繰り返し楽しむ。", "遊びの後に自分から手洗いをしようとする。"),
        ("体の動かし方や運動量を一人ひとりに合わせる。", "できた喜びに共感し、無理なく取り組めるようにする。"),
    ),
    "relations": (
        ("友達と一緒に遊ぶ楽しさを味わう。", "自分の思いを伝え、相手の思いにも気づく。"),
        ("友達と一緒に使える遊具や素材を用意する。", "少人数で落ち着いて遊べる空間を設ける。"),
        ("友達を遊びに誘い、一緒に楽しもうとする。", "玩具の使い方や順番について思いを伝える。"),
        ("互いの思いを聞き、一緒に遊ぶ方法を考える。", "友達と関われた喜びを受け止める。"),
    ),
    "nature": (
        ("身近な自然や物に興味をもち、触れて楽しむ。", "物の形や大きさの違いに気づく。"),
        ("自然物を比べたり並べたりできる場所を用意する。", "集めた物を観察できる容器や図鑑を用意する。"),
        ("見つけた物を友達や保育者に見せようとする。", "形や色の違いに気づき、分けたり並べたりする。"),
        ("子どもの発見に共感し、一緒に調べる。", "安全に触れられる素材を選び、扱い方を知らせる。"),
    ),
    "language": (
        ("経験したことや思いを言葉で伝える。", "絵本や物語の言葉のやり取りを楽しむ。"),
        ("好きな絵本を落ち着いて読める場所を整える。", "話したいことをゆっくり伝えられる時間を設ける。"),
        ("遊びの中で経験したことを友達に話そうとする。", "物語の言葉をまねしてやり取りを楽しむ。"),
        ("最後まで話を聞き、伝わった喜びを味わえるようにする。", "子どもの言葉に応答し、やり取りが続くようにする。"),
    ),
    "expression": (
        ("音やリズムに合わせて表現する楽しさを味わう。", "好きな素材を使い、思い思いに作って楽しむ。"),
        ("描いたり作ったりできる素材を選びやすく並べる。", "歌やリズム遊びを楽しめる空間を確保する。"),
        ("好きな色や素材を選んで表現しようとする。", "友達の動きを見ながら体を動かして楽しむ。"),
        ("一人ひとりの表現を受け止め、楽しさに共感する。", "作る過程や工夫したところを言葉にして伝える。"),
    ),
}


def seed_preview_phrases(path: Path) -> int:
    """Add only to the known fictional test corpus; preserve existing origins."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as con:
        sources = con.execute("SELECT id, rel_path FROM source ORDER BY id").fetchall()
        if sources not in ([(1, "fictional/2025-10.xls")],
                           [(1, "fictional/2025-10.xls"), (2, "fictional/monthly-preview.xls")]):
            raise ValueError("Only the fictional monthly-library fixture may be seeded")
        con.execute("INSERT OR IGNORE INTO source VALUES(2, 'fictional/monthly-preview.xls')")
        con.execute("INSERT OR IGNORE INTO cell VALUES(2, 2, '操作確認用（架空）')")
        rows = []
        for age in range(6):
            samples = dict(COMMON)
            if age < 3:
                samples.update({f"child:1:{key}": value for key, value in PERSONAL[age].items()})
            else:
                for domain, columns in GROUP.items():
                    for column, examples in zip(("goal", "environment", "expected", "support"), columns):
                        samples[f"group:{domain}:{column}"] = examples
                samples["group:food"] = ("食材に興味をもち、楽しく食事をする。", "食材を見たり触れたりして、色や形に気づく。")
            for month in range(1, 13):
                definitions = field_definitions({"age": age, "children": [{"ref": "child:1"}]}, f"2026-{month:02}")
                for index, (key, examples) in enumerate(samples.items()):
                    definition = definitions[key]
                    for variant, example in enumerate(examples):
                        text = "【架空例】" + example
                        phrase_id = 10000 + age * 10000 + month * 100 + index * 2 + variant
                        rows.append((phrase_id, text, normalize(text), age, month,
                                     definition["item"], definition["section"], definition["ryoiki"]))
        con.executemany("INSERT OR IGNORE INTO phrase VALUES(?,2,2,?,?,?,?,2025,?,?,?)", rows)
        con.commit()
        return len(rows)
