import pytest
from pydantic import ValidationError

from api.schemas.tax import TaxQuestionRequest
from services.query_analysis import INTENTS, TOPICS, WIRE_SCHEMA, QueryPlan, analyze_query
from services.retrieval import (
    LEXICAL_MAX_MATCHES,
    LEXICAL_TIER_MAX,
    RetrievalResult,
    Retriever,
)
from services.tax_service import DEPTH_INSTRUCTIONS, TaxService
from tests.conftest import FakeLLMClient, FakeRetriever


# --- query analysis ---

@pytest.mark.asyncio
async def test_analyze_query_parses_json():
    llm = FakeLLMClient(replies=[
        '{"intent": "field_explanation", "search_query_de": "Anlage N Zeile 31",'
        ' "topics": ["form_fields"], "line": 31, "form_id": "anlage_n"}'
    ])
    a = await analyze_query(llm, "What goes in line 31?")
    assert a.intent == "field_explanation"
    assert a.search_query == "Anlage N Zeile 31"
    assert a.line == 31
    assert a.form_id == "anlage_n"


@pytest.mark.asyncio
async def test_analyze_query_asks_for_the_schema():
    """The vocabularies reach the model as enums, so it cannot invent a topic."""
    llm = FakeLLMClient(replies=[
        '{"intent": "knowledge", "search_query_de": "Entfernungspauschale", "topics": []}'
    ])
    await analyze_query(llm, "commute?")

    schema = llm.calls[0]["schema"]
    properties = schema["properties"]
    assert set(properties) == {
        "intent", "search_query_de", "topics", "line", "form_id", "user_language",
    }
    assert set(schema["required"]) == {"intent", "search_query_de"}
    assert properties["topics"]["items"]["enum"] == TOPICS
    assert properties["intent"]["enum"] == INTENTS


def test_the_wire_schema_carries_nothing_the_provider_does_not_read():
    """Every byte of the schema is billed on every question — see _wire_schema."""
    schema = WIRE_SCHEMA

    assert schema["title"]                      # LangChain names the function after it
    for name, field in schema["properties"].items():
        assert "title" not in field, name
        assert "default" not in field, name
        assert "anyOf" not in field, name       # nullable expressed as a type, not a union
        assert field.get("description"), name   # descriptions stay: they are instructions

    # and the nullable fields are still nullable
    assert schema["properties"]["line"]["type"] == ["integer", "null"]
    assert None in schema["properties"]["form_id"]["enum"]


def test_the_wire_schema_still_validates_into_the_model():
    """Trimming is mechanical: what the provider returns must still be a QueryPlan."""
    plan = QueryPlan.model_validate({
        "intent": "calculation",
        "search_query_de": "Entfernungspauschale",
        "topics": ["entfernungspauschale"],
        "line": None,
        "form_id": None,
        "user_language": "de",
    })
    assert plan.intent == "calculation"


@pytest.mark.asyncio
async def test_analyze_query_survives_garbage():
    llm = FakeLLMClient(replies=["not json at all"])
    a = await analyze_query(llm, "some question")
    assert a.intent == "knowledge"
    assert a.search_query == "some question"  # falls back to the original text


@pytest.mark.asyncio
async def test_analyze_query_salvages_a_reply_that_missed_the_schema():
    """One out-of-vocabulary topic must not cost the intent and the search query."""
    llm = FakeLLMClient(replies=[
        '{"intent": "calculation", "search_query_de": "Entfernungspauschale 74 km",'
        ' "topics": ["entfernungspauschale", "not_a_real_topic"], "line": "31",'
        ' "form_id": "made_up_form", "user_language": "xx"}'
    ])

    a = await analyze_query(llm, "74 km?")

    assert a.intent == "calculation"
    assert a.search_query == "Entfernungspauschale 74 km"
    assert a.topics == ["entfernungspauschale"]   # unknown value dropped, not fatal
    assert a.line == 31                           # coerced from the string
    assert a.form_id is None                      # unknown form ignored
    assert a.user_language == "en"                # unknown language falls back


@pytest.mark.asyncio
async def test_analyze_query_trims_extra_topics_instead_of_rejecting_them():
    llm = FakeLLMClient(replies=[
        '{"intent": "knowledge", "search_query_de": "Arbeitszimmer",'
        ' "topics": ["arbeitszimmer", "homeoffice_pauschale", "pauschbetrag"]}'
    ])

    a = await analyze_query(llm, "Arbeitszimmer?")

    assert a.topics == ["arbeitszimmer", "homeoffice_pauschale"]


