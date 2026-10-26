"""Pairwise scoring: interpretable similarity features combined in log-odds space.

Each feature contributes evidence for or against a match; missing values contribute nothing
(absence of a phone number is not evidence of a different company). The weights are
hand-set, Fellegi-Sunter style, and documented here rather than learned - with ~500 records
a learned model would overfit and be harder to explain to a data steward.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from rapidfuzz import fuzz
from rapidfuzz.distance import JaroWinkler

from cdp.resolve.records import Record


@dataclass(frozen=True)
class Thresholds:
    match: float = 0.90
    review: float = 0.50

    def __post_init__(self) -> None:
        if not 0 <= self.review <= self.match <= 1:
            raise ValueError("expected 0 <= review <= match <= 1")

    def decide(self, score: float) -> str:
        if score >= self.match:
            return "match"
        if score >= self.review:
            return "review"
        return "non_match"


@dataclass(frozen=True)
class Features:
    name_sim: float
    name_jw: float
    extra_tokens: int
    domain_match: int | None
    phone_match: int | None
    country_match: int | None
    city_match: int | None
    street_sim: float | None

    def as_dict(self) -> dict[str, float | int | None]:
        return asdict(self)


def _eq(a: str | None, b: str | None) -> int | None:
    if not a or not b:
        return None
    return int(a == b)


def _unexplained_tokens(a: Record, b: Record) -> int:
    """Whole words in ``a``'s name with no counterpart in ``b`` ("Kestrel Data *Labs*").

    A token is *explained* if it (approximately) occurs inside ``b``'s space-free name key,
    which covers typos ("dtaa" ~ "data") and collapsed spacing ("evergleamcoffee").
    """
    tokens_b = set(b.name_norm.split())
    count = 0
    for t in set(a.name_norm.split()) - tokens_b:
        if fuzz.partial_ratio(t, b.name_key) < 75:
            count += 1
    return count


def compute_features(a: Record, b: Record) -> Features:
    name_sim = max(fuzz.ratio(a.name_norm, b.name_norm), fuzz.ratio(a.name_key, b.name_key)) / 100.0
    extra = _unexplained_tokens(a, b) + _unexplained_tokens(b, a)
    street_sim = None
    if a.street and b.street:
        street_sim = fuzz.token_sort_ratio(a.street.lower(), b.street.lower()) / 100.0
    city = None
    if a.city_norm and b.city_norm:
        city = int(fuzz.ratio(a.city_norm, b.city_norm) >= 90)
    return Features(
        name_sim=name_sim,
        name_jw=JaroWinkler.normalized_similarity(a.name_key, b.name_key),
        extra_tokens=extra,
        domain_match=_eq(a.domain, b.domain),
        phone_match=_eq(a.phone_norm, b.phone_norm),
        country_match=_eq(a.country_code, b.country_code),
        city_match=city,
        street_sim=street_sim,
    )


# Evidence weights (log-odds contributions). See module docstring.
WEIGHTS = {
    "bias": -7.0,
    "name_sim": 8.5,  # multiplied by the [0, 1] similarity
    "name_jw": 1.0,
    "extra_token": -2.5,  # per unexplained extra whole word
    "domain_match": 3.5,
    "domain_mismatch": -1.0,  # weak: regional vs global sites are common
    "phone_match": 3.0,
    "phone_mismatch": -0.5,
    "country_match": 0.5,
    "country_mismatch": -5.0,
    "city_match": 1.0,
    "city_mismatch": -0.5,  # companies move
    "street_match": 1.0,  # street_sim >= 0.9
}


def log_odds(f: Features) -> float:
    w = WEIGHTS
    z = w["bias"] + w["name_sim"] * f.name_sim + w["name_jw"] * f.name_jw
    z += w["extra_token"] * f.extra_tokens
    if f.domain_match is not None:
        z += w["domain_match"] if f.domain_match else w["domain_mismatch"]
    if f.phone_match is not None:
        z += w["phone_match"] if f.phone_match else w["phone_mismatch"]
    if f.country_match is not None:
        z += w["country_match"] if f.country_match else w["country_mismatch"]
    if f.city_match is not None:
        z += w["city_match"] if f.city_match else w["city_mismatch"]
    if f.street_sim is not None and f.street_sim >= 0.9:
        z += w["street_match"]
    return z


def score(f: Features) -> float:
    """Match probability-like score in [0, 1]."""
    return 1.0 / (1.0 + math.exp(-log_odds(f)))
