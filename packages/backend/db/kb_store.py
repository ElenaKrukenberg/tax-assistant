"""Writing and reading the knowledge base in Postgres.

The whole point of issue #32: a backend deploy used to rebuild this - 47 files, 775
chunks, every embedding recomputed, on every deploy - and a failure while indexing took
down a backend that was otherwise healthy. Now the backend only reads, and a knowledge
base is released on its own schedule by running `ingest.py` by hand.

**One transaction for the whole reload.** Delete and insert together, so an interrupted
load leaves the previous corpus intact and serving. The alternative - write a new table
and switch - is what this becomes if a load ever grows long enough for the lock to
matter; at 775 rows it does not, and "nothing to roll back to" is the worst property a
reference load can have (#9).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from db.connection import as_owner


def ready() -> bool:
    """Whether there is a table to write into.

    Checked before the embedding call, not after it. Without this the script paid for
    775 embeddings and then discovered the migration had not been applied to the
    database it was pointed at - cheap here, and the wrong order for anything larger.
    """
    with as_owner() as cur:
        cur.execute("select to_regclass('kb.chunks') is not null")
        return bool(cur.fetchone()[0])


def replace_all(rows: Iterable[dict[str, Any]], release_id: str = "") -> int:
    """Rewrite the corpus. Returns how many chunks it now holds.

    `as_owner` and not `as_user`: this is not somebody's data and there is no user to
    run it as. It is run from a laptop by whoever is releasing a knowledge base.
    """
    rows = list(rows)
    if not rows:
        raise ValueError("refusing to replace the knowledge base with nothing")

    with as_owner() as cur:
        cur.execute("delete from kb.chunks")
        cur.executemany(
            """
            insert into kb.chunks
                (chunk_id, source_id, title, section, text, embedding,
                 tax_year, form_id, source_type, line, topics, release_id)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            [
                (
                    row["chunk_id"],
                    row["source_id"],
                    row.get("title") or "",
                    row.get("section") or "",
                    row["text"],
                    _vector(row["embedding"]),
                    row.get("tax_year"),
                    row.get("form_id"),
                    row.get("source_type"),
                    row.get("line") or "",
                    json.dumps(row.get("topics") or []),
                    release_id,
                )
                for row in rows
            ],
        )
        cur.execute("select count(*) from kb.chunks")
        return int(cur.fetchone()[0])


def count() -> int:
    """How many chunks are loaded. Zero is a valid answer, not an error."""
    with as_owner() as cur:
        cur.execute("select count(*) from kb.chunks")
        return int(cur.fetchone()[0])


def _vector(values: list[float]) -> str:
    """pgvector's text form. psycopg has no adapter for it without the extra package,
    and one format string is a smaller dependency than another library."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def metadata_of(row: dict) -> dict:
    """The metadata shape the retriever has always handed out.

    Rebuilt here rather than stored as one blob, so the columns stay queryable and the
    consumer keeps the dictionary it was written against - topic flags included, which
    is how `_build_where` has always spelled a topic filter.
    """
    md: dict[str, Any] = {
        "source_id": row["source_id"],
        "title": row["title"],
        "section": row["section"],
        "form_id": row["form_id"],
        "tax_year": row["tax_year"],
        "source_type": row["source_type"],
    }
    topics: list[str] = list(row["topics"] or [])
    if topics:
        md["topics"] = ",".join(topics)
        for topic in topics:
            md[f"topic_{topic}"] = True
    if row["line"]:
        md["line"] = row["line"]
    return md


class PostgresChunks:
    """The knowledge base as the retriever reads it: two queries and nothing else.

    An object rather than two module functions so the retriever can be handed a
    different one. The tests used to fake Chroma's whole client API to do that; what
    the retrieval strategies actually need is a nearest-neighbour query and a way to
    ask how common a term is, and a fake of two methods cannot drift from the real
    thing the way a fake of a vendor's interface can.
    """

    def nearest(self, vector: list[float], limit: int, *,
                where: Optional[tuple[str, list]] = None,
                contains: Optional[str] = None) -> list[dict]:
        """The closest chunks by cosine distance, filtered, nearest first.

        `<=>` is pgvector's cosine distance and returns the same number Chroma did, so
        the cutoffs in `services/retrieval.py` keep their measured meaning. No index on
        the vector column and none wanted: 775 rows are scanned exactly in
        milliseconds, and an approximate index would put a second source of variance
        inside a measurement this move has to hold steady (#9; thresholds in #64).
        """
        conditions: list[str] = []
        params: list = [_vector(vector)]
        if where is not None:
            fragment, where_params = where
            conditions.append(fragment)
            params.extend(where_params)
        if contains is not None:
            conditions.append("text ilike %s")
            params.append(f"%{contains}%")
        filters = (" where " + " and ".join(conditions)) if conditions else ""
        params.extend([_vector(vector), limit])

        with as_owner() as cur:
            cur.execute(
                "select chunk_id, source_id, title, section, text, tax_year, form_id, "
                "       source_type, line, topics, embedding <=> %s as distance "
                f"from kb.chunks{filters} "
                "order by embedding <=> %s limit %s",
                params,
            )
            columns = [column[0] for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def count_matches(self, needle: str, limit: int) -> int:
        """How many chunks contain a term, counted no further than `limit`.

        Stopping early is the whole point: the answer is only used to decide whether a
        term is too common to rank on, so counting past the cap buys nothing.
        """
        with as_owner() as cur:
            cur.execute(
                "select count(*) from (select 1 from kb.chunks "
                "where text ilike %s limit %s) hits",
                (f"%{needle}%", limit),
            )
            return int(cur.fetchone()[0])


    def by_line(self, line: int, form_id: Optional[str], limit: int) -> list[dict]:
        """Chunks that speak about one line of one form, nearest first by nothing.

        An exact lookup, not a similarity search: a question about Zeile 31 names the
        one thing that identifies the passage, and no embedding is as discriminating
        as the number itself. This is the tier Chroma could not have - its metadata
        filter has no membership test, so `line` was a CSV string matched in Python
        over whatever the vector search had already returned. A chunk that did not
        make that list could not be promoted, which is how a question whose answer was
        in the corpus went unanswered.

        The form is part of the match. Anlage N has a Zeile 31 and so does Anlage
        N-Doppelte Haushaltsführung; they are different lines on different sheets.
        """
        conditions = ["line ~ %s"]
        params: list = [rf"(^|,)\s*{int(line)}\s*(,|$)"]
        if form_id:
            conditions.append("form_id = %s")
            params.append(form_id)
        params.append(limit)
        with as_owner() as cur:
            cur.execute(
                "select chunk_id, source_id, title, section, text, tax_year, form_id, "
                "       source_type, line, topics, 0.0 as distance "
                f"from kb.chunks where {' and '.join(conditions)} limit %s",
                params,
            )
            columns = [column[0] for column in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
