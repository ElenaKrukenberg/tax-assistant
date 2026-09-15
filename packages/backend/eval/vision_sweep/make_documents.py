"""Generate the three synthetic test documents the vision sweep reads, plus ground truth.

The first sweep (issue #11) left nothing reproducible: its documents lived on a branch
that no longer exists, so its numbers cannot be re-derived. The JPEGs this writes are
therefore **committed** next to it — regenerating them is a convenience, not the
contract, because the render depends on a system font that differs between machines.
Ground truth is written beside them so a change to a document cannot silently
disagree with the answers the sweep grades against.

Specs are held from #11 so the two tables mean the same thing:

  1. `lohnsteuerbescheinigung.jpg`  A4 at 150 dpi, 1240x1754, ~133 KB, 11 numbered
     lines including `Bruttoarbeitslohn 41.238,76`.
  2. `rechnung-foto.jpg`            phone photo, 3024x3948, ~320 KB, rotated 3.5°,
     JPEG quality 70.
  3. `payslip-degraded.jpg`         623x862, quality 35, blurred, noise, rotated 1.8°
     so row labels and amount columns no longer line up.

    ./venv/bin/python eval/vision_sweep/make_documents.py
"""

import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
DOCS = HERE / "documents"

# No scalable font ships with Pillow, so the render needs a system one. The committed
# JPEGs are the artefact of record precisely because this list resolves differently
# per machine.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in BOLD_CANDIDATES if bold else FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit(
        "no usable TTF found; the committed JPEGs in documents/ are the artefact of "
        "record — regeneration needs one of: " + ", ".join(FONT_CANDIDATES)
    )


def save_at_size(img: Image.Image, path: Path, target_kb: int, quality: int | None) -> None:
    """Write a JPEG, tuning quality to land near target_kb when quality is not pinned."""
    if quality is not None:
        img.save(path, "JPEG", quality=quality, subsampling=2)
        return
    best = None
    for q in range(95, 29, -1):
        img.save(path, "JPEG", quality=q, subsampling=2)
        kb = path.stat().st_size / 1024
        if best is None or abs(kb - target_kb) < abs(best[1] - target_kb):
            best = (q, kb)
        if kb <= target_kb:
            break
    img.save(path, "JPEG", quality=best[0], subsampling=2)


# --------------------------------------------------------------------------- doc 1

# The 11 numbered lines of the Lohnsteuerbescheinigung, as (line no, label, amount).
# Line 3 carries the Bruttoarbeitslohn #11's table quotes, so it is held exactly.
PAYSLIP_LINES = [
    ("3", "Bruttoarbeitslohn einschl. Sachbezüge ohne 9. und 10.", "41.238,76"),
    ("4", "Einbehaltene Lohnsteuer von 3.", "6.412,00"),
    ("5", "Einbehaltener Solidaritätszuschlag von 3.", "0,00"),
    ("6", "Einbehaltene Kirchensteuer des Arbeitnehmers von 3.", "615,78"),
    ("15", "Steuerfreie Arbeitgeberleistungen (Fahrtkosten)", "348,00"),
    ("16a", "Steuerfreier Arbeitslohn nach Doppelbesteuerungsabkommen", "0,00"),
    ("22a", "Arbeitgeberanteil zur gesetzlichen Rentenversicherung", "3.835,20"),
    ("23a", "Arbeitnehmerbeitrag zur gesetzlichen Rentenversicherung", "3.835,20"),
    ("25", "Arbeitnehmerbeitrag zur gesetzlichen Krankenversicherung", "3.382,58"),
    ("26", "Arbeitnehmerbeitrag zur Pflegeversicherung", "710,86"),
    ("27", "Beiträge zur Arbeitslosenversicherung", "535,10"),
]

PAYSLIP_TRUTH = {
    "document_type": "lohnsteuerbescheinigung",
    "tax_year": 2025,
    "employer_name": "Möbelwerkstatt Krämer GmbH & Co. KG",
    "employee_name": "Anna Beispiel",
    "employment_period_start": "2025-01-01",
    "employment_period_end": "2025-12-31",
    "tax_class": 1,
    "etin": "AB1234567890",
    "gross_salary_eur": 41238.76,
    "income_tax_eur": 6412.00,
    "solidarity_surcharge_eur": 0.00,
    "church_tax_eur": 615.78,
    "pension_insurance_employee_eur": 3835.20,
    "health_insurance_employee_eur": 3382.58,
    "care_insurance_employee_eur": 710.86,
    "unemployment_insurance_eur": 535.10,
}


