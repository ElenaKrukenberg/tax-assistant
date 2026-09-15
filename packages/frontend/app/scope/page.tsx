"use client";

import { useTranslations } from "next-intl";

import { AppNav } from "@/components/gta/app-nav";
import { ScopeStatement } from "@/components/gta/scope-statement";

/**
 * The one page that says what this build does.
 *
 * It is linked from the navigation and from the landing page rather than
 * duplicated into either, so there is a single place a visitor can be sent and
 * a single place that can be wrong. The page itself holds no claims: it asks
 * the backend, which answers from the same rules the interview runs on.
 */
export default function ScopePage() {
  const t = useTranslations("scope");

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />
      <main className="mx-auto max-w-3xl px-6 py-14">
        <header className="mb-10">
          <h1 className="text-[28px] font-semibold tracking-tight text-foreground">{t("title")}</h1>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{t("intro")}</p>
        </header>
        <ScopeStatement />
      </main>
    </div>
  );
}
