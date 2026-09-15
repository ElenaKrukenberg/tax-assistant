# The chat may feed the case, but never carries it in its prompt

The chat tab becomes an entrance to a Tax Case in two ways: a button under an
answer that opens the interview for the user's own figures, and extraction of
facts the user mentions in passing ("I work from home three days a week") into
the profile, after confirmation, so the Interviewer stops asking for them. In
both, the chat's own prompt is untouched: the fact extraction is a separate
structured-output call over the user's message, not case state added to the
conversation.

That separation is the whole point of the decision. Putting the case into the
chat prompt was the obvious alternative and is what makes "why did you deduct
1,400 €" answerable in the chat — but the 26-case golden set and the
`lexical-cap` score of 91/91 were measured against the chat as it is, and a chat
carrying case state is a different system whose published numbers no longer mean
anything. Keeping the extraction beside the conversation rather than inside it
buys the feature without spending the baseline. It also keeps the chat cheap
enough for the existing per-IP limit to be adequate protection.

Conducting the interview itself in the chat was rejected for a different reason:
free-text answers need parsing, which reintroduces the failure mode
[ADR 0001](0001-question-catalogue-instead-of-generated-questions.md) removed,
and the profile fixtures that drive the agent-versus-questionnaire measurement
answer from a dictionary and cannot hold a conversation. The dedicated interview
screen with typed answer controls stays the main path.

The boundary to hold in future work: answers may arrive from anywhere — the
interview, a document, the chat — but each source confirms with the user before
the value lands in the case, and none of them may put the case into the chat's
prompt.
