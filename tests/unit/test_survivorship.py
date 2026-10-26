import pytest

from cdp.resolve.survivorship import entity_id_for, survive

from .factories import rec


def test_most_trusted_source_wins_per_field():
    registry = rec(
        "registry:R1",
        "Kestrel Data GmbH",
        registration_number="DE-1",
        street="1 Main St",
        city="Berlin",
        source_updated_at="2025-01-01",
    )
    api = rec(
        "api:A1",
        "Kestrel Data",
        domain="kestrel.de",
        employee_count=120,
        street="9 New Rd",
        city="Hamburg",
        source_updated_at="2026-06-01",
    )
    directory = rec(
        "directory:D1",
        "KESTREL DATA",
        domain="kestrel-data.com",
        phone_norm="49301234567",
        source_updated_at="2026-08-01",
    )
    g = survive([directory, api, registry])
    assert g.values["company_name"] == "Kestrel Data GmbH"  # registry first for names
    assert g.values["domain"] == "kestrel.de"  # api first for websites
    assert g.values["phone_norm"] == "49301234567"  # only directory has one
    assert g.values["employee_count"] == 120
    assert g.provenance["company_name"] == "registry:R1"
    assert g.sources == ["api", "directory", "registry"]


def test_recency_breaks_ties_within_a_source():
    old = rec("api:A1", "Kestrel", employee_count=50, source_updated_at="2025-01-01")
    new = rec("api:A2", "Kestrel", employee_count=80, source_updated_at="2026-01-01")
    undated = rec("api:A0", "Kestrel", employee_count=10)
    assert survive([old, undated, new]).values["employee_count"] == 80


def test_nulls_never_survive_over_values():
    a = rec("registry:R1", "Kestrel GmbH", status=None)
    b = rec("registry:R2", "Kestrel GmbH", status="active")
    assert survive([a, b]).values["status"] == "active"


def test_address_fields_survive_together():
    # registry has a street but no city; the api has both -> take both from the api
    reg = rec("registry:R1", "Kestrel", street="1 Main St", city=None)
    api = rec("api:A1", "Kestrel", street="9 New Rd", city="Hamburg")
    g = survive([reg, api])
    assert (g.values["street"], g.values["city"]) == ("9 New Rd", "Hamburg")
    assert g.provenance["street"] == g.provenance["city"] == "api:A1"


def test_entity_id_is_deterministic_and_order_independent():
    assert entity_id_for(["b", "a"]) == entity_id_for(["a", "b"]) == entity_id_for(["a"])
    assert entity_id_for(["a"]).startswith("cmp_")


def test_empty_cluster_is_rejected():
    with pytest.raises(ValueError):
        survive([])
