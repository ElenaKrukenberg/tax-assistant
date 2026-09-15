# Official-source strategy for the annual tax knowledge base

Checked on 31 August 2026. Scope: German income tax, initially an ordinary
individual return and Anlage N. Only primary official sources were used.

The Russian translation is kept at the same relative path under `docs_ru/`.

## Executive summary

The two local form directories are both useful, but for different jobs:

- `anleitungen/` is an application-oriented source: who needs an Anlage, what a
  particular line means, which amounts and documents matter, and worked examples.
  Reviewed instructions should be included in retrieval after layout-aware parsing.
- `vordrucke/` is the source of truth for the return's visible structure: field
  labels, line numbers, printed Kennzahlen, units, and choices. Forms should remain
  immutable PDF assets and feed a versioned field schema. Their flat extracted text
  is not good general retrieval material.
- Forms and instructions do not replace the legal and interpretive layer. The main
  annual source for that layer should be the BMF's HTML `EStH`, supplemented by
  `LStH` for employment topics. Only the laws and BMF letters needed by supported
  topics should be added.

The knowledge base is therefore not one giant download. Each `tax_year` is a
separate immutable package with four layers:

1. forms as PDF assets and field structure;
2. instructions as line-oriented application guidance;
3. EStH/LStH sections as annual rules, Richtlinien, and Hinweise;
4. only the statutory provisions and BMF letters actually needed by supported
   scenarios.

## Source matrix for the PDF-first product

