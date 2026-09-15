from core.chunking import chunk_document, extract_lines, parse_frontmatter

SAMPLE = """---
title: "Test Doc"
source_type: official
form_id: anlage_n
tax_year: 2025
source_id: test-doc
topics: [entfernungspauschale, reisekosten]
---

# Heading One

First paragraph about commuting costs. Enter the distance in Zeile 31.

Second paragraph mentioning Zeilen 31 bis 33 for details.

## Subsection

""" + ("Long sentence about deductions. " * 200)


def test_parse_frontmatter():
    meta, body = parse_frontmatter(SAMPLE)
    assert meta["source_id"] == "test-doc"
    assert meta["topics"] == ["entfernungspauschale", "reisekosten"]
    assert "# Heading One" in body


def test_extract_lines():
    assert extract_lines("see Zeile 31") == "31"
    assert extract_lines("Zeilen 31 bis 33") == "31,32,33"
    assert extract_lines("no lines here") == ""


def test_chunk_metadata_and_ids():
    chunks = chunk_document(SAMPLE)
    assert chunks, "expected at least one chunk"
    first = chunks[0]
    assert first.chunk_id == "test-doc::000"
    assert first.metadata["topics"] == "entfernungspauschale,reisekosten"
    assert first.metadata["tax_year"] == 2025
    assert first.metadata["section"].startswith("Heading One")
    assert first.metadata["line"] == "31,32,33"


def test_every_topic_becomes_a_queryable_flag():
    """Regression: a document used to be reachable only by its first topic.

    Chroma metadata cannot hold a list, so `topics[0]` was the only filterable value
    and the rest of the list existed for display. § 9 Werbungskosten covers
    berufsverbaende but leads with entfernungspauschale, so `topic=berufsverbaende`
    matched nothing and union-dues questions never retrieved it.
    """
    for chunk in chunk_document(SAMPLE):
        assert chunk.metadata["topic_entfernungspauschale"] is True
        assert chunk.metadata["topic_reisekosten"] is True
        # the primary-topic-only field is gone: nothing may filter on it again
        assert "topic" not in chunk.metadata


def test_long_sections_get_split():
    chunks = chunk_document(SAMPLE)
    assert all(len(c.text) <= 3500 for c in chunks)
    assert len(chunks) >= 3  # the long subsection must split into several chunks
