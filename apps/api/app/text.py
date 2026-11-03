"""Text matching shared by term resolution and conversation search."""

import re
import unicodedata


def fold(text: str) -> str:
    """Lowercase, strip diacritics (including đ) and collapse punctuation to single spaces."""
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return " ".join(re.split(r"[^a-z0-9]+", text)).strip()
