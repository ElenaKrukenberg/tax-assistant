---
title: "Expense classification — item to Werbungskosten category (Anlage N, tax year 2025)"
source_type: curated
form_id: anlage_n
tax_year: 2025
source_id: curated-expense-classification
retrieved: 2026-07-24
topics: [expense_classification, berufsverbaende]
based_on: [lsth-2025-par-9-werbungskosten, 055-anleitung-anlage-n-2025]
---

# Expense classification — item → Werbungskosten category (Anlage N, 2025)

Curated mapping table: everyday items and expenses → the Werbungskosten category they belong to on Anlage N. Use for classifying a user's expense before calculation or checklist. Legal basis: § 9 EStG; details per category in the referenced official documents.

## Classification table

| Item / expense | Category (topic) | Notes |
|---|---|---|
| Laptop, PC, monitor, keyboard | Arbeitsmittel | ≤ 800 € net: deduct fully in purchase year (GWG); > 800 € net: depreciate over useful life (AfA) |
| Desk, office chair, desk lamp | Arbeitsmittel | Same 800 € GWG rule; only if used ≥ 90 % professionally, otherwise split |
| Smartphone (device) | Arbeitsmittel | Professional share; 800 € GWG rule applies |
| Phone / internet monthly bill | telefon_internet | Professional share; without receipts: 20 % of bill, max. 20 €/month (H 9.1 LStH) |
| Software licence, cloud subscription (e.g. IDE, Office) | Arbeitsmittel | Professional use share |
| ChatGPT Plus / AI subscriptions | Arbeitsmittel or Fortbildung | Arbeitsmittel if used as work tool; Fortbildung if part of structured learning — ask user for context |
| Textbooks, Fachliteratur, professional journals | Arbeitsmittel (Fachliteratur) | Title/topic must be clearly professional |
| Online course, certification exam, seminar | Fortbildung | Includes course fees + travel to venue |
| Language course | Fortbildung | Only if job-related (e.g. German for work in Germany) — check context |
| Commute to the regular workplace | entfernungspauschale | 0,30 €/km (km 1–20), 0,38 €/km (from km 21), one-way distance per working day |
| Public transport ticket (commute) | entfernungspauschale | Actual ticket cost deductible if higher than the distance allowance for the year |
| Business trip (train, flight, hotel) | reisekosten | Actual costs; meals via Verpflegungspauschale (14 € / 28 €) |
| Meals on business trips | reisekosten | Only flat rates (14 € partial day / 28 € full day), no receipts needed |
| Second flat near workplace | doppelte_haushaltsfuehrung | Rent max. 1 000 €/month (Inland); weekly family trips home 0,38 €/km |
| Job-related move (new job, transfer) | umzugskosten | Actual costs or Umzugskostenpauschale (rates: see BMF/Anhang 29) |
| Application costs (printing, photos, postage, travel to interview) | bewerbungskosten | Deductible even without job offer; estimates accepted if plausible |
| Work clothing (safety shoes, lab coat, uniform) | arbeitskleidung | Only *typische Berufskleidung*; ordinary suits/clothes are NOT deductible |
| Cleaning of work clothing | arbeitskleidung | Deductible for typische Berufskleidung, incl. home laundry (estimated share) |
| Union membership fee (Gewerkschaft) | berufsverbaende | Fully deductible (§ 9 Abs. 1 Nr. 3 EStG) |
| Professional association fee | berufsverbaende | Fully deductible |
| Home office days (no separate room) | homeoffice_pauschale | 6 €/day, max. 1 260 €/year; cannot combine with Entfernungspauschale for the same day |
| Separate room used only for work | arbeitszimmer | Either actual costs (room = Mittelpunkt of work) or the 1 260 € Jahrespauschale |
| Account fee (Kontoführung) | Arbeitsmittel/other | Flat 16 €/year accepted without receipts |

## Not deductible (common misconceptions)

| Item | Why not |
|---|---|
| Ordinary clothing (suit, shoes) for the office | Not *typische Berufskleidung* — private use possible |
| Meals at the regular workplace | Private living costs; only business-trip flat rates count |
| Commute by employer-paid Jobticket (tax-free) | Tax-free employer benefits reduce the deductible amount |
| Fines (parking, speeding) on business trips | Never deductible |
| Home office furniture used mainly privately | Only the professional-use share of Arbeitsmittel counts |

## Decision hints for the assistant

1. If the item could be both Arbeitsmittel and Fortbildung → ask what it is used for.
2. If professional share is unclear (phone, internet, mixed-use devices) → ask for usage estimate; default to the simplified flat rules where they exist.
3. If the expense belongs to another form (e.g. donations → Sonderausgaben, household services → § 35a) → out of scope for Anlage N; say so explicitly.
