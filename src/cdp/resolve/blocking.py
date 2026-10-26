"""Blocking: cheap keys that bring likely duplicates together so we never score all n^2 pairs.

Keys (a record can emit several; a pair is a candidate if it shares *any* key):

* ``domain:<registrable host>``   - strongest signal; free-mail domains are already removed
* ``name:<first 4 chars of name_key>|<country>`` - catches typos after the 4th character
  and spacing variants, scoped by country to keep blocks small
* ``tok:<sorted first-two-token signature>|<country>`` - catches typos in the first 4 chars
* ``phone:<digits>``

Oversized blocks (e.g. a hosting provider's domain) are skipped and reported rather than
silently exploding the pair count.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations

from cdp.resolve.records import Record

DEFAULT_MAX_BLOCK_SIZE = 40


def blocking_keys(r: Record) -> set[str]:
    keys: set[str] = set()
    country = r.country_code or "??"
    if r.domain:
        keys.add(f"domain:{r.domain}")
    if r.name_key:
        keys.add(f"name:{r.name_key[:4]}|{country}")
    tokens = r.name_norm.split() if r.name_norm else []
    if len(tokens) >= 2:
        keys.add(f"tok:{tokens[-1][:4]}|{tokens[0][-3:]}|{country}")
    if r.phone_norm:
        keys.add(f"phone:{r.phone_norm}")
    return keys


@dataclass
class BlockingResult:
    pairs: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    block_sizes: dict[str, int] = field(default_factory=dict)
    skipped_blocks: dict[str, int] = field(default_factory=dict)

    @property
    def n_pairs(self) -> int:
        return len(self.pairs)


def candidate_pairs(
    records: Iterable[Record], max_block_size: int = DEFAULT_MAX_BLOCK_SIZE
) -> BlockingResult:
    blocks: dict[str, list[str]] = defaultdict(list)
    for r in records:
        for key in blocking_keys(r):
            blocks[key].append(r.record_id)

    result = BlockingResult()
    for key, members in blocks.items():
        if len(members) < 2:
            continue
        if len(members) > max_block_size:
            result.skipped_blocks[key] = len(members)
            continue
        result.block_sizes[key] = len(members)
        for a, b in combinations(sorted(members), 2):
            result.pairs.setdefault((a, b), set()).add(key.split(":", 1)[0])
    return result