@pytest.mark.asyncio
async def test_analysis_usage_is_reported_even_when_the_reply_is_unusable():
    """Cost accounting must not depend on the reply being parseable."""
    llm = FakeLLMClient(replies=["not json at all"])
    a = await analyze_query(llm, "some question")
    assert a.usage["total_tokens"] == 15


# --- retrieval post-filtering ---

def _topics(md: dict) -> list[str]:
    """The topics of a chunk, from either spelling the test rows use.

    The chunker writes both: a CSV string and one `topic_x: True` flag per topic. The
    Postgres row keeps a list, so the fake accepts whichever the case was written with
    rather than forcing every fixture to be rewritten.
    """
    from core.chunking import TOPIC_FLAG_PREFIX

    flagged = [key[len(TOPIC_FLAG_PREFIX):] for key, value in md.items()
               if key.startswith(TOPIC_FLAG_PREFIX) and value]
    listed = [t for t in str(md.get("topics") or "").split(",") if t]
    return sorted(set(flagged) | set(listed))


class FakeChunks:
    """The two queries the retrieval strategies actually make, over a list of rows.

    It used to be a fake of Chroma's client API - `query`, `get`, `where`,
    `where_document`, the nested result shape. That fake could drift from the real
    client without any test noticing, and when the knowledge base moved to Postgres it
    had to be thrown away entirely. What the strategies need is a nearest-neighbour
    query and a way to ask how common a term is, so that is the surface this fakes.

    Rows arrive in Chroma's old triple form - text, metadata, distance - because the
    test cases were written that way and their contents are the point, not their shape.
    """

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def nearest(self, vector, limit, *, where=None, contains=None):
        self.calls.append((where, contains))
        rows = [r for r in self.rows if self._matches(r[1], where)]
        if contains is not None:
            rows = [r for r in rows if contains.lower() in r[0].lower()]
        rows = sorted(rows, key=lambda r: r[2])[:limit]
        return [self._record(text, md, distance) for text, md, distance in rows]

    def by_line(self, line, form_id, limit):
        """The exact lookup: chunks naming this line of this form."""
        hits = []
        for text, md, _distance in self.rows:
            lines = {p.strip() for p in str(md.get("line") or "").split(",") if p.strip()}
            if str(line) not in lines:
                continue
            if form_id and md.get("form_id") != form_id:
                continue
            hits.append(self._record(text, md, 0.0))
        return hits[:limit]

    def count_matches(self, needle, limit):
        hits = [r for r in self.rows if needle.lower() in r[0].lower()]
        return min(len(hits), limit)

    @staticmethod
    def _matches(md, where):
        """The SQL fragment the retriever builds, applied to a dict.

        Only the two shapes `_build_where` can produce - a topic test and a form test -
        because a fake that accepted arbitrary SQL would be a database.
        """
        if where is None:
            return True
        fragment, params = where
        values = list(params)
        for condition in fragment.split(" and "):
            value = values.pop(0)
            if condition.startswith("topics"):
                if not any(topic in _topics(md) for topic in value):
                    return False
            elif condition.startswith("form_id"):
                if md.get("form_id") != value:
                    return False
        return True

    @staticmethod
    def _record(text, md, distance):
        """A row as `kb.chunks` hands it over."""
        topics = _topics(md)
        return {
            "chunk_id": md.get("source_id", "") + "::000",
            "source_id": md.get("source_id", ""),
            "title": md.get("title", ""),
            "section": md.get("section", ""),
            "text": text,
            "tax_year": md.get("tax_year"),
            "form_id": md.get("form_id"),
            "source_type": md.get("source_type"),
            "line": md.get("line", ""),
            "topics": topics,
            "distance": distance,
        }



class FakeEmbedder:
    def embed_one(self, text):
        return [0.0] * 8


