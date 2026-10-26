from cdp.resolve.blocking import blocking_keys, candidate_pairs

from .factories import rec


def test_keys_include_domain_name_prefix_token_and_phone():
    r = rec("api:1", "Kestrel Data GmbH", domain="kestreldata.de", phone_norm="49301234567")
    assert blocking_keys(r) == {
        "domain:kestreldata.de",
        "name:kest|DE",
        "tok:data|rel|DE",
        "phone:49301234567",
    }


def test_shared_domain_creates_candidate_even_with_different_names():
    a = rec("api:1", "Kestrel Data", domain="kestrel.io", country_code="DE")
    b = rec("directory:2", "KD Analytics", domain="kestrel.io", country_code="GB")
    assert ("api:1", "directory:2") in candidate_pairs([a, b]).pairs


def test_same_name_in_other_country_is_not_blocked_together():
    a = rec("api:1", "Kestrel Data", country_code="DE")
    b = rec("api:2", "Kestrel Data", country_code="FR")
    assert candidate_pairs([a, b]).n_pairs == 0


def test_spacing_variant_shares_name_block():
    a = rec("api:1", "Cobalt Ridge Labs")
    b = rec("registry:1", "CobaltRidge Labs GmbH")
    result = candidate_pairs([a, b])
    assert result.pairs[("api:1", "registry:1")] >= {"name"}


def test_oversized_blocks_are_skipped_and_reported():
    records = [
        rec(f"api:{i}", n, domain="hosting.example")
        for i, n in enumerate(["Alpha", "Bravo", "Charlie", "Delta", "Echo"])
    ]
    result = candidate_pairs(records, max_block_size=3)
    assert result.skipped_blocks == {"domain:hosting.example": 5}
    assert all("domain" not in keys for keys in result.pairs.values())