def make_payslip(clean_only: bool = False, period: str = "01.01.2025 – 31.12.2025") -> Image.Image:
    """A4 at 150 dpi. 1240x1754 is 210x297 mm at 150 dpi, which is what #11 rendered."""
    w, h = 1240, 1754
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    f9, f11, f13, f16 = font(17), font(20), font(23), font(29, bold=True)

    d.text((70, 70), "Ausdruck der elektronischen Lohnsteuerbescheinigung", font=f16, fill="black")
    d.text((70, 108), "für 2025", font=f13, fill="black")
    d.line((70, 146, w - 70, 146), fill="black", width=2)

    y = 176
    for label, value in [
        ("Arbeitgeber", PAYSLIP_TRUTH["employer_name"]),
        ("Steuernummer des Arbeitgebers", "143/815/49302"),
        ("eTIN", PAYSLIP_TRUTH["etin"]),
        ("Arbeitnehmer", PAYSLIP_TRUTH["employee_name"]),
        ("Geburtsdatum", "14.03.1989"),
        ("Bescheinigungszeitraum", period),
        ("Steuerklasse / Faktor", "1"),
        ("Zahl der Kinderfreibeträge", "0"),
        ("Kirchensteuermerkmal", "rk"),
    ]:
        d.text((70, y), label, font=f11, fill="black")
        d.text((520, y), value, font=f11, fill="black")
        y += 34

    y += 22
    d.line((70, y, w - 70, y), fill="black", width=1)
    y += 16
    d.text((70, y), "Nr.", font=f11, fill="black")
    d.text((130, y), "Bezeichnung", font=f11, fill="black")
    d.text((980, y), "Betrag in EUR", font=f11, fill="black")
    y += 30
    d.line((70, y, w - 70, y), fill="black", width=1)
    y += 18

    for no, label, amount in PAYSLIP_LINES:
        d.text((70, y), no, font=f11, fill="black")
        d.text((130, y), label, font=f9, fill="black")
        # Right-aligned amounts, as on the real form: the column edge is what a
        # degraded scan destroys.
        tw = d.textlength(amount, font=f11)
        d.text((1170 - tw, y), amount, font=f11, fill="black")
        y += 40

    y += 20
    d.line((70, y, w - 70, y), fill="black", width=1)
    d.text(
        (70, y + 24),
        "Diese Bescheinigung wurde elektronisch an die Finanzverwaltung übermittelt.",
        font=f9,
        fill="black",
    )
    d.text((70, y + 52), "Übermittelt am 12.02.2026 · Transferticket 2026021200041238", font=f9, fill="black")
    return img


# --------------------------------------------------------------------------- doc 2

INVOICE_TRUTH = {
    "document_type": "rechnung",
    "invoice_number": "2025-0417",
    "invoice_date": "2025-09-08",
    "supplier_name": "Bürotechnik Hoffmann e.K.",
    "customer_name": "Anna Beispiel",
    "net_total_eur": 1094.12,
    "vat_rate_percent": 19.0,
    "vat_amount_eur": 207.88,
    "gross_total_eur": 1302.00,
    "line_items": [
        {"description": "Schreibtisch Modell Ergoline 160 cm", "quantity": 1, "unit_price_eur": 689.00},
        {"description": "Bürostuhl Drehstuhl Aristo, schwarz", "quantity": 1, "unit_price_eur": 312.61},
        {"description": "Monitorarm Duo, Klemmbefestigung", "quantity": 2, "unit_price_eur": 46.25},
    ],
}


def make_invoice() -> Image.Image:
    """Rendered large, then rotated 3.5° and left at 3024x3948 — a phone photo shape."""
    w, h = 3024, 3948
    img = Image.new("RGB", (w, h), (243, 241, 236))
    d = ImageDraw.Draw(img)
    f = font(46)
    fs = font(38)
    fb = font(58, bold=True)
    fh = font(84, bold=True)

    # A paper rectangle inside the frame, so the rotation shows a page edge rather
    # than a rotated full-bleed image.
    d.rectangle((150, 190, w - 150, h - 190), fill=(252, 252, 250), outline=(206, 202, 194), width=4)

    d.text((260, 300), INVOICE_TRUTH["supplier_name"], font=fb, fill="black")
    d.text((260, 380), "Gerberstraße 12 · 76133 Karlsruhe", font=fs, fill=(60, 60, 60))
    d.text((260, 434), "USt-IdNr. DE812345678", font=fs, fill=(60, 60, 60))

    d.text((260, 620), "RECHNUNG", font=fh, fill="black")
    d.text((260, 740), f"Rechnungsnummer  {INVOICE_TRUTH['invoice_number']}", font=f, fill="black")
    d.text((260, 806), "Rechnungsdatum  08.09.2025", font=f, fill="black")
    d.text((260, 872), "Leistungsdatum  05.09.2025", font=f, fill="black")

    d.text((1700, 740), "Rechnungsempfänger", font=fs, fill=(60, 60, 60))
    d.text((1700, 800), INVOICE_TRUTH["customer_name"], font=f, fill="black")
    d.text((1700, 866), "Lindenweg 4", font=f, fill="black")
    d.text((1700, 932), "76185 Karlsruhe", font=f, fill="black")

    y = 1150
    d.line((260, y, w - 260, y), fill="black", width=3)
    y += 24
    for x, t in ((260, "Pos."), (420, "Bezeichnung"), (1980, "Menge"), (2200, "Einzelpreis"), (2540, "Gesamt")):
        d.text((x, y), t, font=fs, fill="black")
    y += 70
    d.line((260, y, w - 260, y), fill="black", width=3)
    y += 40

    for i, item in enumerate(INVOICE_TRUTH["line_items"], start=1):
        total = item["quantity"] * item["unit_price_eur"]
        d.text((260, y), str(i), font=f, fill="black")
        d.text((420, y), item["description"], font=f, fill="black")
        d.text((1980, y), str(item["quantity"]), font=f, fill="black")
        d.text((2200, y), f"{item['unit_price_eur']:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), font=f, fill="black")
        d.text((2540, y), f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), font=f, fill="black")
        y += 84

    y += 40
    d.line((1900, y, w - 260, y), fill="black", width=2)
    y += 30
    for label, amount, bold in (
        ("Nettobetrag", "1.094,12", False),
        ("zzgl. 19 % USt.", "207,88", False),
        ("Gesamtbetrag", "1.302,00", True),
    ):
        d.text((1900, y), label, font=fb if bold else f, fill="black")
        d.text((2540, y), amount, font=fb if bold else f, fill="black")
        y += 90

    d.text((260, h - 640), "Zahlbar innerhalb von 14 Tagen ohne Abzug.", font=fs, fill="black")
    d.text((260, h - 570), "IBAN DE44 6605 0101 0009 1234 56 · Sparkasse Karlsruhe", font=fs, fill=(60, 60, 60))

    # A phone photo is never square-on: 3.5° with an expand-then-crop back to size,
    # so the pixel dimensions stay the ones #11 measured.
    rot = img.rotate(3.5, resample=Image.BICUBIC, expand=True, fillcolor=(228, 226, 220))
    left = (rot.width - w) // 2
    top = (rot.height - h) // 2
    return rot.crop((left, top, left + w, top + h))


