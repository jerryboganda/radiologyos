"""Readable text from slide decks: symbol-font bullets become real bullets.

PowerPoint bullets set in Symbol/Wingdings fonts come out of the PDF text layer
as the replacement character U+FFFD or as private-use code points. They are
shown to the owner and quoted as evidence, so they are mapped to "•" (a bullet
is the only thing they ever were in study decks).
"""

from __future__ import annotations

BULLET = "•"
_SYMBOL_BULLETS = ("�", "", "", "", "", "", "",
                   "", "")
_TABLE = str.maketrans({ch: BULLET for ch in _SYMBOL_BULLETS})


def tidy(text: str) -> str:
    return text.translate(_TABLE)
