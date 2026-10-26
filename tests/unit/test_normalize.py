from __future__ import annotations

import duckdb
import pytest

from cdp.dbt_plugin import register_udfs
from cdp.normalize import (
    clean_name,
    company_domain,
    extract_domain,
    legal_form,
    name_key,
    normalize_name,
    normalize_phone,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Nørdvik Data G.m.b.H.", "nordvik data"),
        ("NØRDVIK DATA GmbH", "nordvik data"),
        ("Lumière Analytics S.A.S.", "lumiere analytics"),
        ("Ébène Foods, S.L.", "ebene foods"),
        ("Fjällgren Solar Aktiebolag", "fjallgren solar"),
        ("Selam Ridge Logistics Share Company", "selam ridge logistics"),
        ("Kilima & Sons Data Ltd.", "kilima and sons data"),
        ("Kilima and Sons Data Limited", "kilima and sons data"),
        ("Acme Holdings Pty Ltd", "acme holdings"),
        ("Westbrook Freight Co Ltd", "westbrook freight"),
        ("  Harborview   Labs  ", "harborview labs"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_suffix_only_stripped_at_end_and_never_to_empty():
    assert normalize_name("Ltd Ventures Ltd") == "ltd ventures"
    assert normalize_name("Limited") == "limited"
    assert normalize_name("AG") == "ag"


def test_null_and_blank_names():
    assert normalize_name(None) is None
    assert normalize_name("  ...  ") is None
    assert name_key(None) is None


def test_clean_name_and_legal_form():
    assert clean_name("Tana Lake Labs G.m.b.H.") == "tana lake labs gmbh"
    assert legal_form("Tana Lake Labs G.m.b.H.") == "gmbh"
    assert legal_form("Tana Lake Labs") is None


def test_name_key_collapses_spacing_variants():
    assert name_key("Cobalt Ridge Data Inc.") == name_key("CobaltRidge Data") == "cobaltridgedata"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.example.co.uk/about-us?x=1", "example.co.uk"),
        ("HTTPS://WWW.EXAMPLE.DE", "example.de"),
        ("example.com", "example.com"),
        ("http://example.com:8080/", "example.com"),
        ("info@Example.fr", "example.fr"),
        ("not a domain", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_domain(raw, expected):
    assert extract_domain(raw) == expected


def test_free_mail_is_not_a_company_domain():
    assert extract_domain("someone@gmail.com") == "gmail.com"
    assert company_domain("someone@gmail.com") is None
    assert company_domain("hello@kestreldata.com") == "kestreldata.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+49 30 123 4567", "49301234567"),
        ("+49301234567", "49301234567"),
        ("0049 301-234567", "49301234567"),
        ("123", None),
        (None, None),
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


def test_udfs_match_python_implementation():
    con = duckdb.connect()
    register_udfs(con)
    row = con.execute(
        "select cdp_normalize_name('Nørdvik Data G.m.b.H.'), cdp_company_domain('x@gmail.com'),"
        " cdp_normalize_phone(NULL), cdp_name_key('Cobalt Ridge Inc')"
    ).fetchone()
    assert row == ("nordvik data", None, None, "cobaltridge")
