import type { TaxCaseDto } from "./types";

// A coherent, deliberately imperfect Tax Case for UI development. It contains one
// seeded contradiction (220 total working days vs 145 commute + 96 home-office days)
// so the Reviewer screen has a real blocking Finding to display.
export const TAX_CASE_2025_FIXTURE: TaxCaseDto = {
  id: "2025",
  taxYear: 2025,
  status: "needs_user_input",
  progress: 62,
  expenseTotalEur: 2109.9,
  lastTouchedIso: "2026-08-19T12:00:00+02:00",
  pauschbetragEur: 1230,
  profile: [
    {
      id: "profile.employed_months",
      value: "12",
      provenance: "document",
      provenanceLabel: "Lohnsteuerbescheinigung 2025",
    },
    {
      id: "profile.employer_count",
      value: "1",
      provenance: "document",
      provenanceLabel: "Lohnsteuerbescheinigung 2025",
    },
    {
      id: "profile.working_days_total",
      value: "220",
      provenance: "answer",
      provenanceLabel: "interview answer",
    },
    {
      id: "profile.works_remotely",
      value: "yes",
      provenance: "answer",
      provenanceLabel: "interview answer",
    },
    {
      id: "commute.commuting_days",
      value: "145",
      provenance: "answer",
      provenanceLabel: "interview answer",
    },
    {
      id: "commute.distance_km",
      value: "27",
      provenance: "answer",
      provenanceLabel: "interview answer",
    },
    {
      id: "homeoffice.homeoffice_days",
      value: "96",
      provenance: "assumed",
      provenanceLabel: "assumed, waiting for confirmation",
    },
    {
      id: "homeoffice.other_workplace_available",
      value: "yes",
      provenance: "answer",
      provenanceLabel: "interview answer",
    },
  ],
  expenses: [
    {
      id: "entfernungspauschale",
      category: "entfernungspauschale",
      categoryLabel: "Entfernungspauschale",
      amountEur: 1255.7,
      evidence: [
        { label: "145 commuting days, interview answer", provenance: "answer" },
        { label: "27 km one-way distance, interview answer", provenance: "answer" },
      ],
      formLine: "Zeilen 27–34 (days: 29; distance: 30, of which by car: 31)",
      status: "confirmed",
      formula: "(first 20 km × 0.30 EUR + remaining km × 0.38 EUR) × commuting days",
      substitutedValues: "(20 km × 0.30 EUR + 7 km × 0.38 EUR) × 145 = 1,255.70 EUR",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeilen 27–50",
        excerpt:
          "Die Entfernungspauschale beträgt 0,30 € für jeden vollen Entfernungskilometer der ersten 20 km und 0,38 € für jeden weiteren vollen Entfernungskilometer.",
      },
    },
    {
      id: "homeoffice_tagespauschale",
      category: "homeoffice_tagespauschale",
      categoryLabel: "Homeoffice-Tagespauschale",
      amountEur: 576,
      evidence: [{ label: "96 home-office days, awaiting confirmation", provenance: "assumed" }],
      formLine: "Zeile 58 (another workplace was available)",
      status: "flagged",
      formula: "6 EUR × home-office days (max. 210 days / 1,260 EUR)",
      substitutedValues: "6.00 EUR × 96 = 576.00 EUR",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeilen 58–59",
        excerpt:
          "Die Tagespauschale ist auf 1.260 € jährlich begrenzt und kann an maximal 210 Tagen in Anspruch genommen werden.",
      },
    },
    {
      id: "arbeitsmittel_1",
      category: "arbeitsmittel",
      categoryLabel: "Arbeitsmittel",
      amountEur: 89.9,
      evidence: [{ label: "Schreibtischlampe, interview answer", provenance: "answer" }],
      formLine: "Zeilen 54–56 (total in 56)",
      status: "confirmed",
      formula: "gross price × professional share, deducted in full below the 800 EUR net threshold",
      substitutedValues: "89.90 EUR × 100% = 89.90 EUR (bought in month 2)",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeilen 54–56",
        excerpt:
          "Arbeitsmittel, die höchstens 800 € ohne Umsatzsteuer gekostet haben, können im Jahr der Anschaffung voll abgesetzt werden.",
      },
    },
    {
      id: "arbeitsmittel_2",
      category: "arbeitsmittel",
      categoryLabel: "Arbeitsmittel",
      amountEur: 64.3,
      evidence: [{ label: "Rechnung Notebook-Tasche.pdf", provenance: "document" }],
      formLine: "Zeilen 54–56 (total in 56)",
      status: "confirmed",
      formula: "gross price × professional share, deducted in full below the 800 EUR net threshold",
      substitutedValues: "64.30 EUR × 100% = 64.30 EUR (bought in month 4)",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeilen 54–56",
        excerpt:
          "Arbeitsmittel, die höchstens 800 € ohne Umsatzsteuer gekostet haben, können im Jahr der Anschaffung voll abgesetzt werden.",
      },
    },
    {
      id: "arbeitsmittel_3",
      category: "arbeitsmittel",
      categoryLabel: "Arbeitsmittel",
      amountEur: 24.0,
      evidence: [{ label: "Fachbuch, interview answer", provenance: "answer" }],
      formLine: "Zeilen 54–56 (total in 56)",
      status: "confirmed",
      formula: "gross price × professional share, deducted in full below the 800 EUR net threshold",
      substitutedValues: "24.00 EUR × 100% = 24.00 EUR (bought in month 9)",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeilen 54–56",
        excerpt:
          "Arbeitsmittel, die höchstens 800 € ohne Umsatzsteuer gekostet haben, können im Jahr der Anschaffung voll abgesetzt werden.",
      },
    },
    {
      id: "fortbildungskosten",
      category: "fortbildungskosten",
      categoryLabel: "Fortbildungskosten",
      amountEur: 100,
      evidence: [{ label: "100 EUR course fee, interview answer", provenance: "answer" }],
      formLine: "Zeile 60",
      status: "draft",
      formula: "course fees + eligible travel + materials − reimbursements",
      substitutedValues: "100.00 EUR course fee = 100.00 EUR",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeile 60",
        excerpt:
          "Aufwendungen für die Fortbildung in einem bereits erlernten Beruf können als Werbungskosten abziehbar sein.",
      },
    },
  ],
  gapCandidates: [
    {
      id: "bewerbungskosten",
      category: "bewerbungskosten",
      categoryLabel: "Bewerbungskosten",
      officialSource: {
        title: "Anleitung zur Anlage N 2025",
        reference: "Zeilen 61–64",
        excerpt:
          "Wenn Sie im Jahr 2025 eine Arbeitsstelle gesucht haben, können nicht erstattete Bewerbungskosten Werbungskosten sein.",
      },
    },
  ],
  findings: [
    {
      id: "working_day_contradiction",
      severity: "blocking",
      affectedExpenseId: "homeoffice_tagespauschale",
    },
    {
      id: "missing_fortbildung_document",
      severity: "warning",
      affectedExpenseId: "fortbildungskosten",
    },
    {
      id: "distance_rounded_down",
      severity: "suggestion",
      affectedExpenseId: "entfernungspauschale",
    },
  ],
  documents: [
    {
      id: "lohnsteuerbescheinigung",
      name: "Lohnsteuerbescheinigung 2025.pdf",
      sizeLabel: "218 KB",
      state: "confirmed",
      confirmedSummary:
        "Gross salary 58,400.00 EUR · Wage tax 11,238.00 EUR · Nordlicht Systeme GmbH",
    },
    {
      id: "notebook_bag",
      name: "Rechnung Notebook-Tasche.pdf",
      sizeLabel: "96 KB",
      state: "awaiting",
      fields: [
        { id: "vendor", value: "Bürowelt Hamburg GmbH" },
        { id: "date", value: "14.04.2025" },
        { id: "net", value: "64.30 EUR" },
        { id: "category", value: "Arbeitsmittel" },
      ],
    },
    {
      // An invoice, not a photo of the ticket itself: a monthly card shows no
      // price, and actual transport costs only matter at all when they exceed
      // the distance allowance the calculator compares them against.
      id: "public_transport",
      name: "HVV Rechnung Deutschlandticket Januar.pdf",
      sizeLabel: "84 KB",
      state: "reading",
      readingStep: "Extracting fields (page 1 of 1)",
    },
    {
      id: "training",
      name: "Fortbildung Rechnung.pdf",
      sizeLabel: "310 KB",
      state: "uploading",
      progress: 46,
    },
  ],
  answeredQuestions: [
    { id: "profile.working_days_total" },
    { id: "commute.commuting_days" },
    { id: "commute.distance_km" },
    { id: "commute.own_car" },
  ],
};

export const TAX_CASE_FIXTURES: TaxCaseDto[] = [TAX_CASE_2025_FIXTURE];
