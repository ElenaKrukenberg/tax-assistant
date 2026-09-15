"""What may be sent to an external model at all, and what it is.

The minimum half of issue #85, and it is worth being exact about what this can and
cannot promise. The user picks the document type before uploading, so what this
module checks is the *declared* type: a medical bill mistakenly declared a Rechnung
still reaches the model before anything notices, because noticing would require
reading it, which is the very thing being gated. Local recognition would change
that and there is none.

So the guarantee is narrow and worth stating in those terms: exactly two kinds of
document may leave this machine, the user is told so before uploading, and every
call carries Zero Data Retention (`core/llm.py`). Actual classification of content
is not claimed.
"""

from __future__ import annotations

from enum import Enum


class DocumentKind(str, Enum):
    """The document types intake supports. Nothing else is sent anywhere."""

    lohnsteuerbescheinigung = "lohnsteuerbescheinigung"
    rechnung = "rechnung"


class Sensitivity(str, Enum):
    tax_document = "tax_document"
    # Art. 9 GDPR: not because the product asks for it, but because the document
    # carries it whether or not anybody wants it to.
    tax_document_special_category = "tax_document_special_category"


# A Lohnsteuerbescheinigung has a Kirchensteuer line, and the amount withheld says
# whether the person belongs to a church that levies it - religious belief, in the
# Art. 9 sense, printed on the form. The image is sent whole, so the model sees that
# line; what this project can do about it is not extract it, not store it, and not
# route the document to a provider that keeps the request. All three are done, and
# none of them is the same as the model not having seen it.
SENSITIVITY: dict[DocumentKind, Sensitivity] = {
    DocumentKind.lohnsteuerbescheinigung: Sensitivity.tax_document_special_category,
    DocumentKind.rechnung: Sensitivity.tax_document,
}


def may_be_sent_to_a_model(kind: str) -> bool:
    """Whether a document declared as `kind` may be sent to an external model.

    An allowlist rather than a denylist: a type nobody has thought about is refused,
    which is the only default that stays safe as the product grows.
    """
    return kind in {k.value for k in DocumentKind}
