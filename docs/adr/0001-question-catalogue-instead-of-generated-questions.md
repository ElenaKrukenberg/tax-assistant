# Interview questions come from a catalogue, not from the model

The Interviewer decides *which* question to ask next and *when to stop asking*.
The wording of each question, the type of answer it accepts and its translations
all come from a fixed catalogue in code. The model writes exactly one thing: the
sentence that introduces the question — "Because you work remotely, let's check
the Homeoffice-Pauschale."

Letting the model write the questions themselves would have given more natural
phrasing at the cost of everything the project is judged on: answers would arrive
as prose needing a second call to parse, translations could not be prepared ahead
of time, each evaluation run would differ from the last, and the model could cite
a deduction that does not exist. The catalogue is also what makes the
central claim measurable — the Interviewer and the Baseline questionnaire draw
from the same set, so "twelve questions instead of forty" compares like with
like. The autonomy this removes is not the autonomy the project set out to
demonstrate.