def test_a_line_number_adds_its_chunks_and_discards_nothing():
    """A line number brings its chunks in and promotes them; the rest still survive.

    Filtering on `line` is what once answered a question about the commute allowance
    from a document about doppelte Haushaltsführung: only 55 of 775 chunks carry the
    metadata, so filtering kept whichever of those survived and dropped the corpus.

    The distance cutoff does not apply to a chunk found *by* its line. That is the same
    rule the lexical tier already follows - the term being present in the text is
    evidence of its own, independent of where the vectors landed - and it is the point
    of the lookup: a passage naming Zeile 31 that embeds far from the question is
    exactly the one promotion alone could never reach.
    """
    rows = [
        ("(+++ Zur Anwendung vgl. § 52 +++)", {"source_id": "a", "line": ""}, 0.2),      # footnote noise
        ("Anderes Thema.", {"source_id": "c", "line": "45"}, 0.30),                      # other line
        ("Zeile 31 erklärt.", {"source_id": "b", "line": "31,32"}, 0.35),                # the line asked for
        ("Weit entfernt.", {"source_id": "d", "line": "31"}, 0.9),                       # far, but named
    ]
    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("query", line=31)

    # Both chunks naming the line come first; the unrelated one survives below them;
    # footnote noise is still gone, because that filter is about the text itself.
    assert [c.metadata["source_id"] for c in result.chunks] == ["b", "d", "c"]
    assert result.strategies[0] == "line:31"


def test_an_unmatchable_line_changes_nothing():
    """The analyzer invents line numbers, so a miss has to be free."""
    rows = [("Text.", {"source_id": "x", "line": "10"}, 0.3)]
    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("query", line=99)  # no chunk carries line 99
    assert result.strategies == ["semantic"]      # no retry needed, nothing was lost
    assert result.chunks[0].metadata["source_id"] == "x"


def test_a_wrong_line_guess_no_longer_outranks_the_lexical_rescue():
    """A real question — "Sind Gewerkschaftsbeiträge absetzbar?" — used to yield line 21
    while the answer sits on line 53. The lexical hit has to keep the top spot."""
    rows = [
        ("Beiträge zur Rentenversicherung.", {"source_id": "rente", "line": "10"}, 0.30),
        ("Beiträge an Gewerkschaften.", {"source_id": "par9", "line": "53"}, 0.80),
    ]
    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("Sind Gewerkschaftsbeiträge absetzbar?", line=21)
    assert result.lexical_rescued
    assert not any(s.startswith("line:") for s in result.strategies)
    assert result.chunks[0].metadata["source_id"] == "par9"


def test_retriever_where_clause():
    """The metadata filter as SQL: a fragment and the parameters that fill it.

    One topic and several are the same clause now - `?|` is "the array contains any of
    these" - where Chroma needed a bare flag for one and an `$or` for more, and
    rejected an `$or` of length one.
    """
    assert Retriever._build_where(["a"], None) == ("topics ?| %s", [["a"]])
    assert Retriever._build_where(["a", "b"], None) == ("topics ?| %s", [["a", "b"]])
    assert Retriever._build_where(["a"], "anlage_n") == (
        "topics ?| %s and form_id = %s", [["a"], "anlage_n"]
    )
    # None and not an empty filter: no metadata tier ran at all, and the trace says so.
    assert Retriever._build_where(None, None) is None


def test_document_is_reachable_by_every_topic_not_just_its_first():
    """The berufsverbaende regression, at the retrieval end."""
    md = {"source_id": "par9", "topic_entfernungspauschale": True,
          "topic_berufsverbaende": True}
    r = Retriever(FakeChunks([("Beiträge an Berufsverbände.", md, 0.4)]), FakeEmbedder())
    result = r.search("query", topics=["berufsverbaende"])
    assert result.metadata_filtered
    assert [c.metadata["source_id"] for c in result.chunks] == ["par9"]


def test_topic_filter_that_matches_nothing_no_longer_discards_the_search():
    """A wrong topic guess used to drop every filter and decide the whole retrieval."""
    rows = [("Allgemeiner Text.", {"source_id": "x", "topic_pauschbetrag": True}, 0.3)]
    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("query", topics=["berufsverbaende"])
    assert not result.metadata_filtered
    assert result.strategies == ["semantic"]
    assert [c.metadata["source_id"] for c in result.chunks] == ["x"]


def test_lexical_rescue_outranks_a_nearer_but_wrong_chunk():
    """Why the rescue exists: "Beiträge" embeds closer to pensions than to unions.

    The § 9 chunk is far away in vector space — far enough that it fell outside the
    top 20 against the real KB — but it contains the term the question is about, so it
    is ranked ahead of the nearer chunk that merely shares a word.
    """
    rows = [
        ("Beiträge zur Rentenversicherung sind begrenzt abziehbar.", {"source_id": "rente"}, 0.30),
        ("Beiträge an Gewerkschaften sind Werbungskosten.", {"source_id": "par9"}, 0.80),
    ]
    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("Sind Gewerkschaftsbeiträge absetzbar?")
    assert result.lexical_rescued
    assert [c.metadata["source_id"] for c in result.chunks] == ["par9", "rente"]


