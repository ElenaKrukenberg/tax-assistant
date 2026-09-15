"use client";

// The live Documents screen: upload, read, confirm - the real path.
//
// What this component does not do is decide anything about the document. The
// category, the values, whether the two reads agreed, what still needs answering:
// all of it arrives from the backend, which is where it can be tested and where the
// model lives. This renders the pause and sends back what the user settled on.
//
// The two states worth looking at in the markup are the ones that carry the
// product's promise. A **disagreement** offers no values at all - two reads that
// differ are a gate, not a percentage - and a **contradiction** ("this looks like
// Fortbildung, but the invoice mentions a restaurant") is shown as a question beside
// the category rather than quietly accepted.

import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Loader2,
  ShieldOff,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { GermanTerm } from "@/components/cases/german-term";
import { ReopenButton } from "@/components/cases/reopen-button";
import { EmptyState, InlineError } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  ApiError,
  type DocumentKind,
  type LiveDocument,
  confirmDocument,
  discardDocument,
  listDocuments,
  setDocumentCategory,
  uploadDocument,
} from "@/features/cases/api";

const KINDS: DocumentKind[] = ["lohnsteuerbescheinigung", "rechnung"];

/** A value as the user is editing it: text, so a half-typed number is not a number. */
type Draft = Record<string, string>;

function draftOf(document: LiveDocument): Draft {
  const draft: Draft = {};
  for (const item of document.proposed) {
    draft[item.key] =
      typeof item.value === "boolean" ? String(item.value) : String(item.value ?? "");
  }
  return draft;
}

/** Back to the type the backend validates: booleans as booleans, numbers as numbers. */
function parsed(key: string, text: string, proposed: LiveDocument["proposed"]): unknown {
  const original = proposed.find((item) => item.key === key)?.value;
  if (typeof original === "boolean") return text === "true";
  if (typeof original === "number") {
    const value = Number(text.replace(",", "."));
    return Number.isFinite(value) ? value : text;
  }
  return text;
}

// The backend's refusal to write to a finished case, recognised rather than shown.
// It arrives on any route that would write - the upload, and the listing, which
// sweeps expired uploads before it reads.
function isLockedCase(exc: unknown): boolean {
  return exc instanceof ApiError && exc.status === 409 && /finalized/i.test(exc.message);
}

