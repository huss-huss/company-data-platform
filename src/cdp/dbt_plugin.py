"""dbt-duckdb plugin: exposes ``cdp.normalize`` functions as DuckDB scalar UDFs.

Configured in ``dbt/profiles.yml`` under ``plugins: [{module: cdp.dbt_plugin}]``.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from dbt.adapters.duckdb.plugins import BasePlugin
from duckdb import DuckDBPyConnection
from duckdb.sqltypes import VARCHAR

from cdp import normalize

UDFS: dict[str, Callable[[str | None], str | None]] = {
    "cdp_clean_name": normalize.clean_name,
    "cdp_normalize_name": normalize.normalize_name,
    "cdp_legal_form": normalize.legal_form,
    "cdp_name_key": normalize.name_key,
    "cdp_extract_domain": normalize.extract_domain,
    "cdp_company_domain": normalize.company_domain,
    "cdp_normalize_phone": normalize.normalize_phone,
}


def register_udfs(conn: DuckDBPyConnection) -> None:
    for name, fn in UDFS.items():
        with contextlib.suppress(Exception):  # not registered yet on this connection
            conn.remove_function(name)
        conn.create_function(
            name, fn, [VARCHAR], VARCHAR, null_handling="special", side_effects=False
        )


class Plugin(BasePlugin):
    def configure_connection(self, conn: DuckDBPyConnection) -> None:
        register_udfs(conn)
