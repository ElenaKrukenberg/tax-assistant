---
title: "Validation rules — plausibility checks for Anlage N entries (tax year 2025)"
source_type: curated
form_id: anlage_n
tax_year: 2025
source_id: curated-validation-rules
retrieved: 2026-07-24
topics: [validation]
based_on: [lsth-2025-par-9-werbungskosten, estg-09a-pauschbetraege, lsth-2025-anhang-19-i-ha-usliches-arbeitszimmer, lsth-2025-tabellarische-uebersicht-betraege]
---

# Validation rules — plausibility checks for Anlage N (2025)

Curated rules the validation tool applies to user input. Each rule has an ID, the check, and the explanation shown to the user when it fires. These are plausibility limits, not legal advice; hard legal caps cite their basis.

## Calendar / working-days consistency

| ID | Rule | Explanation for the user |
|---|---|---|
| V01 | working_days ≤ 366 − weekends − public holidays ≈ **max. 230** (typical full-time year: 220–230) | A year has only ~230 possible working days after weekends, holidays and typical vacation; higher values need justification (e.g. 6-day week) |
| V02 | homeoffice_days + commute_days ≤ working_days | A day is either a home-office day or a commute day; the same day cannot be counted twice |
| V03 | homeoffice_days ≤ **210** | The Homeoffice-Pauschale is capped at 1 260 €/year = 210 days × 6 € |
| V04 | vacation + sick days not counted as working days | Entfernungspauschale and Homeoffice-Pauschale only apply to days actually worked |

## Amount caps (hard legal limits, 2025)

| ID | Rule | Basis |
|---|---|---|
| V10 | Homeoffice-Pauschale ≤ 1 260 €/year (6 €/day) | § 4 Abs. 5 Nr. 6c EStG |
| V11 | Entfernungspauschale: 0,30 €/km for km 1–20, 0,38 €/km from km 21; car-independent cap 4 500 €/year unless own/company car used | § 9 Abs. 1 Nr. 4 EStG |
| V12 | Doppelte Haushaltsführung: rent ≤ 1 000 €/month (Inland) | § 9 Abs. 1 Nr. 5 EStG |
| V13 | Verpflegungsmehraufwand: 14 € (partial/travel day) / 28 € (full 24 h day) only | § 9 Abs. 4a EStG |
| V14 | Telefon/Internet without receipts: 20 % of bill, max. 20 €/month (240 €/year) | H 9.1 LStH |
| V15 | Arbeitsmittel ≤ 800 € net → immediate deduction; > 800 € → AfA over useful life | § 9 Abs. 1 Nr. 6 EStG, R 9.12 LStR |
| V16 | Kontoführungspauschale without receipts: 16 €/year | H 9.1 LStH (Vereinfachung) |

## Cross-checks / plausibility

| ID | Rule | Explanation |
|---|---|---|
| V20 | Total Werbungskosten > 1 230 €? If not → itemising brings no benefit | Arbeitnehmer-Pauschbetrag of 1 230 € (§ 9a EStG) is granted automatically |
| V21 | commute_km one-way distance, not round trip | Entfernungspauschale counts the one-way distance only |
| V22 | Homeoffice-Pauschale and Entfernungspauschale must not be claimed for the same day | Mutually exclusive per day (V02); exception: Arbeitszimmer is a different regime |
| V23 | Arbeitszimmer actual costs XOR Homeoffice-Pauschale — not both | Two alternative regimes for work at home |
| V24 | Umzugskosten claimed → move must be job-related (new job, transfer, ≥ 1 h daily commute saved) | Private moves are not deductible |
| V25 | Fortbildung costs unusually high (> ~5 000 €) → ask for details | Plausible for MBA/certification, but worth confirming context |
| V26 | Expense date must fall in tax year 2025 | Zufluss/Abfluss principle (§ 11 EStG) |

## Behaviour when a rule fires

1. Never silently correct the user's number — explain **which rule** fired and **why** (cite the table above).
2. Distinguish hard caps (V10–V16: legal limits, the tool must clamp/flag) from plausibility warnings (V01–V04, V20–V26: ask the user to confirm or adjust).
3. If the user insists on an implausible value, keep it but add a warning to the response.