def test_a_needle_matching_much_of_the_corpus_is_not_used():
    """Selectivity is the whole point: "Werbungsko" matched 137 of 775 real chunks.

    Ranking on it flooded the lexical tier with § 9 passages about Einbürgerung and
    Werbegeschenke, which beat the actual Berufsverbände passage on distance. Only rare
    needles carry information about *which* chunk answers the question.
    """
    common = [(f"Werbungskosten Fall {i}.", {"source_id": f"c{i}"}, 0.30)
              for i in range(LEXICAL_MAX_MATCHES + 1)]
    rare = [("Beiträge an Gewerkschaften.", {"source_id": "par9"}, 0.80)]
    r = Retriever(FakeChunks(common + rare), FakeEmbedder())
    result = r.search("Sind Gewerkschaftsbeiträge als Werbungskosten absetzbar?")
    assert "lexical:Gewerkscha" in result.strategies
    assert "lexical:Werbungsko" not in result.strategies
    assert result.chunks[0].metadata["source_id"] == "par9"


def test_a_rare_needle_with_many_hits_no_longer_buries_the_answer():
    """The Verpflegungspauschalen gap recorded in eval/LIMITATIONS.md.

    "Dienstreis" matches 16 of 775 chunks — rare enough to qualify as a needle, and
    still three times k. Those 16 took every slot, so the BMF Reisekosten letter that
    answers the question sat at rank 18, even though its distance (0.34) was the second
    best in the whole collection and the topic filter ranked it second. The document was
    written off as unreachable and the fix was assumed to be a larger k; the tier was
    the problem, and k=12 would not have reached it either.
    """
    flood = [(f"Dienstreisen, Fall {i}.",
              {"source_id": f"noise{i}", "topic_reisekosten": True}, 0.40 + i / 100)
             for i in range(16)]
    # the answer names none of the query's terms — it was only ever found by the topic
    # filter and the vectors, which is why the lexical tier could bury it
    answer = [("Bei 24 Stunden Abwesenheit gelten 28 €.",
               {"source_id": "bmf", "topic_reisekosten": True}, 0.34)]
    r = Retriever(FakeChunks(flood + answer), FakeEmbedder())

    result = r.search("Verpflegungspauschale Dienstreise Inland", topics=["reisekosten"], k=5)

    ids = [c.metadata["source_id"] for c in result.chunks]
    assert "bmf" in ids, "the document that answers the question is out of context again"
    # the lexical tier may still go first — that is what it is for — but only up to its
    # cap, so at most that many chunks can stand between the answer and the top
    assert ids.index("bmf") <= LEXICAL_TIER_MAX


def test_lexical_hits_outrank_metadata_hits():
    """A term in the chunk beats a topic flag on its 80-chunk document.

    Sorting the two together by distance is what let § 9 passages that merely share the
    topic outrank the passage that actually names Berufsverbände.
    """
    rows = [
        ("Werbegeschenke an Kunden.", {"source_id": "par9-noise", "topic_berufsverbaende": True}, 0.31),
        ("Ausgaben im Zusammenhang mit Berufsverbänden.", {"source_id": "par9-r93"}, 0.39),
    ]
    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("Sind Berufsverbandsbeiträge absetzbar?", topics=["berufsverbaende"])
    assert result.strategies[0].startswith("lexical:")
    assert [c.metadata["source_id"] for c in result.chunks] == ["par9-r93", "par9-noise"]


def test_needles_are_prefixes_of_capitalised_german_nouns():
    # the sources say "Gewerkschaft ... Beiträge"; the question compounds them, so only
    # a prefix reaches the shared stem
    assert Retriever._needles("Sind Gewerkschaftsbeiträge absetzbar?") == ["Gewerkscha"]
    assert Retriever._needles("was kostet das") == []       # nothing capitalised
    # longest first, and "Ist" is too short to be a useful needle
    assert Retriever._needles("Ist Homeoffice Arbeitszimmer") == ["Arbeitszim", "Homeoffice"]


# --- response depth ---

def _system_prompt(llm) -> str:
    """The system message of the generation call - the analysis call is calls[0]."""
    return llm.calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", ["concise", "balanced", "detailed"])
async def test_the_chosen_depth_is_the_line_the_model_reads(depth):
    """The Settings control has to reach the prompt, or it is decoration again."""
    llm = FakeLLMClient()
    service = TaxService(llm, FakeRetriever())
    await service.answer_question(
        TaxQuestionRequest(text="Pendlerpauschale?", language="en", depth=depth))

    prompt = _system_prompt(llm)
    assert DEPTH_INSTRUCTIONS[depth] in prompt
    for other, line in DEPTH_INSTRUCTIONS.items():
        if other != depth:
            assert line not in prompt