# --------------------------------------------------------------------------- doc 3


def make_degraded(payslip: Image.Image) -> Image.Image:
    """The same payslip, wrecked: small, blurred, noisy, and 1.8° off-square.

    The rotation is the point — at 623x862 a 1.8° skew is enough that a row label on
    the left no longer sits on the same pixel row as its amount on the right, which is
    what made #11's models move `615,78` out of the church-tax row.
    """
    small = payslip.resize((623, 862), Image.LANCZOS)
    small = small.rotate(1.8, resample=Image.BICUBIC, expand=False, fillcolor="white")
    small = small.filter(ImageFilter.GaussianBlur(radius=0.9))
    rng = np.random.default_rng(20260901)
    arr = np.asarray(small).astype(np.int16)
    arr += rng.normal(0, 11, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def main() -> None:
    random.seed(20260901)
    DOCS.mkdir(parents=True, exist_ok=True)

    payslip = make_payslip()
    save_at_size(payslip, DOCS / "lohnsteuerbescheinigung.jpg", target_kb=133, quality=None)

    invoice = make_invoice()
    save_at_size(invoice, DOCS / "rechnung-foto.jpg", target_kb=320, quality=70)

    # A part-year payslip, and the reason it exists is one line of it: the period
    # reads 01.02.2025 - 30.09.2025, where the day and the month of the start differ
    # and both are 12 or under. On the full-year document (01.01. - 31.12.) a
    # day/month swap is either invisible (01.01.) or impossible (31.12., no such
    # month), so #11's finding that `claude-haiku-4.5` inverted a German date could
    # not be re-tested at all - the risk was untested rather than cleared.
    #
    # It is also the case the product needs to get right most: the employment period
    # is the only thing document intake reads off a Lohnsteuerbescheinigung, and
    # reading February as the first of the ninth month turns eight months of
    # employment into one (`services/documents/mapping.py`).
    part_year = make_payslip(period="01.02.2025 – 30.09.2025")
    save_at_size(part_year, DOCS / "payslip-part-year.jpg", target_kb=133, quality=None)

    part_year_truth = dict(PAYSLIP_TRUTH)
    part_year_truth["employment_period_start"] = "2025-02-01"
    part_year_truth["employment_period_end"] = "2025-09-30"

    degraded = make_degraded(payslip)
    save_at_size(degraded, DOCS / "payslip-degraded.jpg", target_kb=0, quality=35)

    degraded_truth = dict(PAYSLIP_TRUTH)
    degraded_truth["document_type"] = "lohnsteuerbescheinigung"

    (DOCS / "ground-truth.json").write_text(
        json.dumps(
            {
                "lohnsteuerbescheinigung.jpg": PAYSLIP_TRUTH,
                "rechnung-foto.jpg": INVOICE_TRUTH,
                # Same document, same truth: the degraded scan is graded against the
                # clean one's values, which is what makes the two rows comparable.
                "payslip-degraded.jpg": degraded_truth,
                "payslip-part-year.jpg": part_year_truth,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    for p in sorted(DOCS.glob("*.jpg")):
        with Image.open(p) as im:
            print(f"{p.name:32s} {im.width}x{im.height}  {p.stat().st_size / 1024:6.1f} KB")


if __name__ == "__main__":
    main()
