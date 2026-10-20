rows = [
    "あいうえお",
    "かきくけこ",
    "さしすせそ",
    "たちつてと",
    "なにぬねの",
    "はひふへほ",
    "まみむめも",
    "らりるれろ",
    "がぎぐげご",
    "ざじずぜぞ",
    "だぢづでど",
    "ばびぶべぼ",
    "ぱぴぷぺぽ",
]
cons = ["", "k", "s", "t", "n", "h", "m", "r", "g", "z", "d", "b", "p"]
vowels = "aiueo"
table = {}
for row, c in zip(rows, cons):
    for k, v in zip(row, vowels):
        table[k] = [c, v] if c else [v]
table.update(
    {
        "し": ["sh", "i"],
        "ち": ["ch", "i"],
        "つ": ["ts", "u"],
        "ふ": ["f", "u"],
        "じ": ["j", "i"],
        "ぢ": ["j", "i"],
        "づ": ["z", "u"],
        "ん": ["N"],
        "っ": ["cl"],
        "や": ["y", "a"],
        "ゆ": ["y", "u"],
        "よ": ["y", "o"],
        "わ": ["w", "a"],
        "を": ["o"],
        "ゔ": ["b", "u"],
    }
)
for k, c in [
    ("き", "ky"),
    ("し", "sh"),
    ("ち", "ch"),
    ("に", "ny"),
    ("ひ", "hy"),
    ("み", "my"),
    ("り", "ry"),
    ("ぎ", "gy"),
    ("じ", "j"),
    ("び", "by"),
    ("ぴ", "py"),
]:
    for sm, v in zip("ゃゅょ", "auo"):
        table[k + sm] = [c, v]
for k, v in zip("ぁぃぅぇぉ", "aiueo"):
    table[k] = [v]
# These combinations are one mora, not a full vowel followed by a small vowel.
table.update(
    {
        "てぃ": ["t", "i"],
        "でぃ": ["d", "i"],
        "しぇ": ["sh", "e"],
        "ちぇ": ["ch", "e"],
        "じぇ": ["j", "e"],
        "とぅ": ["t", "u"],
        "どぅ": ["d", "u"],
        "ふぁ": ["f", "a"],
        "ふぃ": ["f", "i"],
        "ふぇ": ["f", "e"],
        "ふぉ": ["f", "o"],
        "うぃ": ["w", "i"],
        "うぇ": ["w", "e"],
        "うぉ": ["w", "o"],
    }
)


def phones(text, *, normalize_long_vowels=True):
    text = "".join(chr(ord(c) - 96) if "ァ" <= c <= "ヶ" else c for c in text)
    out = []
    i = 0
    while i < len(text):
        if text[i] == "ー":
            if not out or out[-1] not in vowels:
                raise ValueError(f"Long vowel has no preceding vowel: {text}")
            out.append(out[-1])
            i += 1
            continue
        key = text[i : i + 2] if text[i : i + 2] in table else text[i]
        if key not in table:
            raise ValueError(f"Unknown kana {key!r}; provide an explicit phonemes array")
        seq = table[key]
        # Override token.phonemes when the sung reading differs from these defaults.
        if normalize_long_vowels and key == "う" and out and out[-1] == "o":
            seq = ["o"]
        if normalize_long_vowels and key == "い" and out and out[-1] == "e":
            seq = ["e"]
        out += seq
        i += len(key)
    return out
