"""The record shape the resolver works on (a row of ``intermediate.int_company_records``)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime

import duckdb


@dataclass(frozen=True, slots=True)
class Record:
    record_id: str
    source: str
    source_record_id: str
    company_name: str
    name_norm: str
    name_key: str
    domain: str | None = None
    phone_norm: str | None = None
    street: str | None = None
    city: str | None = None
    city_norm: str | None = None
    country_code: str | None = None
    registration_number: str | None = None
    employee_count: int | None = None
    industry: str | None = None
    status: str | None = None
    incorporation_date: date | None = None
    source_updated_at: datetime | None = None


RECORD_COLUMNS = [f.name for f in fields(Record)]


def load_records(con: duckdb.DuckDBPyConnection) -> list[Record]:
    cols = ", ".join(RECORD_COLUMNS)
    rows = con.execute(
        f"select {cols} from intermediate.int_company_records order by record_id"
    ).fetchall()
    return [Record(*row) for row in rows]
