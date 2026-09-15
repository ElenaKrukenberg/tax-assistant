-- The knowledge base moves into Postgres, so a deploy stops rebuilding it.
--
-- Today `render.yaml` runs `python ingest.py --reset` on every backend deploy: 47
-- files, 775 chunks, every embedding recomputed. Three consequences, and the third is
-- the one that matters - a failure while indexing takes down a backend that was
-- otherwise healthy. The store also lives only inside one deploy's filesystem, so
-- nothing survives to the next one.
--
-- Its own schema, `kb`, and not a table among the tax-case tables. The isolation is
-- the point: this is published Finanzamt text, its release runs on its own schedule,
-- and deleting somebody's tax case must never come near it. A separate Supabase
-- project would have isolated it further and the free tier allows two, both taken.
--
-- **Row-level security on, and no policy at all.** Not because these rows belong to
-- anybody - they are the Finanzamt's published documents, identical for everyone - but
-- because a table reachable through Supabase's API with no policy on it can be read by
-- anyone holding the public key. There is nothing secret to read; there is a table that
-- can be pulled down repeatedly on somebody else's bandwidth, and Supabase warns about
-- exactly this. With security on and no policy the API denies everything, while the
-- backend reads it as before: it connects as the owner, and row-level security does not
-- apply to the owner (`db/connection.py:as_owner`).
--
-- **Exactly two indexes** (#9). `pg_trgm` for the substring search the lexical tier
-- does, and a btree on `(tax_year, form_id)` for the metadata filter. No HNSW: it is
-- approximate, 775 rows are scanned exactly in milliseconds, and an approximate index
-- would put a second source of variance inside the measurement this move has to keep
-- steady. The thresholds at which that changes are recorded in #64.

create extension if not exists vector;
create extension if not exists pg_trgm;

create schema if not exists kb;

create table if not exists kb.chunks (
    id          bigserial primary key,
    -- The chunker's own identifier, `<source_id>::NNN`. Unique, so a reload that runs
    -- twice cannot produce the corpus twice.
    chunk_id    text not null unique,
    source_id   text not null,
    title       text not null default '',
    section     text not null default '',
    text        text not null,
    -- 1536 exact dimensions: `text-embedding-3-small` as it comes, not truncated and
    -- not `halfvec`. A shortened vector is a different measurement.
    embedding   vector(1536) not null,
    tax_year    integer,
    form_id     text,
    source_type text,
    -- The Zeilen a chunk speaks about, as the frontmatter writes them: "27,28,31".
    -- Kept as text because that is what it is - a list a human wrote, not a number.
    line        text not null default '',
    -- Topic flags were one boolean column per topic in Chroma, which is a schema that
    -- changes whenever a document does. A JSON array is the same filter and no
    -- migration.
    topics      jsonb not null default '[]'::jsonb,
    -- Which load wrote this row. Nothing reads it yet; it exists so that a future
    -- release can be identified without a migration at the moment it is needed (#9).
    release_id  text not null default '',
    created_at  timestamptz not null default now()
);

comment on schema kb is
    'The knowledge base: published Finanzamt documents, chunked and embedded. Not '
    'user data, which is why nothing here has row-level security, and released on '
    'its own schedule rather than with a backend deploy (issue #32).';
comment on table kb.chunks is
    'One chunk of one official document. Rewritten wholesale by ingest.py inside a '
    'single transaction, so an interrupted load leaves the previous corpus intact.';
comment on column kb.chunks.embedding is
    'vector(1536), exact. Not halfvec and not truncated: a shortened vector changes '
    'what the distance means, and the retrieval evaluation is measured against it.';
comment on column kb.chunks.release_id is
    'Which load wrote this row. Nothing reads it yet - it is here so identifying a '
    'release later is not a migration.';

alter table kb.chunks enable row level security;

comment on table kb.chunks is
    'One chunk of one official document. Rewritten wholesale by ingest.py inside a '
    'single transaction, so an interrupted load leaves the previous corpus intact. '
    'Row-level security is on with no policy: nothing reaches this through the API, '
    'and the backend reads it as the owner, which row-level security does not apply to.';

create index if not exists kb_chunks_text_trgm
    on kb.chunks using gin (text gin_trgm_ops);
create index if not exists kb_chunks_year_form
    on kb.chunks (tax_year, form_id);

insert into schema_versions (version) values ('0014')
on conflict (version) do nothing;
