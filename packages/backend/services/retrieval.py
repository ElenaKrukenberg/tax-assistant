import re
from dataclasses import dataclass, field

from core.chunking import TOPIC_FLAG_PREFIX

# Retrieval over the Chroma KB. Three strategies run against a single embedding of the
# query and their results are pooled, so a filter can only ever add candidates:
#
#   lexical  — chunks containing a rare, exact term from the question, matched with
#              `where_document`. This rescues terminology the embedding ranks badly:
#              for "Sind Gewerkschaftsbeiträge absetzbar?" the vectors put pension and
#              insurance contributions on top and the § 9 union-dues passages did not
#              appear in the first twenty results at all.
#   metadata — topic flags and form_id in the Chroma `where` filter. Precise about the
#              document, but a legitimately empty result must not decide the retrieval.
#   semantic — the plain unfiltered vector search, always run.
#
# This replaces an either/or arrangement with a cliff in it: the filtered query decided
# everything, and the moment it returned nothing every filter was dropped and the answer
# came from a pure semantic search over the whole KB. Nothing sat in between, so a
# single bad topic guess cost the entire retrieval.
#
# Results are ranked by tier, then by distance within the tier, in the order above. A
# lexical hit is evidence about *this chunk* — the term is in it. A topic flag is only
# evidence about its document, which for the 80-chunk § 9 is weak: sorting the two
# together by distance let § 9 passages on Einbürgerung and Werbegeschenke outrank the
# actual passage on Berufsverbände. Semantic hits fill whatever the first two miss
# rather than replacing them.
#
# `line` used to be the exception that broke the rule above: it was a post-filter, so it
# subtracted. Measured on the 26-case evaluation set: the analyzer returned a line number
# for 12 of them and in 10 it was the same invented line 31 — including for "Wie hoch ist
# die Entfernungspauschale?", which names no line at all. Only 55 of 775 chunks carry line
# metadata, all of them in the Anleitung PDFs, so filtering on it discarded every document
# that answered the question and kept one or two survivors that merely happened to be
# tagged. That is how a question about the commute allowance came back answered from a
# document about doppelte Haushaltsführung. The empty-result retry never helped, because
# the result was not empty — it was wrong.
#
# So a line number now only promotes: matching chunks rank first, nothing is removed.
# It is stored as a CSV string ("27,28,31") and Chroma metadata filters cannot do
# membership tests, so the match is done in Python either way.
#
# Footnote-only chunks ("+++ Zur Anwendung vgl. ... +++") are still dropped — they embed
# close to everything.

# Which strategies a retriever runs. Every deployment uses all three; the evaluation
# harness builds a semantic-only retriever to measure what the other two actually add
# (see eval/README.md). Ablation rather than comparing two commits: the hybrid pooling
# is already the shipped behaviour, so there is no "before" left to run.
ALL_STRATEGIES = ("lexical", "metadata", "semantic")

# Chunks handed to generation. The pipeline never passes k, so this is the number that
# ships; `eval/collect.py --k` overrides it for a run, and `eval/k_sweep.py` measures the
# rank at which each reference document enters the context. See eval/results/k-sweep.md.
DEFAULT_K = 5

MAX_DISTANCE = 0.62   # cosine distance cutoff — beyond this, chunks are noise
# Lexical hits are held to a looser cutoff: the exact term is present in the text,
# which is evidence of its own and independent of how the vectors happened to land.
LEXICAL_MAX_DISTANCE = 0.85
FETCH_K = 4 * DEFAULT_K   # overfetch to survive post-filtering
# Relative to k and not to the corpus: what post-filtering removes is a property of
# the query, not of how many documents exist. Exactly 20 at today's k=5, so the
# acceptance run is unchanged (#9, point 5).

# Lexical needles: capitalised words of at least MIN_TERM_CHARS, truncated to a prefix.
# The question compounds German nouns ("Gewerkschaftsbeiträge") where the sources keep
# the words apart ("Gewerkschaft hat Herr Muster Beiträge"), so matching a whole word
# finds nothing — only a prefix reaches the shared stem. Chroma's $contains is
# case-sensitive, and German nouns are capitalised in both question and sources, so the
# token keeps its own capitalisation.
MIN_TERM_CHARS = 8
NEEDLE_CHARS = 10
MAX_NEEDLES = 3
TERM_RE = re.compile(r"[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]{%d,}" % (MIN_TERM_CHARS - 1))
# A needle is only worth ranking on if it is rare. "Werbungsko" matches 137 of 775
# chunks and tells us nothing about which of them answers the question — used as a
# needle it simply floods the top tier. "Gewerkscha" matches 5 and points straight at
# the answer. Roughly 5% of the collection is the line between the two.
def _lexical_max_matches() -> int:
    """How common a term may be and still be worth ranking on.

    Relative to the corpus, because "common" is: a term in 40 of 775 chunks is
    selective and the same term in 40 of 80,000 is noise. Exactly 40 at today's 775
    rows, so the acceptance run is untouched (#9, point 5), and a floor of 40 keeps a
    small or half-loaded corpus from rejecting every needle it has.
    """
    from db.kb_store import count

    try:
        return max(40, int(count() * 0.005))
    except Exception:  # noqa: BLE001 - a knowledge base that cannot be counted
        return 40


