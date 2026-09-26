"""Name normalisation and trigram similarity for entity resolution.

``normalize_name`` produces the canonical key used for exact and alias matches:
lower case, punctuation and possessives removed (eponyms: "Crohn's disease" ==
"Crohn disease"), UK spellings mapped to US, and a small set of unambiguous
radiology abbreviations expanded. ``trigram_similarity`` mirrors pg_trgm so the
SQL candidate search and the Python decision agree. No new dependencies.
"""

from __future__ import annotations

import re
import unicodedata

AUTO_MERGE = 0.92
CANDIDATE = 0.80

_SPELLING: tuple[tuple[str, str], ...] = (
    (r"\bhaem", "hem"), (r"\bpaed", "ped"), (r"orthopaed", "orthoped"),
    (r"\boesophag", "esophag"), (r"\boestr", "estr"), (r"oedema", "edema"),
    (r"ischaem", "ischem"), (r"anaem", "anem"), (r"leukaem", "leukem"),
    (r"\bcaec", "cec"), (r"\bfoet", "fet"), (r"tumour", "tumor"), (r"colour", "color"),
    (r"haemat", "hemat"), (r"\bgynaec", "gynec"), (r"\bdiarrhoe", "diarrhe"),
    (r"\banaesth", "anesth"), (r"sulphur", "sulfur"), (r"fibre\b", "fiber"),
    (r"centre\b", "center"), (r"litre\b", "liter"), (r"metre\b", "meter"),
)
_ABBREVIATIONS: dict[str, str] = {
    "hrct": "high resolution computed tomography",
    "mrcp": "magnetic resonance cholangiopancreatography",
    "ercp": "endoscopic retrograde cholangiopancreatography",
    "dwi": "diffusion weighted imaging",
    "adc": "apparent diffusion coefficient",
    "flair": "fluid attenuated inversion recovery",
    "swi": "susceptibility weighted imaging",
    "ctpa": "computed tomography pulmonary angiography",
    "uip": "usual interstitial pneumonia",
    "nsip": "nonspecific interstitial pneumonia",
    "ards": "acute respiratory distress syndrome",
    "copd": "chronic obstructive pulmonary disease",
    "hcc": "hepatocellular carcinoma",
    "rcc": "renal cell carcinoma",
    "fnh": "focal nodular hyperplasia",
    "gist": "gastrointestinal stromal tumor",
    "avn": "avascular necrosis",
    "ddh": "developmental dysplasia of the hip",
    "nec": "necrotizing enterocolitis",
    "sah": "subarachnoid hemorrhage",
    "sdh": "subdural hematoma",
    "edh": "extradural hematoma",
    "pres": "posterior reversible encephalopathy syndrome",
    "tb": "tuberculosis",
    "birads": "breast imaging reporting and data system",
    "lirads": "liver imaging reporting and data system",
    "tirads": "thyroid imaging reporting and data system",
}
_STRIP = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Canonical matching key for a concept name or alias."""
    value = name.replace(chr(0x2019), "'")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"'s\b", "", value)
    value = value.replace("-", " ").replace("/", " ")
    value = _STRIP.sub(" ", value)
    value = _SPACE.sub(" ", value).strip()
    for pattern, replacement in _SPELLING:
        value = re.sub(pattern, replacement, value)
    compact = value.replace(" ", "")
    if compact in _ABBREVIATIONS:
        return _ABBREVIATIONS[compact]
    return " ".join(_singular(word) for word in value.split())


def _singular(word: str) -> str:
    """Singular form for matching keys only; it must be consistent, not pretty."""
    if len(word) <= 4 or word.endswith(("ss", "us", "is")):
        return word
    if word.endswith(("oses", "stases")):
        return word[:-2] + "is"
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("s"):
        return word[:-1]
    return word


def alias_keys(name: str, aliases: list[str] | tuple[str, ...]) -> list[str]:
    """Distinct normalised keys for a concept name plus its aliases."""
    keys: list[str] = []
    for value in (name, *aliases):
        key = normalize_name(value)
        if key and key not in keys:
            keys.append(key)
    return keys


def trigrams(value: str) -> set[str]:
    """pg_trgm-compatible trigram set (each word padded with two leading spaces)."""
    grams: set[str] = set()
    for word in re.findall(r"[a-z0-9]+", value.lower()):
        padded = f"  {word} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return grams


def trigram_similarity(left: str, right: str) -> float:
    a, b = trigrams(left), trigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def collapse_ws(value: str) -> str:
    return _SPACE.sub(" ", value).strip()


def word_count(value: str) -> int:
    return len(value.split())
