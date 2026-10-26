"""Pure normalisation functions shared by dbt (as DuckDB UDFs) and the resolver.

Keeping one implementation avoids the classic drift where SQL and Python disagree on what a
"normalised name" is. See ``cdp.dbt_plugin`` for the UDF registration.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Letters NFKD does not decompose into ASCII.
_TRANSLIT = str.maketrans(
    {
        "ø": "o",
        "Ø": "O",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
        "ß": "ss",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "þ": "th",
        "Þ": "Th",
        "ı": "i",  # noqa: RUF001 - Turkish dotless i, intentional
    }
)

# Legal-form tokens, matched only at the *end* of a name after punctuation removal.
# Multi-token forms are listed as tuples so "share company" is stripped but "share" alone isn't.
LEGAL_SUFFIXES: tuple[tuple[str, ...], ...] = tuple(
    tuple(s.split())
    for s in sorted(
        {
            "gmbh",
            "ag",
            "aktiengesellschaft",
            "kg",
            "ug",
            "ltd",
            "limited",
            "plc",
            "llp",
            "inc",
            "incorporated",
            "llc",
            "corp",
            "corporation",
            "co",
            "company",
            "sas",
            "sarl",
            "sa",
            "sl",
            "bv",
            "nv",
            "ab",
            "aktiebolag",
            "oy",
            "as",
            "aps",
            "spa",
            "srl",
            "pty",
            "pvt",
            "sc",
            "share company",
            "private limited company",
            "public limited company",
            "pty ltd",
            "co ltd",
        },
        key=lambda s: -len(s.split()),
    )
)

FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.de",
        "web.de",
        "mail.ru",
    }
)

_ABBREV_DOTS = re.compile(r"\b(?:[a-z]\.){2,}")  # g.m.b.h.  s.a.s.  b.v.
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")


def fold(text: str) -> str:
    """Unicode -> lowercase ASCII (accents stripped, special letters transliterated)."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


@lru_cache(maxsize=65536)
def clean_name(name: str | None) -> str | None:
    """Folded, punctuation-free name *including* legal suffix: ``'Nørdvik G.m.b.H.'`` ->
    ``'nordvik gmbh'``."""
    if name is None:
        return None
    text = fold(name).replace("&", " and ")
    text = _ABBREV_DOTS.sub(lambda m: m.group(0).replace(".", ""), text)
    text = _NON_ALNUM.sub(" ", text).strip()
    return text or None


def strip_legal_suffix(cleaned: str) -> str:
    tokens = cleaned.split()
    changed = True
    while changed and len(tokens) > 1:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            n = len(suffix)
            if len(tokens) > n and tuple(tokens[-n:]) == suffix:
                tokens = tokens[:-n]
                changed = True
                break
    return " ".join(tokens)


@lru_cache(maxsize=65536)
def normalize_name(name: str | None) -> str | None:
    """Comparable company name: folded, punctuation removed, legal form stripped."""
    cleaned = clean_name(name)
    return strip_legal_suffix(cleaned) if cleaned else None


def legal_form(name: str | None) -> str | None:
    """The stripped legal-form tokens, e.g. ``'gmbh'`` (useful as a weak feature)."""
    cleaned = clean_name(name)
    if not cleaned:
        return None
    core = strip_legal_suffix(cleaned)
    rest = cleaned[len(core) :].strip()
    return rest or None


def name_key(name: str | None) -> str | None:
    """Space-free key so ``'Cobalt Ridge'`` and ``'CobaltRidge'`` collide in blocking."""
    norm = normalize_name(name)
    return norm.replace(" ", "") if norm else None


def extract_domain(value: str | None) -> str | None:
    """Host from a URL, e-mail address or bare domain; lower-cased, ``www.`` removed."""
    if not value:
        return None
    text = value.strip().lower()
    if "@" in text and "://" not in text:
        text = text.rsplit("@", 1)[1]
    text = _SCHEME.sub("", text)
    text = re.split(r"[/?#]", text, maxsplit=1)[0]
    text = text.split("@")[-1].split(":")[0].strip(".")
    text = text.removeprefix("www.")
    if "." not in text or not re.fullmatch(r"[a-z0-9.-]+", text):
        return None
    return text


def is_free_mail(domain: str | None) -> bool:
    return domain in FREE_MAIL_DOMAINS


def company_domain(value: str | None) -> str | None:
    """Domain usable as a company identifier (free-mail providers excluded)."""
    domain = extract_domain(value)
    return None if domain is None or is_free_mail(domain) else domain


def normalize_phone(value: str | None) -> str | None:
    """Digits only, international prefix ``00`` treated like ``+``. Short numbers -> None."""
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if value.strip().startswith("00") or digits.startswith("00"):
        digits = digits[2:]
    return digits if len(digits) >= 8 else None
