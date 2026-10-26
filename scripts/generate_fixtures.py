"""Generate the synthetic, fully fictional fixture datasets used offline.

Three providers describe overlapping sets of fictional companies:

* ``registry``  - a company-registry style CSV export (legal names, registration numbers)
* ``api``       - a paginated JSON API (websites, headcount, industry)
* ``directory`` - a scraped business directory in JSONL (phones, emails, free-text address)

The generator is deterministic (seeded) so the committed fixtures and the ground truth are
reproducible. Noise injected on purpose:

* legal-suffix variants (``GmbH`` / ``G.m.b.H.``, ``Ltd`` / ``Limited``), casing, accents
* typos (adjacent swaps, dropped letters), ``&`` vs ``and``, collapsed spaces
* different country spellings per provider (``DE`` / ``Germany`` / ``Deutschland``)
* conflicting fields (headcount, address after a move, regional vs global domain)
* free-mail contact emails (must not be used as a blocking key)
* duplicate listings inside the directory itself
* hard negatives: distinct companies with the same or nearly the same name

Usage: ``python scripts/generate_fixtures.py [--out fixtures]``
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

SEED = 20261026

STEMS = [
    "Aldermoor",
    "Brightwater",
    "Cobalt Ridge",
    "Driftwood",
    "Emberline",
    "Fernhollow",
    "Granite Peak",
    "Harborview",
    "Ironbark",
    "Juniper",
    "Kestrel",
    "Larkspur",
    "Meridian Vale",
    "Northwind",
    "Oakhaven",
    "Pinecrest",
    "Quillfeather",
    "Redfern",
    "Silverbirch",
    "Tidewater",
    "Umberfield",
    "Valewood",
    "Westbrook",
    "Yarrow",
    "Zephyrine",
    "Ashgrove",
    "Bluestone",
    "Cedarline",
    "Duskfall",
    "Evergleam",
    "Foxglove",
    "Goldcrest",
    "Hollowmere",
    "Islay Point",
    "Jadecliff",
    "Kingsmoor",
    "Lumière",
    "Mossbank",
    "Nørdvik",
    "Orchid Bay",
    "Pebblebrook",
    "Quarrystone",
    "Rosemoor",
    "Stonebridge",
    "Thornbury",
    "Upland",
    "Verdant Arc",
    "Willowmere",
    "Abenet",
    "Selam Ridge",
    "Tana Lake",
    "Simien",
    "Kilima",
    "Savanna Gate",
    "Ébène",
    "Brisa",
    "Solano",
    "Fjällgren",
    "Lindqvist",
    "Maplecrest",
]

INDUSTRIES = [
    ("Logistics", "logistics"),
    ("Analytics", "software"),
    ("Foods", "food & beverage"),
    ("Robotics", "manufacturing"),
    ("Health", "healthcare"),
    ("Energy", "energy"),
    ("Capital", "financial services"),
    ("Textiles", "manufacturing"),
    ("Labs", "biotech"),
    ("Software", "software"),
    ("Coffee Traders", "food & beverage"),
    ("Freight", "logistics"),
    ("Solar", "energy"),
    ("Pharma", "healthcare"),
    ("Data", "software"),
    ("Builders", "construction"),
]

COUNTRIES = {
    # iso2: (registry spellings, directory spellings, legal suffix variants, tld, phone prefix,
    #        cities)
    "DE": (
        ["Germany", "GERMANY", "Deutschland"],
        ["Germany", "DE", "Deutschland"],
        [["GmbH", "G.m.b.H.", "gmbh"], ["AG", "Aktiengesellschaft"]],
        "de",
        "+49",
        ["Berlin", "Hamburg", "München", "Köln"],
    ),
    "GB": (
        ["United Kingdom", "UNITED KINGDOM", "Great Britain"],
        ["UK", "U.K.", "United Kingdom"],
        [["Ltd", "Limited", "Ltd."], ["PLC", "plc"]],
        "co.uk",
        "+44",
        ["London", "Manchester", "Leeds", "Bristol"],
    ),
    "US": (
        ["United States", "United States of America", "USA"],
        ["USA", "US", "United States"],
        [["Inc.", "Inc", "Incorporated"], ["LLC", "L.L.C."], ["Corporation", "Corp."]],
        "com",
        "+1",
        ["Austin", "Denver", "Boston", "Seattle"],
    ),
    "FR": (
        ["France", "FRANCE", "République française"],
        ["France", "FR"],
        [["SAS", "S.A.S."], ["SARL", "S.A.R.L."]],
        "fr",
        "+33",
        ["Paris", "Lyon", "Toulouse", "Nantes"],
    ),
    "NL": (
        ["Netherlands", "The Netherlands", "Nederland"],
        ["Netherlands", "NL", "Holland"],
        [["B.V.", "BV"]],
        "nl",
        "+31",
        ["Amsterdam", "Rotterdam", "Utrecht"],
    ),
    "ET": (
        ["Ethiopia", "ETHIOPIA", "Federal Democratic Republic of Ethiopia"],
        ["Ethiopia", "ET"],
        [["PLC", "P.L.C."], ["Share Company", "S.C."]],
        "et",
        "+251",
        ["Addis Ababa", "Bahir Dar", "Hawassa"],
    ),
    "KE": (
        ["Kenya", "KENYA", "Republic of Kenya"],
        ["Kenya", "KE"],
        [["Ltd", "Limited"]],
        "co.ke",
        "+254",
        ["Nairobi", "Mombasa", "Kisumu"],
    ),
    "ES": (
        ["Spain", "SPAIN", "España"],
        ["Spain", "ES", "España"],
        [["S.L.", "SL"], ["S.A.", "SA"]],
        "es",
        "+34",
        ["Madrid", "Barcelona", "Valencia"],
    ),
    "SE": (
        ["Sweden", "SWEDEN", "Sverige"],
        ["Sweden", "SE", "Sverige"],
        [["AB", "Aktiebolag"]],
        "se",
        "+46",
        ["Stockholm", "Göteborg", "Malmö"],
    ),
    "CA": (
        ["Canada", "CANADA"],
        ["Canada", "CA"],
        [["Inc.", "Inc"], ["Ltd.", "Limited"]],
        "ca",
        "+1",
        ["Toronto", "Vancouver", "Ottawa"],
    ),
}

STREETS = [
    "Market Street",
    "Station Road",
    "Harbour Lane",
    "Mill Way",
    "Kingsway",
    "Bahnhofstraße",
    "Rue de la Paix",
    "Calle Mayor",
    "Storgatan",
    "Bole Road",
    "Moi Avenue",
    "Keizersgracht",
    "Queen Street",
    "Elm Avenue",
    "Riverside Drive",
]

FREE_MAIL = ["gmail.com", "outlook.com", "yahoo.com"]

N_ENTITIES = 220
FETCH_EPOCH = datetime(2026, 9, 1, tzinfo=UTC)


@dataclass
class Company:
    entity_id: str
    base_name: str
    country: str
    suffix_group: list[str]
    domain: str
    alt_domain: str | None
    industry: str
    city: str
    street: str
    phone: str
    employees: int
    incorporated: date
    status: str = "active"
    moved_to: tuple[str, str] | None = None  # (street, city) after a move
    tags: list[str] = field(default_factory=list)


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_text.lower())


def typo(rng: random.Random, text: str) -> str:
    letters = [i for i, c in enumerate(text) if c.isalpha()]
    if len(letters) < 6:
        return text
    i = rng.choice(letters[1:-2])
    if rng.random() < 0.5 and text[i + 1].isalpha():  # adjacent swap
        return text[:i] + text[i + 1] + text[i] + text[i + 2 :]
    return text[:i] + text[i + 1 :]  # drop a letter


def strip_accents(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def name_variant(rng: random.Random, c: Company, *, canonical: bool = False) -> str:
    suffix = c.suffix_group[0] if canonical else rng.choice(c.suffix_group)
    name = c.base_name
    if canonical:
        return f"{name} {suffix}"
    roll = rng.random()
    if roll < 0.18:
        name = typo(rng, name)
    elif roll < 0.28:
        name = name.upper()
    elif roll < 0.36:
        name = strip_accents(name)
    elif roll < 0.42:
        name = name.replace(" ", "", 1)
    if " & " in name and rng.random() < 0.5:
        name = name.replace(" & ", " and ")
    if rng.random() < 0.15:
        return name  # suffix omitted entirely
    return f"{name} {suffix}" if rng.random() < 0.9 else f"{name}, {suffix}"


def phone_variant(rng: random.Random, phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    fmt = rng.random()
    if fmt < 0.4:
        return phone
    if fmt < 0.7:
        return "+" + digits
    return f"00{digits[:3]} {digits[3:6]}-{digits[6:]}"


def random_phone(rng: random.Random, prefix: str) -> str:
    return f"{prefix} {rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}"


def make_companies(rng: random.Random) -> list[Company]:
    combos = [(s, ind) for s in STEMS for ind in INDUSTRIES]
    rng.shuffle(combos)
    companies: list[Company] = []
    used_names: set[str] = set()
    countries = list(COUNTRIES)

    def build(stem: str, ind: tuple[str, str], iso: str, idx: int, tag: str | None = None) -> None:
        _, _, suffixes, tld, prefix, cities = COUNTRIES[iso]
        base = f"{stem} {ind[0]}"
        if rng.random() < 0.06:
            base = f"{stem} & {rng.choice(['Sons', 'Partners', 'Co'])} {ind[0]}"
        slug = slugify(base)
        domain = f"{slug}.{tld}" if rng.random() < 0.6 else f"{slug}.com"
        alt = None
        if rng.random() < 0.15:  # regional vs global website conflict
            alt = f"{slug}-{iso.lower()}.com" if domain.endswith(".com") else f"{slug}.com"
        c = Company(
            entity_id=f"E{idx:04d}",
            base_name=base,
            country=iso,
            suffix_group=rng.choice(suffixes),
            domain=domain,
            alt_domain=alt,
            industry=ind[1],
            city=rng.choice(cities),
            street=f"{rng.randint(1, 240)} {rng.choice(STREETS)}",
            phone=random_phone(rng, prefix),
            employees=rng.choice([8, 15, 32, 60, 120, 250, 480, 900, 2400]),
            incorporated=date(1985, 1, 1) + timedelta(days=rng.randint(0, 13000)),
        )
        if rng.random() < 0.12:
            c.moved_to = (f"{rng.randint(1, 240)} {rng.choice(STREETS)}", rng.choice(cities))
        if rng.random() < 0.04:
            c.status = "dissolved"
        if tag:
            c.tags.append(tag)
        companies.append(c)
        used_names.add(base + iso)

    idx = 1
    for stem, ind in combos:
        if len(companies) >= N_ENTITIES - 24:
            break
        iso = rng.choice(countries)
        if f"{stem} {ind[0]}{iso}" in used_names:
            continue
        build(stem, ind, iso, idx)
        idx += 1

    # Hard negatives 1: same trading name, different country, different company.
    for c in rng.sample(companies, 12):
        other_iso = rng.choice([x for x in countries if x != c.country])
        stem, word = c.base_name.rsplit(" ", 1)
        ind = next(i for i in INDUSTRIES if i[0].endswith(word))
        build(stem.split(" & ")[0], ind, other_iso, idx, tag="hard_negative_country")
        idx += 1

    # Hard negatives 2: near-identical name in the same country ("Kestrel Data" vs
    # "Kestrel Data Labs") with its own domain and address.
    for c in rng.sample(companies[: N_ENTITIES - 24], 12):
        extra = rng.choice(["Labs", "Group", "Systems", "International"])
        base = f"{c.base_name} {extra}"
        _, _, _, tld, prefix, cities = COUNTRIES[c.country]
        twin = Company(
            entity_id=f"E{idx:04d}",
            base_name=base,
            country=c.country,
            suffix_group=c.suffix_group,
            domain=f"{slugify(base)}.{tld}",
            alt_domain=None,
            industry=c.industry,
            city=rng.choice(cities),
            street=f"{rng.randint(1, 240)} {rng.choice(STREETS)}",
            phone=random_phone(rng, prefix),
            employees=rng.choice([15, 60, 250]),
            incorporated=date(2005, 1, 1) + timedelta(days=rng.randint(0, 6000)),
            tags=["hard_negative_name"],
        )
        companies.append(twin)
        idx += 1
    return companies


def ts(rng: random.Random, start_days: int, span_days: int) -> datetime:
    return FETCH_EPOCH - timedelta(
        days=start_days + rng.randint(0, span_days), minutes=rng.randint(0, 1440)
    )


def generate(out: Path, seed: int = SEED) -> dict[str, int]:
    rng = random.Random(seed)
    companies = make_companies(rng)
    truth: list[tuple[str, str, str]] = []

    # ---------------------------------------------------------------- registry (CSV)
    registry_rows = []
    for c in companies:
        if rng.random() > 0.82:
            continue
        reg_spellings = COUNTRIES[c.country][0]
        street, city = c.moved_to if c.moved_to and rng.random() < 0.5 else (c.street, c.city)
        reg_no = f"{c.country}-{rng.randint(100000, 999999)}"
        registry_rows.append(
            {
                "registration_number": reg_no,
                "company_name": name_variant(rng, c, canonical=rng.random() < 0.7),
                "country": rng.choice(reg_spellings),
                "registered_address": street,
                "city": city,
                "status": c.status.upper() if rng.random() < 0.3 else c.status,
                "incorporation_date": c.incorporated.strftime(
                    rng.choice(["%Y-%m-%d", "%Y-%m-%d", "%d/%m/%Y"])
                ),
                "last_updated": ts(rng, 30, 400).date().isoformat(),
            }
        )
        truth.append(("registry", reg_no, c.entity_id))

    # ---------------------------------------------------------------- api (JSON)
    api_rows = []
    for n, c in enumerate(companies):
        if rng.random() > 0.72:
            continue
        domain = c.alt_domain if c.alt_domain and rng.random() < 0.6 else c.domain
        website = rng.choice(
            [
                f"https://www.{domain}",
                f"https://{domain}/",
                f"http://www.{domain}/about-us",
                f"{domain}",
                f"HTTPS://WWW.{domain.upper()}",
            ]
        )
        if rng.random() < 0.06:
            website = None
        city, street = (c.moved_to[1], c.moved_to[0]) if c.moved_to else (c.city, c.street)
        employees = c.employees
        if rng.random() < 0.35:
            employees = max(1, int(employees * rng.uniform(0.7, 1.4)))
        api_id = f"acc_{n:03d}{rng.randint(1000, 9999)}"
        api_rows.append(
            {
                "id": api_id,
                "name": name_variant(rng, c),
                "website": website,
                "hq": {"street": street, "city": city, "country_code": c.country},
                "employee_count": employees if rng.random() > 0.08 else None,
                "industry": c.industry,
                "updated_at": ts(rng, 1, 120).isoformat().replace("+00:00", "Z"),
            }
        )
        truth.append(("api", api_id, c.entity_id))

    # ---------------------------------------------------------------- directory (JSONL)
    directory_rows = []
    for n, c in enumerate(companies):
        if rng.random() > 0.66:
            continue
        copies = 2 if rng.random() < 0.1 else 1
        for k in range(copies):
            dir_spellings = COUNTRIES[c.country][1]
            email_domain = rng.choice(FREE_MAIL) if rng.random() < 0.12 else c.domain
            url = None if email_domain in FREE_MAIL or rng.random() < 0.3 else f"http://{c.domain}"
            city, street = (
                (c.moved_to[1], c.moved_to[0])
                if (c.moved_to and rng.random() < 0.5)
                else (c.city, c.street)
            )
            listing_id = f"dir-{n:03d}-{k}{rng.randint(10, 99)}"
            mailbox = (
                slugify(c.base_name)[:8]
                if email_domain in FREE_MAIL
                else rng.choice(["info", "contact", "hello", "sales"])
            )
            directory_rows.append(
                {
                    "listing_id": listing_id,
                    "business_name": name_variant(rng, c),
                    "contact": {
                        "url": url,
                        "email": f"{mailbox}@{email_domain}",
                        "phone": phone_variant(rng, c.phone) if rng.random() > 0.1 else None,
                    },
                    "address": f"{street}, {city}",
                    "country": rng.choice(dir_spellings),
                    "category": c.industry.title(),
                    "scraped_at": ts(rng, 0, 60).isoformat().replace("+00:00", "Z"),
                }
            )
            truth.append(("directory", listing_id, c.entity_id))

    rng.shuffle(registry_rows)
    rng.shuffle(api_rows)
    rng.shuffle(directory_rows)

    (out / "registry").mkdir(parents=True, exist_ok=True)
    (out / "api").mkdir(parents=True, exist_ok=True)
    (out / "directory").mkdir(parents=True, exist_ok=True)

    with (out / "registry" / "companies.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(registry_rows[0]))
        writer.writeheader()
        writer.writerows(registry_rows)
    (out / "api" / "companies.json").write_text(
        json.dumps(api_rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    with (out / "directory" / "export.jsonl").open("w", encoding="utf-8") as fh:
        for row in directory_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "ground_truth.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["source", "source_id", "entity_id"])
        writer.writerows(sorted(truth))

    stats = {
        "entities": len(companies),
        "registry": len(registry_rows),
        "api": len(api_rows),
        "directory": len(directory_rows),
        "hard_negatives": sum(1 for c in companies if c.tags),
    }
    (out / "README.md").write_text(
        "# Fixtures\n\nSynthetic, fully fictional company data generated by "
        "`scripts/generate_fixtures.py` (seed "
        f"{seed}). Any resemblance to real organisations is coincidental.\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in stats.items())
        + "\n",
        encoding="utf-8",
    )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out", type=Path, default=Path(__file__).resolve().parents[1] / "fixtures"
    )
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    print(generate(args.out, args.seed))


if __name__ == "__main__":
    main()