| Source | Include in the KB? | Role and limit |
|---|---|---|
| Public ELSTER/FMS `Anleitungen` | **Yes** | The main practical layer. Parse by form, year, and `Zeile` range; retain the source URL, publication status, retrieval date, and checksum. |
| Public final `Vordrucke` | **Yes, but not as ordinary RAG text** | Retain the original for PDF generation and visual verification. Extract a versioned field schema containing at least `line`, `kennzahl`, `label`, and `bbox`. Never promote an `Arbeitsversion` or other draft as final. [FMS](https://www.formulare-bfinv.de/) is an official public source. |
| [BMF EStH by year](https://esth.bundesfinanzministerium.de/esth/2025/home.html) | **Yes: core annual rule layer** | Explains why an income-tax rule applies. Select only sections used by supported forms and scenarios. |
| [BMF LStH by year](https://lsth.bundesfinanzministerium.de/lsth/2025/home.html) | **Yes for Arbeitnehmer and Anlage N** | Covers Arbeitslohn, Werbungskosten, travel, Entfernungspauschale, and Homeoffice. It supplements rather than replaces the form instruction. |
| [Gesetze im Internet: EStG](https://www.gesetze-im-internet.de/estg/index.html) | **Yes, selectively** | HTML/XML is machine-readable, but it is the current consolidated law, not an annual historical snapshot. A current download must not be labelled as the 2025 text without an applicability check. |
| BMF letters | **Yes, selectively** | Include a letter only when EStH/LStH or an instruction cites it, or when a supported scenario needs detail not supplied by those sources. The relevant text belongs in retrieval; the original PDF remains evidence. |
| [BMF DBA material](https://www.bundesfinanzministerium.de/Content/DE/Standardartikel/Themen/Steuern/Internationales_Steuerrecht/Staatenbezogene_Informationen/doppelbesteuerungsabkommen.html) | **Only for international scenarios** | Add the agreement and guidance for the particular country and year needed by N-AUS/AUS. Do not ingest every treaty into the ordinary domestic flow. |
| Gated ERiC binaries, schemas, and developer documentation | **No, not in the public PDF-first KB** | They support future electronic filing: interfaces, data formats, plausibility checks, releases, and testing. They remain under gitignored `elster_eric/`. Licence §14 requires confidentiality, and §3 ties ERiC to electronic transmission. Do not derive the public KB or PDF-only validation from them without clarification from the LfSt. |

Developer registration does not provide a superior legal knowledge base for the
current product. It provides the technical ecosystem needed later for ELSTER
transmission: ERiC, interface and schema documentation, examples, plausibility
documentation, manufacturer support channels, release information, and the ability
to use a Hersteller-ID.

## What is in `official_sources/forms`

The local workspace contains two annual public form packages:

| Directory | Instructions | Forms |
|---|---:|---:|
| `official_sources/forms/ESt_2025` | 25 PDFs, 97 pages | 35 PDFs, 97 pages |
| `official_sources/forms/ESt_2026` | 25 PDFs | 33 PDFs |

Local download history and quarantine metadata identify their source as the public
[`ESt_2025.zip`](https://download.elster.de/download/vordrucke/ESt_2025.zip) and
[`ESt_2026.zip`](https://download.elster.de/download/vordrucke/ESt_2026.zip),
downloaded on 31 August 2026 at 21:20. They are not the gated ERiC release bundles
named `Vordrucke_<year>_ERiC-<version>.zip`. Their location on an ELSTER developer
page does not make them ERiC runtime material.

All 60 PDFs in the 2025 package were inspected:

- all 25 instructions contain extractable text, are tagged, and need no OCR;
- all 35 forms contain extractable text, and 33 are tagged;
- none has AcroForm fields (`Form: none`), so these are printed layouts rather than
  fillable field definitions;
- the two untagged exceptions still have extractable text;
- the Anlage N instruction yields meaningful text from all eight pages, including
  headings, examples, and amounts; the N form yields line numbers, Kennzahlen, and
  labels;
- four 2025 forms — N, AUS, KAP, and VOR — identify themselves as
  `Arbeitsversion`. Their presence in the archive is not proof that they are final.

The hard part is therefore structural reconstruction, not OCR.

## Parsing complexity

### Instructions: moderate

The PDFs are text-based, and headings such as `Zeile 4 bis 17` provide natural chunk
boundaries. They are also written for taxpayers and contain useful examples.

The difficulties are multi-column reading order, word-break hyphenation, marker
symbols inside sentences, and tables or lists losing their hierarchy. A fixed
character splitter may separate a rule from the form line that gives it meaning.

The deterministic pipeline should extract text with coordinates, restore columns,
identify `Zeile ...` headings, normalise word breaks, and emit records such as:

```text
form_id
tax_year
line_from
line_to
heading
text
page
```

The output then needs a small visual sample check. It does not require an OCR or
vision model.

The current `KB/` already contains extracted September 2025 instructions for ESt 1 A,
Anlage N, N-Doppelte Haushaltsführung, and N-AUS. Those files should be audited, not
ingested a second time.

### Forms: poor general RAG input, suitable for a field schema

Flat text extraction does not preserve the spatial relationship between a line
number, label, Kennzahl, Person A/Person B column, unit, and choice. With no AcroForm
fields, that relationship must be reconstructed from coordinates and visually
verified.

Keep the PDF as the original asset and create a separate schema with fields such as:

```text
form_id
tax_year
page
line
kennzahl
label
value_type
unit
choices
bbox
source_revision
```

The advertising poster is neither a legal source nor a form schema source. The
Anlage U sample is needed only if the product supports that scenario.

## The practical 2025 acquisition plan

The product must work outward from its supported forms and topics. It must not try to
snapshot every German tax law or read every BMF letter.

### A. Annual handbooks are the starting point

For a supported 2025 topic, prefer the annual
[EStH 2025](https://esth.bundesfinanzministerium.de/esth/2025/home.html) and, for
employment, [LStH 2025](https://lsth.bundesfinanzministerium.de/lsth/2025/home.html).
They already organise the law, Richtlinien, Hinweise, court references, and BMF
guidance for the year. Store only the sections needed by supported scenarios.

This removes the need to reconstruct the entire 2025 EStG from today's consolidated
law.

### B. Statutory text is fetched only when a KB answer needs it

For each statutory provision actually cited by a selected EStH/LStH section or a
supported answer:

1. download the provision or full law from `gesetze-im-internet.de`, preferably XML
   for deterministic parsing and HTML as a human-readable source;
2. retain the exact bytes, canonical URL, retrieval timestamp, the source's stated
   revision information, and SHA-256;
3. check the provision's applicability note in the annual EStH and, where relevant,
   the transition rule in §52 EStG;
4. mark the source `verified_for_tax_year: 2025` only after that check.

This is not a manual file-by-file review of the whole statute. It is a bounded check
for the small set of sections actually retrieved by the product. The current KB has
only a few standalone EStG/AO extracts, so the initial audit is correspondingly
small and can be scripted as an inventory.

The [Federal Law Gazette platform](https://www.recht.bund.de/de/home/home_node.html)
is an escalation source, not a mandatory second pass. Consult it only if the current
consolidated wording differs from the annual handbook, the transition rule is
ambiguous, or the exact amending act and effective date are needed. Do not download
every Gazette issue.

### C. BMF letters are discovered from selected topics, not by bulk reading

The page titled
[Application of BMF letters](https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Weitere_Steuerthemen/Normenflut/2025-03-14-anwendung-von-bmf-schreiben.html)
is an annual index page. Its four PDFs are not four substantive tax guides that all
belong in the KB. They are:

- the annual administrative notice;
- the corresponding Länder notice;
- the positive list of guidance still applicable to the current assessment period;
- the list removed since the preceding positive list.

The application should not read those lists at answer time, and Elena should not
read them cover to cover. Use them as a lookup table after a relevant EStH/LStH
section or instruction cites a letter by date, file reference, or BStBl citation.

For each cited letter:

1. resolve its exact official BMF publication;
2. confirm in the positive/superseded lists that it was still applicable for 2025;
3. read only its scope and applicability paragraphs plus the sections needed by the
   supported topic;
4. retain the original PDF and metadata for auditability;
5. place the reviewed relevant text — not merely the inert PDF — into retrieval.

If no selected source cites a BMF letter and the supported answer does not need one,
no letter is added. This turns an unbounded archive into a small dependency graph:

```text
supported form/topic
  -> Anleitung and EStH/LStH section
      -> cited statutory provisions
      -> cited BMF letter, if any
```

### D. What an immutable snapshot means

A snapshot is not one giant archive. It is a versioned manifest plus the exact raw
files and reviewed derived chunks for one tax year:

```text
tax_year: 2025
sources/
  <immutable downloaded HTML, XML, and PDF files>
manifest.json
derived/
  <reviewed instruction and handbook chunks>
forms/
  <final form assets and versioned field schemas>
```

The manifest records at least:

```text
source_id
tax_year
source_type
form_id or legal_reference
title
canonical_url
retrieved_at
source_revision or Stand
publication_status
applicability_note
sha256
supersedes
```

The point is reproducibility: when an answer or generated PDF is challenged later,
the product can identify the exact official bytes and derived text it used. A new
tax year creates a sibling snapshot. An official correction for the same year creates
a new revision and preserves the superseded artifact.

The concrete storage layout and database schema belong to the implementation issue;
this document defines the source-selection rule.

## Official explanatory and legal sources

### EStH: the main annual income-tax layer

The [Official Income Tax Handbook 2025](https://esth.bundesfinanzministerium.de/esth/2025/home.html)
is structured HTML for a named year. Its preface says it contains the EStG, EStDV,
EStR, and Hinweise applicable to assessment period 2025. It is easier and safer to
parse than PDF instructions because headings, sections, links, and the year remain
explicit.

EStH answers why a rule applies. It does not replace the Anleitung's answer to where
the value belongs in the form.

### LStH: required for Anlage N

The [Official Wage Tax Handbook 2025](https://lsth.bundesfinanzministerium.de/lsth/2025/home.html)
combines relevant EStG, EStDV, LStDV, LStR, and Hinweise. For an employee product it
is needed alongside EStH, especially for Werbungskosten, Arbeitslohn,
Entfernungspauschale, travel, and Homeoffice.

The BMF's [official handbooks landing page](https://esth.bundesfinanzministerium.de/Home/home.html)
provides annual editions and requires the source to be acknowledged and the work not
to be distorted. Normalised chunks therefore retain direct provenance while the raw
source remains immutable.

### Gesetze im Internet: machine-readable, but current

The [EStG](https://www.gesetze-im-internet.de/estg/index.html) is available as HTML,
PDF, EPUB, and XML. The service's guidance identifies XML as suitable for automated
processing.

It publishes the current consolidated wording, not ready-made historical annual
snapshots. A download taken today must therefore keep its own retrieval and revision
metadata and must not be relabelled as the 2023, 2024, or 2025 law without an annual
applicability check.

### FMS: final public forms, not a legal handbook

The [Federal Tax Administration's Form Management System](https://www.formulare-bfinv.de/)
publishes income-tax packages for multiple years and individual forms. It is a useful
official source of final public forms and instructions, but it does not replace
EStH/LStH as the legal and interpretive layer.

Local comparison confirms that similarly named files from FMS and the ELSTER archive
need not be the same artifact. The current FMS `Anlage_N_2025.pdf` is a final FMS
form, while the local ELSTER archive's N PDF identifies itself as
`N (2025/Arbeitsversion)`. Selection must therefore be based on publication status,
revision, and checksum rather than filename alone.

## Immediate MVP priority

1. Start with the forms and scenarios the product actually supports, not all forms.
2. Audit the four existing 2025 instructions for ESt 1 A, N, N-DHH, and N-AUS rather
   than ingesting duplicates.
3. Use final FMS/public forms as PDF assets. Reject or quarantine `Arbeitsversion`
   files for production output.
4. Build a separate field schema from the corresponding forms; do not mix form layout
   text into general retrieval.
5. Add only relevant EStH 2025 and LStH 2025 sections.
6. Inventory the few current standalone EStG/AO extracts, then verify their 2025
   applicability using the procedure above.
7. Resolve and ingest BMF letters only when the selected sources cite them or a
   supported scenario demonstrably requires them.
8. Add 2023, 2024, 2026, and later years as new snapshots, never as updates to 2025.

The result is bounded and automatable: the instructions provide practical form-line
guidance; EStH/LStH provide the annual rule layer; final forms provide assets and
field structure; statutes and BMF letters are small, explicit dependencies rather
than bulk downloads.