export function LiveDocuments({ caseId }: { caseId: string }) {
  const t = useTranslations("cases");
  const [documents, setDocuments] = useState<LiveDocument[] | null>(null);
  const [kind, setKind] = useState<DocumentKind>("rechnung");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // A finished case refuses every write, uploads included. The refusal used to reach
  // the screen as the backend's own sentence - "the case is finalized; reopen it
  // first" - which names a state the user was never shown and a door they could not
  // see. Recognised here so the screen can say it in their language and put the door
  // next to it.
  const [locked, setLocked] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    listDocuments(caseId)
      .then((rows) => {
        setDocuments(rows);
        setError(null);
        setLocked(false);
      })
      .catch((exc: unknown) => {
        // A locked case is a state, not a failure. It used to arrive as the
        // database's own sentence in a red box, over a list that then stayed on
        // "loading" forever because nothing ever set it.
        if (isLockedCase(exc)) {
          setLocked(true);
          setDocuments([]);
          setError(null);
          return;
        }
        setDocuments([]);
        setError(exc instanceof ApiError ? exc.message : t("documents.loadFailed"));
      });
  }, [caseId, t]);

  useEffect(load, [load]);

  async function onFile(file: File) {
    setBusy("upload");
    setError(null);
    try {
      // One key per attempt. A retry of *this* attempt reuses it, which is what
      // stops a dropped connection from paying to read the same page twice.
      const document = await uploadDocument(caseId, file, kind, crypto.randomUUID());
      setDrafts((current) => ({ ...current, [document.id]: draftOf(document) }));
      setDocuments((current) => [...(current ?? []), document]);
    } catch (exc: unknown) {
      if (isLockedCase(exc)) {
        setLocked(true);
      } else {
        setError(exc instanceof ApiError ? exc.message : t("documents.uploadFailed"));
      }
    } finally {
      setBusy(null);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function onConfirm(document: LiveDocument) {
    setBusy(document.id);
    setError(null);
    // Fall back to what the document itself proposes, never to an empty draft: after
    // a reload nothing has been typed, and an empty confirmation is refused by the
    // backend - correctly, and for something the user did not do.
    const draft = drafts[document.id] ?? draftOf(document);
    const values: Record<string, unknown> = {};
    for (const [key, text] of Object.entries(draft)) {
      if (text.trim() !== "") values[key] = parsed(key, text, document.proposed);
    }
    try {
      const saved = await confirmDocument(caseId, document.id, values, document.category);
      setDocuments((current) => (current ?? []).map((row) => (row.id === saved.id ? saved : row)));
    } catch (exc: unknown) {
      setError(exc instanceof ApiError ? exc.message : t("documents.confirmFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function onCategory(document: LiveDocument, category: string) {
    if (category === document.category) return;
    setBusy(document.id);
    setError(null);
    try {
      // The backend maps the document again under the chosen category and answers
      // with the values that category yields - different keys, not the same ones
      // relabelled - so the draft is replaced rather than merged into.
      const saved = await setDocumentCategory(caseId, document.id, category);
      setDocuments((current) => (current ?? []).map((row) => (row.id === saved.id ? saved : row)));
      setDrafts((current) => ({ ...current, [saved.id]: draftOf(saved) }));
    } catch (exc: unknown) {
      setError(exc instanceof ApiError ? exc.message : t("documents.categoryFailed"));
    } finally {
      setBusy(null);
    }
  }

  async function onDiscard(document: LiveDocument) {
    setBusy(document.id);
    try {
      const saved = await discardDocument(caseId, document.id);
      setDocuments((current) => (current ?? []).map((row) => (row.id === saved.id ? saved : row)));
    } catch (exc: unknown) {
      setError(exc instanceof ApiError ? exc.message : t("documents.discardFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-4xl leading-tight">{t("documents.title")}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{t("documents.subtitle")}</p>
      </div>

      <div className="rounded-xl border border-dashed border-border-strong bg-surface-2 px-6 py-10 text-center">
        <UploadCloud className="mx-auto size-7 text-muted-foreground" aria-hidden="true" />
        <p className="mt-3 text-sm font-medium">{t("documents.dropTitle")}</p>
        <p className="mt-1 text-sm text-muted-foreground">{t("documents.dropBody")}</p>

        {/* The type is chosen before the upload, on purpose: it picks the extraction
            schema, and it is also the only thing that decides whether the file is
            sent to a model at all - the two supported types are an allowlist
            (packages/backend/services/documents/sensitivity.py). */}
        <div
          className="mt-4 flex flex-wrap items-center justify-center gap-2"
          role="radiogroup"
          aria-label={t("documents.kindLabel")}
        >
          {KINDS.map((option) => (
            <Button
              key={option}
              type="button"
              role="radio"
              aria-checked={kind === option}
              variant={kind === option ? "default" : "outline"}
              size="sm"
              onClick={() => setKind(option)}
            >
              {option === "lohnsteuerbescheinigung" ? (
                <GermanTerm original="Lohnsteuerbescheinigung">
                  {t(`documents.kind.${option}`)}
                </GermanTerm>
              ) : (
                t(`documents.kind.${option}`)
              )}
            </Button>
          ))}
        </div>

        <input
          ref={fileInput}
          type="file"
          accept="image/jpeg,image/png,application/pdf"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void onFile(file);
          }}
        />
        <Button
          variant="outline"
          className="mt-4"
          disabled={busy === "upload"}
          onClick={() => fileInput.current?.click()}
        >
          {busy === "upload" ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" />
              {t("documents.reading")}
            </>
          ) : (
            t("documents.choose")
          )}
        </Button>
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
        <ShieldOff className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        {t("documents.privacy")}
      </p>

      {locked ? (
        <div className="rounded-lg border border-warning/60 bg-warning/5 p-4">
          <p className="text-sm">{t("documents.caseFinalized")}</p>
          <ReopenButton
            caseId={caseId}
            onReopened={() => {
              setLocked(false);
              load();
            }}
          />
        </div>
      ) : null}

      {error ? (
        <InlineError title={t("documents.errorTitle")} description={error} onRetry={load} />
      ) : null}

      <div className="space-y-3">
        {documents === null ? (
          <p className="text-sm text-muted-foreground">{t("documents.loading")}</p>
        ) : documents.length === 0 ? (
          <EmptyState title={t("documents.emptyTitle")} description={t("documents.emptyBody")} />
        ) : (
          documents.map((document) => (
            <DocumentCard
              key={document.id}
              document={document}
              draft={drafts[document.id] ?? draftOf(document)}
              busy={busy === document.id}
              onChange={(key, text) =>
                setDrafts((current) => ({
                  ...current,
                  [document.id]: { ...(current[document.id] ?? draftOf(document)), [key]: text },
                }))
              }
              onCategory={(category) => void onCategory(document, category)}
              onConfirm={() => void onConfirm(document)}
              onDiscard={() => void onDiscard(document)}
            />
          ))
        )}
      </div>
    </div>
  );
}

function DocumentCard({
  document,
  draft,
  busy,
  onChange,
  onCategory,
  onConfirm,
  onDiscard,
}: {
  document: LiveDocument;
  draft: Draft;
  busy: boolean;
  onChange: (key: string, value: string) => void;
  onCategory: (category: string) => void;
  onConfirm: () => void;
  onDiscard: () => void;
}) {
  const t = useTranslations("cases");
  const waiting = document.state === "awaiting_confirmation";

  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{document.file_name}</p>
            <p className="text-xs text-muted-foreground">
              {document.kind ? t(`documents.kind.${document.kind}`) : null}
            </p>
          </div>
        </div>
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {document.state === "confirmed" ? (
            <>
              <CheckCircle2 className="size-3.5 text-success" aria-hidden="true" />
              {t("documents.confirmed")}
            </>
          ) : document.state === "failed" ? (
            <>
              <AlertTriangle className="size-3.5 text-destructive" aria-hidden="true" />
              {t("documents.failed")}
            </>
          ) : document.state === "discarded" ? (
            <>
              <Trash2 className="size-3.5" aria-hidden="true" />
              {t("documents.discarded")}
            </>
          ) : waiting ? (
            <>
              <FileText className="size-3.5" aria-hidden="true" />
              {t("documents.awaiting")}
            </>
          ) : (
            <>
              <Loader2 className="size-3.5 animate-spin text-primary" aria-hidden="true" />
              {t("documents.reading")}
            </>
          )}
        </p>
      </div>

      {document.state === "failed" && document.failure_detail ? (
        <p className="mt-3 text-sm text-muted-foreground">{document.failure_detail}</p>
      ) : null}

      {waiting ? (
        <>
          <Separator className="my-4" />

          {document.category ? (
            <p className="text-xs text-muted-foreground">
              {t("documents.categoryLine", {
                category: t(`categories.${document.category}`),
                reason: document.category_reason,
              })}
            </p>
          ) : null}

          {/* Which model produced these values. Shown rather than assumed: the
              configured model is not always the one that answered, and a trace that
              names the wrong reader is worse than none. */}
          {document.read_cost_usd != null ? (
            // The product's own acceptance criteria ask for visible cost, and this is
            // the first paid call outside the chat. Cents rather than dollars: a
            // document costs a fraction of one, and "$0.00" would read as free.
            <p className="text-xs text-muted-foreground">
              {t("documents.readCost", {
                cents: (document.read_cost_usd * 100).toFixed(2),
                tokens: document.read_tokens ?? 0,
              })}
            </p>
          ) : null}
          {document.read_by ? (
            <p className="text-xs text-muted-foreground">
              {t("documents.readBy", { model: document.read_by })}
            </p>
          ) : null}

          {/* Offered only when there is something to choose between: the backend
              sends an empty list for a Lohnsteuerbescheinigung, for a settled
              document, and for two reads that disagreed - none of which has a
              category to pick. Picking one asks for a new proposal, so the values
              below change with it. */}
          {document.category_choices.length > 0 ? (
            <div
              className="mt-3 flex flex-wrap items-center gap-2"
              role="radiogroup"
              aria-label={t("documents.categoryLabel")}
            >
              {document.category_choices.map((option) => (
                <Button
                  key={option}
                  type="button"
                  role="radio"
                  aria-checked={document.category === option}
                  variant={document.category === option ? "default" : "outline"}
                  size="sm"
                  disabled={busy}
                  onClick={() => onCategory(option)}
                >
                  {t(`categories.${option}`)}
                </Button>
              ))}
            </div>
          ) : null}

          {/* Two reads that differ offer nothing to confirm. Both readings are shown
              instead, because the user is the only one who can settle it (issue #5). */}
          {document.disagreements.length > 0 ? (
            <div className="mt-3 rounded-lg border border-warning/40 bg-warning/5 p-3">
              <p className="text-sm font-medium">{t("documents.disagreementTitle")}</p>
              <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                {document.disagreements.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {document.contradiction ? (
            <p className="mt-3 flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/5 p-3 text-sm">
              <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden="true" />
              {t("documents.contradiction", { detail: document.contradiction })}
            </p>
          ) : null}

          {document.questions.length > 0 ? (
            <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
              {document.questions.map((question) => (
                <li key={question}>{question}</li>
              ))}
            </ul>
          ) : null}

          {document.proposed.length > 0 ? (
            <div className="mt-4 space-y-3">
              {document.proposed.map((item) => (
                <div key={item.key} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-2">
                    {/* The catalogue's wording, not the Fact key: `equipment.price_eur#2`
                        is how the value is stored, not what it is called. The key stays
                        as the input's id, which is what the confirmation sends back. */}
                    <Label htmlFor={`${document.id}-${item.key}`}>
                      {item.label}
                      {item.item !== null ? (
                        <span className="ml-2 text-[11px] font-normal text-muted-foreground">
                          {t("documents.itemNumber", { number: item.item })}
                        </span>
                      ) : null}
                    </Label>
                    <span className="text-[11px] text-muted-foreground">
                      {t("documents.checkField")}
                    </span>
                  </div>
                  <Input
                    id={`${document.id}-${item.key}`}
                    className="h-9"
                    value={draft[item.key] ?? ""}
                    onChange={(event) => onChange(item.key, event.target.value)}
                  />
                </div>
              ))}
            </div>
          ) : null}

          <div className="flex gap-2 pt-4">
            <Button size="sm" disabled={busy} onClick={onConfirm}>
              {busy ? <Loader2 className="mr-2 size-4 animate-spin" aria-hidden="true" /> : null}
              {t("documents.confirmFields")}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={onDiscard}>
              {t("documents.discard")}
            </Button>
          </div>
        </>
      ) : null}
    </div>
  );
}