@pytest.mark.asyncio
async def test_a_request_without_a_depth_asks_for_what_it_always_asked_for():
    """Old clients and untouched controls must not get a different assistant.

    The balanced line is the sentence the prompt carried before the field existed,
    so this is the no-change case rather than a fourth behaviour.
    """
    llm = FakeLLMClient()
    service = TaxService(llm, FakeRetriever())
    await service.answer_question(TaxQuestionRequest(text="Pendlerpauschale?", language="en"))

    assert "Be concise: a short direct answer, then essential details." in _system_prompt(llm)


def test_an_unknown_depth_never_reaches_the_lookup():
    """`DEPTH_INSTRUCTIONS[request.depth]` is a KeyError unless the schema stops it."""
    with pytest.raises(ValidationError):
        TaxQuestionRequest(text="Pendlerpauschale?", depth="exhaustive")


# --- service orchestration ---

@pytest.mark.asyncio
async def test_out_of_scope_skips_retrieval():
    llm = FakeLLMClient(replies=[
        '{"intent": "out_of_scope", "search_query_de": "", "topics": [], "line": null, "form_id": null}'
    ])
    retriever = FakeRetriever()
    service = TaxService(llm, retriever)
    resp = await service.answer_question(TaxQuestionRequest(text="How do I bake bread?", language="en"))
    assert resp.intent == "out_of_scope"
    assert retriever.searches == []          # no retrieval happened
    assert resp.sources == []
    assert "Anlage N" in resp.summary


@pytest.mark.asyncio
async def test_empty_retrieval_is_honest():
    llm = FakeLLMClient()  # default: knowledge analysis, then answer (unused)
    retriever = FakeRetriever(chunks=[])
    service = TaxService(llm, retriever)
    resp = await service.answer_question(TaxQuestionRequest(text="Question", language="en"))
    assert resp.sources == []
    assert any("No relevant sources" in w for w in resp.warnings)


@pytest.mark.asyncio
async def test_citations_become_sources_and_usage_sums():
    llm = FakeLLMClient()  # answer cites lsth-2022-anhang-14...
    service = TaxService(llm, FakeRetriever())
    resp = await service.answer_question(TaxQuestionRequest(text="Pendlerpauschale?", language="en"))
    assert resp.sources[0].source_id == "lsth-2022-anhang-14-entfernungspauschalen"
    assert resp.usage.total_tokens == 30     # two LLM calls x 15
    assert resp.intent == "knowledge"


def test_a_line_number_does_not_promote_another_forms_line():
    """Anlage N has a Zeile 31 and so does Anlage N-Doppelte Haushaltsführung.

    They are different lines on different sheets, and the promotion used to match on
    the number alone - so "what goes in Zeile 31 of Anlage N" put chunks about a second
    household at the top and the question went unanswered.
    """
    own = {"source_id": "anlage-n", "form_id": "anlage_n", "line": "31,32"}
    other = {"source_id": "dhf", "form_id": "anlage_n_dhf", "line": "30,31"}
    rows = [("Zeile 31 der Anlage N.", own, 0.5),
            ("Zeile 31 der Anlage N-DHF.", other, 0.3)]

    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("Was gehört in Zeile 31?", line=31, form_id="anlage_n")

    assert [c.metadata["source_id"] for c in result.chunks][0] == "anlage-n"


def test_a_line_number_finds_a_passage_the_vectors_missed():
    """The tier Chroma could not have, and the failure it explains.

    Promotion can only reorder what the vector search already returned, so a passage
    that named the line and did not embed near the question stayed invisible - and the
    answer was in the corpus the whole time. Postgres can ask for it directly.
    """
    named = {"source_id": "anlage-n", "form_id": "anlage_n", "line": "31,34"}
    far = {"source_id": "other", "form_id": "anlage_n", "line": ""}
    rows = [("Tragen Sie bitte in Zeile 31 die Kilometer ein.", named, 0.99),
            ("Etwas ganz anderes.", far, 0.1)]

    r = Retriever(FakeChunks(rows), FakeEmbedder())
    result = r.search("Was gehört in Zeile 31?", line=31, form_id="anlage_n")

    assert result.strategies[0] == "line:31"
    assert [c.metadata["source_id"] for c in result.chunks][0] == "anlage-n"
