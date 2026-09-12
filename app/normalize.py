import re

UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
LEADING = re.compile(r"^(der|die|das|ein|eine|einen|einem|einer|sich|zu)\s+")


def make_search_key(word: str) -> str:
    s = word.strip().lower().translate(UMLAUTS)
    prev = None
    while prev != s:  # strips stacked prefixes: "sich zu ..."
        prev = s
        s = LEADING.sub("", s).strip()
    return re.sub(r"[^a-z0-9 ]", "", s)
