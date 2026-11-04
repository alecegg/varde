"""FTS search ranking and snippet rendering for stored output."""

from __future__ import annotations

import re
import time
from collections import defaultdict

from .store import Store

CANDIDATES = 50
SNIPPET_LINES = 6
SNIPPET_BYTES = 600


def terms_of(query: str) -> list[str]:
    terms = []
    for raw in query.split():
        term = re.sub(r"^[^\w.-]+|[^\w.-]+$", "", raw, flags=re.UNICODE)
        if term:
            terms.append(term.lower())
    return terms


def _fts_query(terms: list[str], min_len: int, conjunction: bool) -> str | None:
    terms = [term for term in terms if len(term) >= min_len]
    return (" " if conjunction else " OR ").join(
        f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms
    ) or None


def _rank(
    store: Store,
    table: str,
    query: str,
    handle: str | None,
    source: str | None,
    content_type: str | None,
    include_superseded: bool,
) -> list[int]:
    sql = (
        f"SELECT f.rowid FROM {table} f JOIN chunks ch ON ch.id=f.rowid "  # noqa: S608 - table is selected from the two internal FTS table names.
        f"JOIN captures c ON c.id=ch.capture_id WHERE {table} MATCH ?"
    )
    args: list[object] = [query]
    for clause, value in (
        ("c.handle=?", handle),
        ("(lower(c.label) LIKE ? OR lower(c.source) LIKE ?)", source),
        ("ch.content_type=?", content_type),
    ):
        if value is not None:
            sql += " AND " + clause
            args.extend(
                [f"%{value.lower()}%", f"%{value.lower()}%"]
                if clause.startswith("(")
                else [value]
            )
    if not include_superseded and handle is None:
        sql += " AND c.superseded_by IS NULL"
    sql += f" ORDER BY bm25({table}) LIMIT {CANDIDATES}"
    return [int(row[0]) for row in store.conn.execute(sql, args)]


def search(
    store: Store,
    queries: list[str],
    *,
    limit: int = 3,
    handle: str | None = None,
    source: str | None = None,
    content_type: str | None = None,
    include_superseded: bool = False,
) -> list[dict]:
    results = []
    for query in queries:
        terms = terms_of(query)
        combined = _candidates(
            store, terms, handle, source, content_type, include_superseded
        )
        corrected = None
        if not combined:
            fixed = _correct_terms(store, terms)
            if fixed:
                combined = _candidates(
                    store, fixed, handle, source, content_type, include_superseded
                )
                if combined:
                    corrected = " ".join(fixed)
                    terms = fixed
        hits = []
        now = int(time.time())
        for rowid, iter_rrf in combined.items():
            row = store.conn.execute(
                """SELECT c.handle,c.label,ch.ordinal,ch.stream,ch.title,
                ch.line_start,ch.line_end,ch.content_type,c.created_at,ch.body
                FROM chunks ch JOIN captures c ON c.id=ch.capture_id WHERE ch.id=?""",
                (rowid,),
            ).fetchone()
            if row is None:
                continue
            body = row[9]
            matches = _term_positions(body, terms)
            score = iter_rrf
            if len(terms) > 1 and _all_within(matches, 200):
                score *= 1.5
            age = max(0, now - int(row[8]))
            score *= max(0.7, 1 / (1 + age / 86400))
            hits.append(
                {
                    "handle": row[0],
                    "label": row[1],
                    "chunk": row[2],
                    "stream": row[3],
                    "title": row[4],
                    "line_start": row[5],
                    "line_end": row[6],
                    "content_type": row[7],
                    "score": score,
                    "age_secs": age,
                    "snippet": _snippet(body, [pos for pos, _ in matches]),
                }
            )
        hits.sort(key=lambda hit: -hit["score"])
        results.append(
            {"query": query, "corrected": corrected, "hits": hits[: max(limit, 1)]}
        )
    return results


