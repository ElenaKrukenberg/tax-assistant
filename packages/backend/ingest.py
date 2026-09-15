"""Ingestion command: chunk the KB markdown, embed it, and load it into Postgres.

Run by hand, from a laptop, against one database at a time. It is deliberately not
part of any deploy: a backend deploy used to run this and rebuild all 775 embeddings
every time, so deploys were slow, nothing survived between them, and a failure while
indexing took a healthy backend down with it (issue #32).

Usage (from packages/backend, venv active):
    python ingest.py                        # load ../../KB into DATABASE_URL
    python ingest.py --kb-path PATH         # a KB somewhere else
    python ingest.py --dry-run              # chunk only, print stats, no API calls
    python ingest.py --release-id 2026-09-13  # label this load

The whole corpus is replaced inside one transaction, so an interrupted run leaves the
previous one intact and serving.
"""

import argparse
import pathlib
import sys

from core.chunking import TOPIC_FLAG_PREFIX, chunk_document
from core.vectorstore import get_embeddings_client
from db import kb_store

DEFAULT_KB = pathlib.Path(__file__).resolve().parents[2] / "KB"


def load_chunks(kb_path: pathlib.Path):
    files = sorted(kb_path.glob("*.md"))
    if not files:
        sys.exit(f"No .md files found in {kb_path}")
    all_chunks = []
    for f in files:
        chunks = chunk_document(f.read_text(encoding="utf-8"), fallback_source_id=f.stem)
        all_chunks.extend(chunks)
        print(f"  {f.name}: {len(chunks)} chunks")
    return files, all_chunks


def main():
    parser = argparse.ArgumentParser(description="Load the KB into Postgres")
    parser.add_argument("--kb-path", type=pathlib.Path, default=DEFAULT_KB)
    parser.add_argument("--release-id", default="", help="a label for this load")
    parser.add_argument("--dry-run", action="store_true", help="chunk only, no embedding/DB")
    # Accepted and ignored: `render.yaml` passed it for as long as ingestion ran at
    # build time, and a deploy that has not been updated yet should fail on the
    # database being unreachable rather than on an unknown flag.
    parser.add_argument("--reset", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    print(f"KB: {args.kb_path}")
    files, chunks = load_chunks(args.kb_path)
    sizes = [len(c.text) for c in chunks]
    print(f"\n{len(files)} files -> {len(chunks)} chunks "
          f"(chars min/avg/max: {min(sizes)}/{sum(sizes)//len(sizes)}/{max(sizes)})")

    if args.dry_run:
        return

    # Before the money, not after it: an unmigrated database is the ordinary mistake
    # here, and paying for 775 embeddings to discover it is the wrong order.
    if not kb_store.ready():
        sys.exit("kb.chunks does not exist in the database this points at. Apply the "
                 "schema first:\n"
                 "    python -m db.migrate --db-url '<the same connection string>'")

    print("\nEmbedding via OpenRouter...")
    embedder = get_embeddings_client()
    vectors = embedder.embed([c.text for c in chunks])
    print(f"  {len(vectors)} vectors, dim={len(vectors[0])}")

    rows = [_row(chunk, vector) for chunk, vector in zip(chunks, vectors)]
    stored = kb_store.replace_all(rows, release_id=args.release_id)
    print(f"\nkb.chunks: {stored} chunks stored"
          + (f" (release {args.release_id})" if args.release_id else ""))


def _row(chunk, vector) -> dict:
    """One chunk in the shape `kb.chunks` holds.

    The topic flags the chunker writes - `topic_pauschbetrag: true` - collapse back
    into the list they came from. One boolean column per topic is a schema that
    changes whenever a document does; the filter is the same either way.
    """
    md = chunk.metadata
    topics = [key[len(TOPIC_FLAG_PREFIX):] for key, value in md.items()
              if key.startswith(TOPIC_FLAG_PREFIX) and value]
    return {
        "chunk_id": chunk.chunk_id,
        "source_id": md.get("source_id", ""),
        "title": md.get("title", ""),
        "section": md.get("section", ""),
        "text": chunk.text,
        "embedding": vector,
        "tax_year": md.get("tax_year"),
        "form_id": md.get("form_id"),
        "source_type": md.get("source_type"),
        "line": md.get("line", ""),
        "topics": sorted(topics),
    }


if __name__ == "__main__":
    main()