LEXICAL_MAX_MATCHES = 40

# How many lexical chunks may sit ahead of the other two tiers. Rarity alone does not
# bound this: 40 matching chunks is rare in a 775-chunk collection and still eight times
# k, so one qualifying needle could fill every slot. Measured on
# "Welche Verpflegungspauschalen gelten bei einer Dienstreise im Inland?" — the needle
# "Dienstreis" matches 16 chunks, which took ranks 1-16, and the BMF Reisekosten letter
# that answers the question was pushed to rank 18 even though the metadata tier ranked it
# second and its distance (0.34) was second best in the whole collection. That is the
# document LIMITATIONS.md recorded as unreachable.
#
# Three, because the tier is a rescue and not a ranking of its own: a lexical hit says the
# term is in the chunk, which is worth putting a few chunks in front of the vectors, not
# worth crowding them out. The case the tier exists for — "Sind Gewerkschaftsbeiträge
# absetzbar?", where § 9 was outside the first twenty vector results — needs its top two,
# so it is unaffected. A dropped lexical chunk is not lost: the metadata and semantic
# queries can still return it on their own merits.
LEXICAL_TIER_MAX = 3

# How many chunks the line lookup may contribute. Small on purpose: a line number is
# precise, so a handful of passages name it, and a larger number would let one
# well-indexed document crowd out everything the question also needs.
LINE_TIER_MAX = 3


@dataclass
class RetrievedChunk:
    text: str
    metadata: dict
    distance: float


@dataclass
class RetrievalResult:
    chunks: list
    # Which strategies contributed, in order, e.g. ["metadata", "lexical:Gewerkscha"].
    strategies: list = field(default_factory=list)

    @property
    def metadata_filtered(self) -> bool:
        return "metadata" in self.strategies

    @property
    def lexical_rescued(self) -> bool:
        return any(s.startswith("lexical:") for s in self.strategies)


