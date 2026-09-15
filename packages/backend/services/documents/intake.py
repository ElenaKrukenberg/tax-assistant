"""The file checks, before anything is sent anywhere.

Three questions, all answerable without a model: is this one of the two file formats
intake supports, is it small enough to send, and - for a PDF - is it short enough.
The type is decided by the bytes, not by what the client said it was: a request
header is a claim, and the whole point of checking is that a claim may be wrong.

Nothing here writes to disk. That is not a comment, it is the requirement ADR 0004
rests on, and it is why the route hands us `bytes` from the request body rather than
an `UploadFile`: Starlette's multipart parser spools a part over 1 MiB into a real
temporary file (`MultiPartParser.max_file_size`), so a phone photo of a payslip would
have been written to /tmp on the way in.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# 10 MiB. A photographed A4 page off a modern phone is 2 to 5 MB, so this is roomy
# enough for a bad camera and small enough that the request cannot be used to fill
# memory. The route enforces it while reading, not after: a limit checked once the
# body is in hand has already been exceeded.
MAX_BYTES = 10 * 1024 * 1024

# Pages, not bytes, for a PDF: each page is an image to the model and is billed as
# one (~1,500 to 3,000 tokens). A Lohnsteuerbescheinigung is one page and an invoice
# rarely more than three; five leaves room without inviting a scanned brochure.
MAX_PDF_PAGES = 5


class FileFormat(str, Enum):
    jpeg = "image/jpeg"
    png = "image/png"
    pdf = "application/pdf"


class Rejected(ValueError):
    """The upload cannot be read, with a reason the interface can show as it is."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CheckedUpload:
    """An upload that passed the checks. Still only in memory."""

    file_name: str
    file_format: FileFormat
    size_bytes: int
    pages: int  # 1 for an image


# Magic numbers. JPEG and PNG are unambiguous in their first bytes; a PDF must start
# with %PDF-, and the specification allows leading junk before it, which is exactly
# the kind of leniency a check should not copy.
_SIGNATURES: tuple[tuple[bytes, FileFormat], ...] = (
    (b"\xff\xd8\xff", FileFormat.jpeg),
    (b"\x89PNG\r\n\x1a\n", FileFormat.png),
    (b"%PDF-", FileFormat.pdf),
)


def sniff(data: bytes) -> FileFormat | None:
    """The format the bytes actually are, or None for anything else."""
    for signature, file_format in _SIGNATURES:
        if data.startswith(signature):
            return file_format
    return None


def pdf_pages(data: bytes) -> int:
    """How many pages the PDF has, or a rejection if it cannot be opened.

    pypdf is already a dependency (`services/anlage_n_pdf.py` fills the official
    form with it), so this costs no new package. An encrypted PDF is refused rather
    than half-read: the model would receive pages nobody could check.
    """
    import io

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise Rejected(
                "pdf_encrypted",
                "This PDF is password protected. Remove the protection, or upload a "
                "photo of the page instead.",
            )
        return len(reader.pages)
    except Rejected:
        raise
    except (PdfReadError, Exception) as exc:  # noqa: BLE001 - any failure is the same answer
        raise Rejected("pdf_unreadable", f"This PDF could not be opened: {exc}") from exc


def check(data: bytes, *, file_name: str, declared_format: str | None = None) -> CheckedUpload:
    """Everything that has to be true before an upload is sent to a model.

    `declared_format` is only compared, never trusted: a mismatch between what the
    client said and what the bytes are is worth refusing, because it is either a
    misconfigured client or someone probing.
    """
    if not data:
        raise Rejected("empty", "The upload was empty.")

    if len(data) > MAX_BYTES:
        raise Rejected(
            "too_large",
            f"The file is {len(data) / 1024 / 1024:.1f} MB. The limit is "
            f"{MAX_BYTES // 1024 // 1024} MB - a photo of one page is well under it.",
        )

    file_format = sniff(data)
    if file_format is None:
        raise Rejected(
            "unsupported_format",
            "Only JPEG, PNG and PDF can be read. A screenshot of the document is fine.",
        )

    if declared_format and declared_format.split(";")[0].strip() != file_format.value:
        raise Rejected(
            "format_mismatch",
            f"The upload says it is {declared_format} but its content is "
            f"{file_format.value}.",
        )

    pages = 1
    if file_format is FileFormat.pdf:
        pages = pdf_pages(data)
        if pages == 0:
            raise Rejected("pdf_unreadable", "This PDF has no pages.")
        if pages > MAX_PDF_PAGES:
            raise Rejected(
                "too_many_pages",
                f"This PDF has {pages} pages and the limit is {MAX_PDF_PAGES}. Upload "
                "the pages that carry the figures.",
            )

    return CheckedUpload(
        file_name=file_name.strip() or "document",
        file_format=file_format,
        size_bytes=len(data),
        pages=pages,
    )
