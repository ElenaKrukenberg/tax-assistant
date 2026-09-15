# The system may assume a value, but never silently and never to its own advantage

When the user cannot answer, the system is allowed to fill a field with an
assumption — recorded as such, shown as such everywhere the figure appears, and
confirmed before any report is generated. Every value in a case therefore carries
its provenance: an answer, a document, or an assumption.

This started as a discovery rather than a design. `calculations.py` already
assumed six values through Pydantic defaults, invisibly: `own_car=False`,
`price_is_net=False`, `is_digital=False`, `useful_life_years=3`,
`professional_share_pct=100`, and a telecom `months=12`. Some of those change the
figure substantially — assuming no car applies the 4,500 € cap — and none of them
were visible to the user. A tool that produces tax figures cannot have invisible
assumptions in it, so the fix was not to remove them but to make them a first-class
part of the case.

Which fields may be assumed is a judgement made once, in `fields.py`, and the rule
is that an assumption may only ever be the cautious reading. Four qualify: one
employer, a receipt showing a gross price, an item that is not digital, and a
three-year useful life. Two deliberately do not, although the calculator has a
default for both: `professional_share_pct` at 100 and the telecom `months` at 12
both *enlarge* the claim — a laptop used for nothing but work, a phone line used
professionally all year — and a figure in a tax return must not grow because
nobody asked. Those two are questions, always.

The Pydantic defaults stay where they are as a safety net against a missing key,
and the case layer must never rely on them: it fills every field explicitly, with
an assumption where one is defensible and a question where it is not. An
assumption that reaches the report unconfirmed is a defect, not a shortcut.
