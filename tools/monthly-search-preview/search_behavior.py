"""Proposed matching for fictional preview only; never rewrite source text."""
import unicodedata


def search_key(value: str, mode: str = "spelling") -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    if mode == "current":
        return text
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    text = text.replace("真似", "まね")
    if mode == "related":
        text = text.replace("模倣", "まね")
    return text


def matches(text: str, query: str, mode: str = "spelling") -> bool:
    haystack = search_key(text, mode)
    return all(word in haystack for word in search_key(query, mode).split())


EXAMPLES = (
    "友達の動きを真似して、体を動かすことを楽しむ。",
    "友達の動きをまねして、体を動かすことを楽しむ。",
    "友達の動きをマネして、体を動かすことを楽しむ。",
    "友達の動きをﾏﾈして、いろいろな動きを楽しむ。",
    "友達の動きを模倣して、体を動かすことを楽しむ。",
    "保育者のしぐさを真似して、やり取りを楽しむ。",
    "ボールを転がして、保育者とのやり取りを楽しむ。",
    "ぼーるを転がして、友達とのやり取りを楽しむ。",
    "身近な素材を並べて、色や形の違いを楽しむ。",
)