def _vector_literal(values) -> str:
    """pgvector's text form for a query vector."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _is_footnote_noise(text: str) -> bool:
    return "+++" in text and len(text) < 300


class Retriever:
    def __init__(self, chunks, embedder, strategies: tuple = ALL_STRATEGIES):
        # `chunks` is anything with `nearest` and `count_matches`: the Postgres store in
        # production, a list-backed fake in the tests. Two methods rather than a
        # vendor's client - a fake of two methods cannot drift from the real thing the
        # way a fake of Chroma's whole API could, and did.
        if chunks is None:
            from db.kb_store import PostgresChunks

            chunks = PostgresChunks()
        self.chunks = chunks
        self.embedder = embedder
        self.strategies = tuple(strategies)
        self.embedder = embedder
        self.strategies = tuple(strategies)

    def search(self, query: str, topics: list | None = None, line: int | None = None,
               form_id: str | None = None, k: int = DEFAULT_K) -> RetrievalResult:
        vector = self.embedder.embed_one(query)
        needles = self._selective_needles(query)
        where = self._build_where(topics, form_id)

        ranked, strategies = self._gather(vector, needles, where)
        # A line number reorders, never removes. There is nothing to retry: an analyzer
        # that invented a line costs the ranking nothing, and a real one still puts its
        # chunks on top.
        if line is not None:
            # Looked up, not merely promoted. A line number is the most discriminating
            # thing a question can carry, and reordering could only ever raise a chunk
            # the vector search had already found - so a passage that named the line
            # and did not embed near the question stayed invisible.
            named = self._by_line(line, form_id)
            matched = [c for c in ranked if self._matches_line(c, line, form_id)]
            seen = {self._key(c.text, c.metadata) for c in matched}
            for chunk in named:
                if self._key(chunk.text, chunk.metadata) not in seen:
                    matched.append(chunk)
                    seen.add(self._key(chunk.text, chunk.metadata))
            if matched:
                strategies.insert(0, f"line:{line}")
                rest = [c for c in ranked
                        if self._key(c.text, c.metadata) not in seen]
                ranked = matched + rest

        return RetrievalResult(chunks=ranked[:k], strategies=strategies)

    @staticmethod
    def _matches_line(chunk, line: int, form_id: str | None = None) -> bool:
        """Whether a chunk speaks about that line *of that form*.

        The form matters and used to be ignored. Anlage N has a Zeile 31 and so does
        Anlage N-Doppelte Haushaltsführung, and they are different lines on different
        sheets - so asking what belongs in Zeile 31 promoted chunks about the second
        household to the top and the question went unanswered. With no form in the
        analysis the number alone is all there is, and the promotion stays as it was.
        """
        lines = {s.strip() for s in (chunk.metadata.get("line") or "").split(",") if s.strip()}
        if str(line) not in lines:
            return False
        return form_id is None or chunk.metadata.get("form_id") == form_id

    def _gather(self, vector, needles, where) -> tuple[list, list]:
        """Run all three strategies and rank their pooled results by tier."""
        lexical: list = []
        metadata: list = []
        semantic: list = []
        seen: set = set()
        strategies: list[str] = []

        def collect(tier: list, chunks: list) -> bool:
            added = False
            for chunk in chunks:
                key = self._key(chunk.text, chunk.metadata)
                if key in seen:
                    continue
                seen.add(key)
                tier.append(chunk)
                added = True
            return added

        if "lexical" in self.strategies:
            # Pooled across needles and capped, so the tier promotes the few best exact
            # matches instead of however many the rarest needle happens to have.
            hits = [(chunk, needle)
                    for needle in needles
                    for chunk in self._query(vector, LEXICAL_MAX_DISTANCE, contains=needle)]
            hits.sort(key=lambda hit: hit[0].distance)
            for chunk, needle in hits:
                if len(lexical) >= LEXICAL_TIER_MAX:
                    break
                # A strategy is only named if it put a chunk in the result, so the trace
                # keeps saying what actually contributed.
                if collect(lexical, [chunk]) and f"lexical:{needle}" not in strategies:
                    strategies.append(f"lexical:{needle}")

        if where is not None and "metadata" in self.strategies:
            if collect(metadata, self._query(vector, MAX_DISTANCE, where=where)):
                strategies.append("metadata")

        if "semantic" in self.strategies:
            if collect(semantic, self._query(vector, MAX_DISTANCE)):
                strategies.append("semantic")

        by_distance = lambda c: c.distance  # noqa: E731
        ranked = (sorted(lexical, key=by_distance)
                  + sorted(metadata, key=by_distance)
                  + sorted(semantic, key=by_distance))
        return ranked, strategies

    @staticmethod
    def _build_where(topics, form_id):
        """The metadata filter, as a SQL fragment and its parameters.

        `None` when there is nothing to filter on, which is what the caller checks -
        a filter that matches everything is not the same as no metadata tier at all,
        and the trace says which tiers contributed.
        """
        clauses: list[str] = []
        params: list = []
        if topics:
            # `?|` is "the JSON array contains any of these keys", which is what the
            # `$or` over topic flags meant in Chroma.
            clauses.append("topics ?| %s")
            params.append(list(topics))
        if form_id:
            clauses.append("form_id = %s")
            params.append(form_id)
        if not clauses:
            return None
        return " and ".join(clauses), params

    @staticmethod
    def _needles(query: str) -> list[str]:
        """Candidate needles from the query, longest term first."""
        tokens = sorted(set(TERM_RE.findall(query)), key=len, reverse=True)
        needles = []
        for token in tokens:
            needle = token[:NEEDLE_CHARS]
            if needle not in needles:
                needles.append(needle)
        return needles

    def _selective_needles(self, query: str) -> list[str]:
        """Candidate needles that are rare enough in the KB to rank on, rarest first."""
        counted = []
        cap = _lexical_max_matches()
        for needle in self._needles(query):
            matches = self._count_matches(needle)
            if 0 < matches <= cap:
                counted.append((matches, needle))
        counted.sort()
        return [needle for _, needle in counted[:MAX_NEEDLES]]

    def _count_matches(self, needle: str) -> int:
        # Never more than the cap plus one: the answer is only used to decide whether a
        # needle is too common to rank on, so counting past it buys nothing.
        return self.chunks.count_matches(needle, _lexical_max_matches() + 1)

    @staticmethod
    def _key(text, md):
        return md.get("source_id", ""), md.get("section", ""), text

    def _merge(self, pool: dict, chunks: list, skip: dict | None = None) -> bool:
        added = False
        for chunk in chunks:
            key = self._key(chunk.text, chunk.metadata)
            if key in pool or (skip is not None and key in skip):
                continue
            pool[key] = chunk
            added = True
        return added

    def _by_line(self, line: int, form_id: str | None) -> list:
        """Chunks that name this line of this form, whatever the vectors said."""
        from db.kb_store import metadata_of

        records = self.chunks.by_line(line, form_id, LINE_TIER_MAX)
        return [RetrievedChunk(text=r["text"], metadata=metadata_of(r), distance=0.0)
                for r in records if not _is_footnote_noise(r["text"])]

    def _query(self, vector, max_distance, where=None, contains=None):
        """The nearest chunks, past the distance cutoff and the footnote filter."""
        from db.kb_store import metadata_of

        chunks = []
        for record in self.chunks.nearest(vector, FETCH_K, where=where, contains=contains):
            distance = float(record["distance"])
            if distance > max_distance or _is_footnote_noise(record["text"]):
                continue
            chunks.append(RetrievedChunk(text=record["text"],
                                         metadata=metadata_of(record),
                                         distance=distance))
        return chunks