def _candidates(store, terms, handle, source, content_type, include_superseded):
    for conjunction in (True, False):
        porter_q = _fts_query(terms, 1, conjunction)
        trigram_q = _fts_query(terms, 3, conjunction)
        porter = (
            _rank(
                store,
                "chunks_porter",
                porter_q,
                handle,
                source,
                content_type,
                include_superseded,
            )
            if porter_q
            else []
        )
        trigram = (
            _rank(
                store,
                "chunks_trigram",
                trigram_q,
                handle,
                source,
                content_type,
                include_superseded,
            )
            if trigram_q
            else []
        )
        if porter or trigram:
            combined: dict[int, float] = defaultdict(float)
            for rows in (porter, trigram):
                for rank, rowid in enumerate(rows, 1):
                    combined[rowid] += 1 / (60 + rank)
            return combined
        if len(terms) == 1:
            break
    return {}


def _correct_terms(store, terms):
    fixed = []
    changed = False
    for term in terms:
        if len(term) < 4:
            fixed.append(term)
            continue
        grams = [term[i : i + 3] for i in range(len(term) - 2)]
        query = _fts_query(grams, 3, False)
        rows = (
            store.conn.execute(
                "SELECT body FROM chunks_trigram WHERE chunks_trigram MATCH ? "
                "ORDER BY bm25(chunks_trigram) LIMIT 10",
                (query,),
            ).fetchall()
            if query
            else []
        )
        words = (
            word.lower()
            for row in rows
            for word in re.split(r"[^\w]+", row[0], flags=re.UNICODE)
        )
        candidates = [
            word for word in words if word and abs(len(word) - len(term)) <= 2
        ]
        cutoff = 2 if len(term) >= 8 else 1
        correction = min(
            candidates, key=lambda word: _edit_distance(term, word), default=None
        )
        if correction and 0 < _edit_distance(term, correction) <= cutoff:
            fixed.append(correction)
            changed = True
        else:
            fixed.append(term)
    return fixed if changed else None


def _edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, 1):
        current = [i]
        for j, other in enumerate(right, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (char != other))
            )
        previous = current
    return previous[-1]


def _term_positions(body, terms):
    positions = []
    for index, term in enumerate(terms):
        positions.extend(
            (len(body[: match.start()].encode()), index)
            for match in re.finditer(re.escape(term), body, re.IGNORECASE)
        )
    return sorted(positions)


def _all_within(positions, width):
    if not positions:
        return False
    n_terms = max(term for _, term in positions) + 1
    counts = [0] * n_terms
    distinct = lo = 0
    for _hi, (position, term) in enumerate(positions):
        if not counts[term]:
            distinct += 1
        counts[term] += 1
        while position - positions[lo][0] > width:
            old = positions[lo][1]
            counts[old] -= 1
            if not counts[old]:
                distinct -= 1
            lo += 1
        if distinct == n_terms:
            return True
    return False


def _snippet(body: str, positions: list[int]) -> str:
    lines = body.splitlines()
    max_bytes = SNIPPET_BYTES
    if len(lines) <= SNIPPET_LINES and len(body.encode()) <= max_bytes:
        return body
    starts, offset = [], 0
    for line in lines:
        starts.append(offset)
        offset += len(line.encode()) + 1
    hit_lines = []
    for pos in positions:
        line = (
            next(
                (i for i, line_start in enumerate(starts) if line_start > pos),
                len(starts),
            )
            - 1
        )
        if not hit_lines or hit_lines[-1] != line:
            hit_lines.append(line)
    start = max(0, (_densest_line(hit_lines) if hit_lines else 0) - 1)
    end = min(len(lines), start + SNIPPET_LINES)
    out = ["…"] if start else []
    used = 0
    for line in lines[start:end]:
        clipped = _clip(line, max_bytes // 2)
        if used + len(clipped.encode()) > max_bytes:
            break
        out.append(clipped)
        used += len(clipped.encode()) + 1
    if end < len(lines):
        out.append("…")
    return "\n".join(out)


def _densest_line(hit_lines):
    best_count, best_line = 0, hit_lines[0]
    lo = 0
    for hi, line in enumerate(hit_lines):
        while line - hit_lines[lo] >= SNIPPET_LINES:
            lo += 1
        if hi - lo + 1 > best_count:
            best_count, best_line = hi - lo + 1, hit_lines[lo]
    return best_line


def _clip(line, limit):
    encoded = line.encode()
    if len(encoded) <= limit:
        return line
    return encoded[:limit].decode("utf-8", errors="ignore") + "…"
