"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { AppNav } from "@/components/gta/app-nav";
import { BackendStatusBanner } from "@/components/gta/backend-status-banner";
import { PromptBox } from "@/components/gta/prompt-box";
import { SuggestionChips } from "@/components/gta/suggestion-chips";
import {
  ShieldCheck,
  BookOpen,
  Languages,
  Sparkles,
  ArrowRight,
  FileText,
  Landmark,
  ScrollText,
  MessagesSquare,
} from "lucide-react";

// official source names are proper nouns — not translated
const trust = [
  { icon: Landmark, label: "Bundesministerium der Finanzen" },
  { icon: ScrollText, label: "Einkommensteuergesetz (EStG)" },
  { icon: FileText, label: "Anlage N Anleitung 2025" },
  { icon: BookOpen, label: "Lohnsteuer-Handbuch (LStH)" },
];

export function LandingContent() {
  const t = useTranslations("landing");

  const suggestions = [t("suggestion1"), t("suggestion2"), t("suggestion3"), t("suggestion4")];

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />

      <main>
        {/* Hero */}
        <section className="relative">
          <div className="pointer-events-none absolute inset-0 -z-10 bg-dotgrid opacity-60 [mask-image:radial-gradient(ellipse_at_top,black_20%,transparent_70%)]" />
          <div className="mx-auto max-w-3xl px-6 pt-20 pb-14 text-center sm:pt-28">
            <div className="mx-auto mb-8 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-muted-foreground shadow-elevated">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-primary" />
              </span>
              {t("badge")}
            </div>

            <h1 className="text-balance text-5xl font-semibold tracking-[-0.03em] text-foreground sm:text-6xl">
              {t("h1Pre")}{" "}
              <span className="font-display italic font-normal text-primary">{t("h1Italic")}</span>{" "}
              {t("h1Post")}
            </h1>
            <p className="mx-auto mt-6 max-w-xl text-pretty text-[17px] leading-relaxed text-muted-foreground">
              {t("heroText")}
            </p>

            <div className="mx-auto mt-10 max-w-2xl">
              {/* The check that feeds this banner is also what wakes the free-tier
                  instance, so mounting it here means the boot happens while the
                  question is being typed rather than after it is sent. */}
              <BackendStatusBanner className="mb-3" />
              {/* Above the field, not below it: the scope is what decides whether
                  the question you are about to type is one this can answer. The
                  years and forms are not repeated here - they would go stale the
                  first time a year is added - so this says the one thing that
                  never changes and points at the page that is read from the build. */}
              <p className="mb-3 text-center text-xs text-muted-foreground/70">
                {t("scopeNote")}{" "}
                <Link href="/scope" className="underline underline-offset-2 hover:text-foreground">
                  {t("scopeLink")}
                </Link>
              </p>
              <PromptBox size="hero" />
            </div>

            <SuggestionChips suggestions={suggestions} />
          </div>
        </section>

        {/* Trust */}
        <section className="mx-auto max-w-5xl px-6 py-16">
          <div className="mb-8 flex items-center justify-center gap-2 text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5" />
            {t("trustTitle")}
          </div>
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border sm:grid-cols-4">
            {trust.map(({ icon: Icon, label }) => (
              <div
                key={label}
                className="flex flex-col items-center gap-3 bg-surface px-4 py-8 text-center"
              >
                <Icon className="h-5 w-5 text-primary" strokeWidth={1.75} />
                <span className="text-[13px] font-medium text-foreground">{label}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Feature grid */}
        <section className="mx-auto max-w-5xl px-6 py-16">
          <div className="grid gap-6 md:grid-cols-3">
            <FeatureCard icon={Sparkles} title={t("feature1Title")} body={t("feature1Body")} />
            <FeatureCard icon={Languages} title={t("feature2Title")} body={t("feature2Body")} />
            <FeatureCard
              icon={MessagesSquare}
              title={t("feature3Title")}
              body={t("feature3Body")}
            />
          </div>
        </section>

        {/* CTA */}
        <section className="mx-auto max-w-3xl px-6 pb-24 pt-8 text-center">
          <div className="rounded-2xl border border-border bg-surface px-8 py-14 shadow-elevated">
            <h2 className="text-3xl font-semibold tracking-tight text-foreground">
              {t("ctaTitle")}
            </h2>
            <p className="mx-auto mt-3 max-w-md text-sm text-muted-foreground">{t("ctaText")}</p>
            <Link
              href="/chat"
              className="mt-8 inline-flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground shadow-elevated transition hover:brightness-110"
            >
              {t("ctaButton")}
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-4 px-6 py-8 text-xs text-muted-foreground sm:flex-row sm:items-center">
          <div>{t("footerNote")}</div>
          <div className="flex items-center gap-5">
            <a className="hover:text-foreground" href="#">
              {t("footerPrivacy")}
            </a>
            <a className="hover:text-foreground" href="#">
              {t("footerSources")}
            </a>
            <a className="hover:text-foreground" href="#">
              {t("footerImpressum")}
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ className?: string; strokeWidth?: number }>;
  title: string;
  body: string;
}) {
  return (
    <div className="group rounded-2xl border border-border bg-surface p-6 transition hover:border-border-strong hover:shadow-elevated">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent text-primary">
        <Icon className="h-4.5 w-4.5" strokeWidth={1.75} />
      </div>
      <h3 className="mt-5 text-[15px] font-semibold text-foreground">{title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{body}</p>
    </div>
  );
}
