# ELSTER: what the ERiC licence obliges us to do

Elena registered as an ELSTER developer and accepted the **ERiC-Lizenzvertrag,
Release 43** on 31 August 2026. This file is the engineering checklist drawn from it:
what the agreement requires of us, in our own words, so that every session can check
against it without the contract text being committed.

**This is not the agreement and not legal advice.** The authoritative text, plus the
data-protection sheet that is its Anhang 2, is in the repository root under
`elster_eric/` — **gitignored on purpose** (§ 14 binds us to confidentiality, the documents
come from an account-gated developer area, and the `personal` remote is a *public*
repository). If `elster_eric/` is missing from your clone, ask Elena for it rather than
guessing at the terms. The copy we hold is complete: the agreement itself, its Anhang 1
of nine third-party open-source licences, and the Anhang 2 data-protection sheet — the
last as extracted text, with the PDF still to be added.

## When any of this binds

**Most of it is dormant today.** ELSTER submission is out of scope for the current
effort — decided 31 August 2026, see the wayfinder map. Nothing here applies until ERiC
is actually integrated and the product distributed.

The plan for when it does apply is issue #63, *Integrate ERiC for optional electronic
filing through ELSTER* — PDF-first stays, transmission is added beside it and only after the
user explicitly confirms.

**Two things bind now:** the confidentiality duty in § 14, and the naming and trademark
limits in § 12 — because they constrain what we write and publish, not what we ship.

## Without ERiC, none of this applies

ERiC exists for one thing: transmitting a return to the Finanzamt electronically. This
product fills in PDF forms and the human files them, so **ERiC is not needed at all** —
and every obligation below except § 12 and § 14 flows from the ERiC licence, so it is
dormant while ERiC is absent. Treat this file as preparation, not as live requirements.

In particular, the § 5 duty to show the end user the data-protection sheet exists
*because of the ERiC licence*. No ERiC, no such duty.

### Artifact boundary for the PDF-only stage

- ERiC binaries, ERiC documentation, ERiC schemas and
  `Vordrucke_<year>_ERiC-<version>.zip` release bundles are stored under the gitignored
  `elster_eric/` directory for the future e-filing workstream only. Do not copy them into
  `KB/`, a public repository, a PDF asset directory or a deployment.
- Do not confuse that ERiC release bundle with the separate BMF-controlled ELSTER page
  `Download der amtlichen Vordrucke`. A final `ESt_<year>.zip` from that page is an
  official-form publication and may be used by the PDF-only product; it is not an ERiC
  binary or runtime dependency merely because the page sits in the developer portal.
- For every official-form package, keep the canonical source page, retrieval date,
  tax year, final/draft status and checksum. Never promote an `Entwurfsstand` as a final
  form.
- Obtain the other instructions and legal sources from official BMF/FMS, Gesetze im
  Internet and BMF handbook or BMF-Schreiben pages, with the same provenance metadata.

Two things that are true regardless:

- **The official form PDFs and their Anleitungen are publicly downloadable** — no
  developer account, no licence. Several are already in `KB/`. The *field
  specifications* in the developer area may come under their own terms, which are not
  this agreement; check what they are issued under before depending on them.
- **The GDPR applies to this product on its own account**, because it processes tax
  data. That is general law. The ERiC licence neither creates nor removes it, and the
  data-lifecycle work in `docs/KNOWN_LIMITATIONS.md` is owed either way.

Who "the end user" is, where it comes up: the person preparing their tax return in this
application — not the developer. The § 5 notices, when they apply, are screens in the
product shown before use, with the acknowledgement persisted.

## The rules

### Naming and trademarks (§ 12) — live now

- The product name and the maker name **must not contain "ELSTER"**. Currently satisfied:
  the packages are `tax-assistant`, `@tax-assistant/shared`.
- The ELSTER word mark and graphic may be used only to tell customers the product is
  *suitable for use with* ELSTER.
- The **ELSTER logo** carries no usage right beyond appearing in the ERiC documentation
  (§ 4). Putting it in our UI, README or slides needs a separate agreement. Do not.

### Confidentiality (§ 14) — live now

Business secrets and internal material obtained from the LfSt stay confidential, and the
duty outlives the contract. This is why `elster_eric/` is gitignored, and it is a standing
reason not to paste ELSTER developer-area material into a public repository, a public
issue, or the submission materials.

### What ERiC may be used for (§ 3) — check before relying on it

ERiC serves **exclusively** for use in connection with the electronic filing of tax
returns and transmission of tax data. That wording is narrower than "a library that
knows the forms".

**Open question, and it matters for the current plan.** Elena wants ELSTER's official
form specifications — field definitions, validation rules, data formats — to get the 33
forms right, while explicitly leaving submission out of scope. Reading the
*documentation* from the developer area is a different act from *using ERiC*, and this
agreement governs ERiC. Before any code depends on ERiC purely for validation in a
PDF-only product, verify that use is within § 3 — ask the LfSt rather than assuming.
Nothing in this file resolves it.

### Before the end user uses the software (§ 5) — when ERiC ships

Two things must be presented, in a suitable way, **before use**:

1. The document **"Allgemeine Informationen zur Umsetzung der datenschutzrechtlichen
   Vorgaben der Artikel 12 bis 14 der Datenschutz-Grundverordnung in der
   Steuerverwaltung"** (Anhang 2, held in `elster_eric/`) — with the ability to read it *and
   to confirm having read it*. A confirmation, not just a link.
2. The exact **Datenschutzhinweis** text the agreement quotes, verbatim — with the
   ability to read it. It states that the software also collects the type of the user's
   operating system and transmits that to the tax administration.

Both are UI requirements with a persisted acknowledgement behind them, so they touch the
data model, not only a screen. Note the second one describes behaviour we would have to
actually implement: ERiC transmits OS information.

### Versions (§ 5) — when ERiC ships

- Use the version the LfSt marks as **"Mindestversion"**. Newer is recommended;
  running older than the minimum is a violation.
- Check the developer area regularly for new versions and updates. The LfSt is not
  obliged to provide any.
- **Never ship an unreleased update.** Field-testing one needs the LfSt's explicit
  consent, given by e-mail or announced on www.elster.de.
- Use ERiC according to its own documentation and the further documentation on the
  ELSTER developer download pages.

### Distribution (§ 4) — read this before adding ERiC to the repository

We may integrate ERiC and the `ericdemo` / `ottodemo` sample code into our own product
and distribute that product, including publicly. We may **not** transfer the usage right
to third parties or sublicense beyond that.

**The `personal` remote is public.** Committing ERiC binaries there would put the library
where anyone can take it independently of our product, which is not obviously the
"einheitliches Produkt" the paragraph permits. Treat adding ERiC to a public repository
as a question to settle, not a routine dependency addition.

Any third-party software we bind into ERiC for our own development is **our** licensing
responsibility (§ 5, last paragraph); we may need our own developer licences.

**Shipping ERiC also means shipping an attribution notice.** Anhang 1 lists nine
open-source components — zlib, OpenSSL, Xerces and JNA, cURL, Haru Free PDF Library,
LibXML2, XMLsec, PCRE2 and the NotoSans font. Apache 2.0 requires reproducing NOTICE
contents; the permissive ones require their copyright notice be carried in binary
distributions; the SIL Open Font License requires the notice and licence with each copy of
the font. PCRE2's binary-package exemption probably spares us its condition, since our
product would include ERiC rather than use PCRE2 itself — worth confirming. Details and
full texts in `elster/eric-anhang-1-lizenzen-dritter.md`.

### RABE (§ 6) — contradicts ADR 0004, so it is effectively closed to us

RABE lets a return reference receipts that **the software maker stores** and ELSTER
fetches on demand. Taking part obliges us to:

- keep that receipt store available 24/7, with weekday maintenance only between 18:00
  and 06:00 for at most four hours, and at most six hours on weekends and nationwide
  holidays;
- answer in the millisecond range;
- follow the current RABE interface specification in full;
- show the end user a specific notice, quoted in the agreement, about receipts being
  fetched by ELSTER and forwarded to the tax administration.

**This is incompatible with [ADR 0004](../adr/0004-documents-are-read-then-discarded.md)**,
which discards the original document after reading and keeps only the file name and
user-confirmed values. RABE requires holding the actual receipts and serving them for
years. So RABE is unavailable to this product unless a new privacy decision replaces
ADR 0004 — and that is a product decision, not a technical one.

### Log files (§ 15) — decides where ERiC may run

- ERiC writes log files locally. They stay with the end user, and may reach the software
  maker only in a support case, with the user's explicit permission.
- **If ERiC runs on our server instead of the user's machine — which is what a web
  application means — the log files are stored on our server by default, and we carry
  the data-protection duties for them.** That is a direct consequence of this product
  being a web app rather than desktop software, and it needs an answer before ERiC is
  integrated.
- Forwarding log files to the tax administration in either scenario requires the end
  user's explicit permission, and we must be able to prove we have it on request.

### Support, cost, liability (§§ 7, 8, 9, 10, 11)

- Once ERiC is integrated, **we provide all support**. The LfSt answers developer
  questions voluntarily and revocably, and its support contact details must not be
  passed to third parties or end users.
- Sending logs to the LfSt for support needs the end user's explicit permission first if
  their personal data is in them.
- All integration, update and support cost is ours. ERiC itself is free of charge.
- Breach lets the LfSt block our Hersteller-ID and stop us using ERiC (§ 9).
- The LfSt's liability is excluded except for breach of official duty, injury to life or
  health, and gross negligence (§ 10).

### Data backup (§ 5) and export control (§ 13)

- Back up data to a reasonable extent, and tell end users that such backups are needed.
- ERiC uses cryptography; complying with import and export rules is our responsibility.

## How to use this file

Read it before any of the following, and say in the change which rule you checked:

- adding ERiC, `ericdemo` or `ottodemo` to the repository or to a dependency manifest;
- writing anything user-facing about ELSTER, or adding an ELSTER name or logo to the UI,
  README, showcase entry or submission materials;
- designing document storage, retention or deletion — see the RABE and ADR 0004 clash;
- deciding where ERiC runs, or how its log files are stored — see § 15;
- publishing to the public `personal` remote anything derived from the developer area.
