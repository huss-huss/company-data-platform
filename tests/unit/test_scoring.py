import pytest

from cdp.resolve.scoring import Thresholds, compute_features, score

from .factories import rec


def test_identical_records_score_as_match():
    a = rec("api:1", "Kestrel Data GmbH", domain="kestreldata.de", city_norm="berlin")
    b = rec("registry:1", "KESTREL DATA G.m.b.H.", domain="kestreldata.de", city_norm="berlin")
    assert Thresholds().decide(score(compute_features(a, b))) == "match"


def test_typo_and_collapsed_spacing_are_not_extra_tokens():
    a = rec("api:1", "Valewood Dtaa BV")
    b = rec("registry:1", "ValewoodData B.V.")
    assert compute_features(a, b).extra_tokens == 0


def test_extra_word_is_penalised():
    a = rec("api:1", "Kestrel Data GmbH", city_norm="berlin")
    b = rec("api:2", "Kestrel Data Labs GmbH", city_norm="berlin")
    f = compute_features(a, b)
    assert f.extra_tokens == 1
    assert score(f) < Thresholds().match


def test_country_mismatch_blocks_a_merge():
    a = rec("api:1", "Kestrel Data", country_code="DE")
    b = rec("api:2", "Kestrel Data", country_code="FR")
    assert Thresholds().decide(score(compute_features(a, b))) == "non_match"


def test_missing_values_are_neutral():
    a = rec("api:1", "Kestrel Data", phone_norm=None)
    b = rec("api:2", "Kestrel Data", phone_norm="4912345678")
    c = rec("api:3", "Kestrel Data", phone_norm="4999999999")
    neutral = score(compute_features(a, b))
    assert compute_features(a, b).phone_match is None
    assert score(compute_features(b, c)) < neutral


def test_shared_domain_and_phone_raise_score():
    a = rec("api:1", "Kestrel Analytics")
    b = rec("api:2", "Kestrel Analytix")
    base = score(compute_features(a, b))
    a2 = rec("api:1", "Kestrel Analytics", domain="k.de", phone_norm="4930111111")
    b2 = rec("api:2", "Kestrel Analytix", domain="k.de", phone_norm="4930111111")
    assert score(compute_features(a2, b2)) > base


def test_thresholds():
    t = Thresholds(match=0.9, review=0.5)
    assert [t.decide(s) for s in (0.95, 0.9, 0.7, 0.5, 0.2)] == [
        "match",
        "match",
        "review",
        "review",
        "non_match",
    ]
    with pytest.raises(ValueError):
        Thresholds(match=0.4, review=0.6)
