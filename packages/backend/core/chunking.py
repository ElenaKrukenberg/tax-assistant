import re
from dataclasses import dataclass, field

# Semantic chunking for the KB markdown files.
#
# Strategy: split by markdown headings (the files were converted so that
# legal units — §§, Anhang sections, R/H blocks — became headings or clear
# paragraph boundaries), then pack paragraphs into chunks of a target size
# without breaking a paragraph in the middle. Each chunk carries document
# frontmatter metadata plus its own `section` (heading path) and `line`
# (Zeile numbers mentioned in the text).

TARGET_CHARS = 1200   # aim for chunks around this size
MAX_CHARS = 2200      # hard cap: force a split above this
MIN_CHARS = 200       # merge tiny tail chunks into the previous one

# Prefix for the per-topic boolean metadata keys. Shared with retrieval, which builds
# its topic filter from it — keep the two in step.
TOPIC_FLAG_PREFIX = "topic_"


@dataclass
class Chunk:
    chunk_id: str
    text: str
    metadata: dict = field(default_factory=dict)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse the simple flat YAML frontmatter used across the KB."""
    if not text.startswith("---"):
        return {}, text
    try:
        _, head, body = text.split("---", 2)
    except ValueError:
        return {}, text
    meta = {}
    for line in head.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip('"')
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, body


LINE_RE = re.compile(r"Zeilen?\s+(\d+)(?:\s*(?:bis|und|[–\-])\s*(\d+))?", re.I)


def extract_lines(text: str) -> str:
    """Collect Anlage-N line numbers mentioned in a chunk ('Zeile 31' -> '31')."""
    lines: set[int] = set()
    for m in LINE_RE.finditer(text):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if end >= start and end - start <= 30:  # ignore absurd ranges
            lines.update(range(start, end + 1))
    return ",".join(str(n) for n in sorted(lines)) if lines else ""


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown body into (heading_path, section_text) pairs."""
    sections: list[tuple[str, str]] = []
    heading_stack: dict[int, str] = {}
    current: list[str] = []

    def flush():
        text = "\n".join(current).strip()
        if text:
            path = " > ".join(v for _, v in sorted(heading_stack.items()))
            sections.append((path, text))
        current.clear()

    for line in body.splitlines():
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            heading_stack[level] = m.group(2).strip()
            # drop deeper levels from the previous branch
            for deeper in [k for k in heading_stack if k > level]:
                del heading_stack[deeper]
        else:
            current.append(line)
    flush()
    return sections


SENTENCE_RE = re.compile(r"(?<=[.;:])\s+(?=[A-ZÄÖÜ(§\d])")


def _split_long(paragraph: str) -> list[str]:
    """Split an oversized paragraph on sentence boundaries into TARGET-sized parts.

    PDF-extracted text often lacks blank lines, so a whole section can arrive
    as one huge 'paragraph'; without this, chunks blow past MAX_CHARS.
    """
    if len(paragraph) <= MAX_CHARS:
        return [paragraph]
    sentences = SENTENCE_RE.split(paragraph)
    parts, buf, size = [], [], 0
    for s in sentences:
        if size + len(s) > TARGET_CHARS and buf:
            parts.append(" ".join(buf))
            buf, size = [], 0
        buf.append(s)
        size += len(s)
    if buf:
        parts.append(" ".join(buf))
    return parts


def _pack_paragraphs(text: str) -> list[str]:
    """Pack paragraphs into chunks of roughly TARGET_CHARS, never splitting one."""
    raw = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    paragraphs = [piece for p in raw for piece in _split_long(p)]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for p in paragraphs:
        # an oversized single paragraph becomes its own chunk (rare: tables)
        if size + len(p) > MAX_CHARS and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(p)
        size += len(p)
        if size >= TARGET_CHARS:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
    if buf:
        tail = "\n\n".join(buf)
        if chunks and len(tail) < MIN_CHARS:
            chunks[-1] = chunks[-1] + "\n\n" + tail
        else:
            chunks.append(tail)
    return chunks


def chunk_document(text: str, fallback_source_id: str = "") -> list[Chunk]:
    """Chunk one KB markdown file into Chroma-ready chunks with metadata."""
    meta, body = parse_frontmatter(text)
    source_id = meta.get("source_id") or fallback_source_id
    topics = meta.get("topics") or []
    if isinstance(topics, str):
        topics = [topics]

    base_meta = {
        "source_id": source_id,
        "title": meta.get("title", source_id),
        "form_id": meta.get("form_id", "anlage_n"),
        "tax_year": int(meta.get("tax_year", 2025)),
        "source_type": meta.get("source_type", "official"),
        # CSV for display and debugging; the flags below are what queries filter on.
        "topics": ",".join(topics),
    }
    # Chroma metadata values must be scalar, so a list of topics cannot be stored and
    # filtered as a list. One boolean key per topic makes every topic of the document
    # queryable, combined with $or at query time. Storing only topics[0] instead —
    # which is what this did — left a document unreachable by every topic but its
    # first: § 9 Werbungskosten covers berufsverbaende but leads with
    # entfernungspauschale, so `topic=berufsverbaende` matched nothing at all and
    # union-dues questions fell through to an unfiltered search.
    for topic in topics:
        base_meta[TOPIC_FLAG_PREFIX + topic] = True

    chunks: list[Chunk] = []
    for section_path, section_text in _split_sections(body):
        for piece in _pack_paragraphs(section_text):
            md = dict(base_meta)
            md["section"] = section_path
            lines = extract_lines(piece)
            if lines:
                md["line"] = lines
            chunks.append(Chunk(chunk_id=f"{source_id}::{len(chunks):03d}", text=piece, metadata=md))
    return chunks
