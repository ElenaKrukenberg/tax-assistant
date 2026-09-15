"use client";

import { CheckCircle2, FileText, Loader2, ShieldOff, UploadCloud } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { LiveDocuments } from "@/components/cases/live-documents";
import { EmptyState } from "@/components/cases/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import { getTaxCase } from "@/features/cases/case-api.stub";
import type { UploadedDocumentDto } from "@/features/cases/types";
import { isLiveBackend } from "@/lib/supabase";

function StateLine({ label, icon }: { label: string; icon: ReactNode }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
      {icon}
      {label}
    </p>
  );
}

function DocumentCard({ document }: { document: UploadedDocumentDto }) {
  const t = useTranslations("cases");
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <FileText className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{document.name}</p>
            <p className="text-xs text-muted-foreground">{document.sizeLabel}</p>
          </div>
        </div>
        {document.state === "confirmed" ? (
          <StateLine
            label={t("documents.confirmed")}
            icon={<CheckCircle2 className="size-3.5 text-success" aria-hidden="true" />}
          />
        ) : document.state === "reading" ? (
          <StateLine
            label={t("documents.reading")}
            icon={<Loader2 className="size-3.5 animate-spin text-primary" aria-hidden="true" />}
          />
        ) : document.state === "uploading" ? (
          <StateLine
            label={t("documents.uploading")}
            icon={<Loader2 className="size-3.5 animate-spin text-primary" aria-hidden="true" />}
          />
        ) : (
          <StateLine
            label={t("documents.awaiting")}
            icon={<FileText className="size-3.5" aria-hidden="true" />}
          />
        )}
      </div>

      {document.state === "uploading" ? (
        <Progress value={document.progress ?? 0} className="mt-3 h-1.5" />
      ) : null}
      {document.state === "reading" ? (
        <p className="mt-3 text-sm text-muted-foreground">{t("documents.readingStep")}</p>
      ) : null}
      {document.state === "confirmed" ? (
        <p className="mt-3 text-sm text-muted-foreground">{document.confirmedSummary}</p>
      ) : null}
      {document.state === "awaiting" && document.fields ? (
        <>
          <Separator className="my-4" />
          <div className="grid gap-4 md:grid-cols-[220px_1fr]">
            <div
              className="flex h-56 flex-col items-center justify-center rounded-lg border border-border bg-surface-2 text-center"
              role="img"
              aria-label={t("documents.preview")}
            >
              <FileText className="size-8 text-muted-foreground" aria-hidden="true" />
              <p className="mt-2 text-xs text-muted-foreground">{t("documents.pageOne")}</p>
            </div>
            <div className="space-y-3">
              {document.fields.map((field) => (
                <div key={field.id} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <Label htmlFor={`${document.id}-${field.id}`}>
                      {t(`documents.field.${field.id}`)}
                    </Label>
                    <span className="text-[11px] text-muted-foreground">
                      {t("documents.checkField")}
                    </span>
                  </div>
                  <Input
                    id={`${document.id}-${field.id}`}
                    defaultValue={field.value}
                    className="h-9"
                  />
                </div>
              ))}
              <div className="flex gap-2 pt-1">
                <Button size="sm">{t("documents.confirmFields")}</Button>
                <Button size="sm" variant="outline">
                  {t("documents.discard")}
                </Button>
              </div>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function DocumentsPage() {
  const params = useParams<{ id: string }>();
  // Signed in, this screen is the real thing. Without a backend it is the example
  // case - and it has to say so, because a sample document shown as somebody's own
  // data is the specific dishonesty issue #16 was opened about.
  if (isLiveBackend) {
    return <LiveDocuments caseId={params.id} />;
  }
  return <DemoDocumentsPage />;
}

function DemoDocumentsPage() {
  const t = useTranslations("cases");
  const params = useParams<{ id: string }>();
  const taxCase = getTaxCase(params.id);
  const [showStubNotice, setShowStubNotice] = useState(false);

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
        <Button variant="outline" className="mt-4" onClick={() => setShowStubNotice(true)}>
          {t("documents.choose")}
        </Button>
        {showStubNotice ? (
          <p className="mt-3 text-xs text-primary">{t("documents.demoNotice")}</p>
        ) : null}
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs text-muted-foreground">
        <ShieldOff className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
        {t("documents.privacy")}
      </p>

      <p className="text-xs text-muted-foreground">{t("documents.demoNotice")}</p>

      <div className="space-y-3">
        {taxCase.documents.length === 0 ? (
          <EmptyState title={t("documents.emptyTitle")} description={t("documents.emptyBody")} />
        ) : (
          taxCase.documents.map((document) => (
            <DocumentCard key={document.id} document={document} />
          ))
        )}
      </div>
    </div>
  );
}
