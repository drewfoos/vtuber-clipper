import re
import unicodedata

def slugify(text: str, max_len: int = 60, index: int | None = None) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lower = ascii_only.lower()
    no_punct = re.sub(r"[^\w\s-]", "", lower)
    hyphenated = re.sub(r"[\s_]+", "-", no_punct).strip("-")
    truncated = hyphenated[:max_len].rstrip("-")
    if index is not None:
        return f"{index:02d}_{truncated}"
    return truncated
