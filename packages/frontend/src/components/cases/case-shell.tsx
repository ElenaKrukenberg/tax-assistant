"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import {
  ChevronLeft,
  FileCheck2,
  FileText,
  LayoutDashboard,
  MessagesSquare,
  ShieldCheck,
} from "lucide-react";
import type { ReactNode } from "react";

import { CaseStatusBadge } from "@/components/cases/badges";
import { BackendStatusBanner } from "@/components/gta/backend-status-banner";
import { DemoModeBanner } from "@/components/cases/states";
import { AppNav } from "@/components/gta/app-nav";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { getTaxCase } from "@/features/cases/case-api.stub";
import { type LiveCaseSummary, getCaseDetail } from "@/features/cases/api";
import { isLiveBackend } from "@/lib/supabase";
import { useEffect, useState } from "react";

const ITEMS = [
  { key: "overview", suffix: "", icon: LayoutDashboard },
  { key: "interview", suffix: "/interview", icon: MessagesSquare },
  { key: "documents", suffix: "/documents", icon: FileText },
  { key: "review", suffix: "/review", icon: ShieldCheck },
  { key: "report", suffix: "/report", icon: FileCheck2 },
] as const;

export function CaseShell({ children }: { children: ReactNode }) {
  const t = useTranslations("cases");
  const params = useParams<{ id: string }>();
  const caseId = params.id;
  const pathname = usePathname();
  const fixture = getTaxCase(caseId);
  const [live, setLive] = useState<LiveCaseSummary | null>(null);
  useEffect(() => {
    if (isLiveBackend)
      getCaseDetail(caseId)
        .then(setLive)
        .catch(() => {});
  }, [caseId]);
  // Live values once they arrive; the fixture keeps demo mode working unchanged.
  const taxCase = isLiveBackend
    ? { taxYear: live?.tax_year ?? "…", status: (live?.status ?? "gathering") as never }
    : { taxYear: fixture.taxYear, status: fixture.status };
  const base = `/cases/${caseId}`;

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />
      <SidebarProvider>
        <div className="flex min-h-[calc(100dvh-3.5rem)] w-full bg-background">
          <Sidebar collapsible="offcanvas" className="bottom-0 top-14 h-auto print-hide">
            <SidebarHeader className="gap-4 border-b border-sidebar-border p-5">
              <Link
                href="/cases"
                className="group flex items-center gap-1.5 text-sm text-muted-foreground transition-colors duration-200 ease-out hover:text-foreground"
              >
                <ChevronLeft className="h-4 w-4 transition-transform duration-200 ease-out group-hover:-translate-x-0.5" />
                {t("nav.allCases")}
              </Link>

              <div className="flex items-start justify-between gap-3">
                <div className="flex-1">
                  <SidebarGroupLabel className="px-0 pb-1.5 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    {t("common.taxYear")}
                  </SidebarGroupLabel>
                  <div className="font-display text-3xl leading-none text-foreground">
                    {taxCase.taxYear}
                  </div>
                </div>
                <CaseStatusBadge status={taxCase.status} />
              </div>
            </SidebarHeader>

            <SidebarContent className="px-3 pb-4">
              <SidebarGroup>
                <SidebarGroupLabel className="px-3 pb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {t("nav.thisCase")}
                </SidebarGroupLabel>

                <SidebarGroupContent>
                  <SidebarMenu className="gap-0.5">
                    {ITEMS.map((item) => {
                      const href = `${base}${item.suffix}`;
                      const active =
                        item.suffix === "" ? pathname === href : pathname.startsWith(href);

                      return (
                        <SidebarMenuItem key={item.key}>
                          <SidebarMenuButton
                            asChild
                            isActive={active}
                            className="group relative transition-all duration-200 ease-out text-muted-foreground hover:bg-accent/80 hover:text-accent-foreground data-[active=true]:bg-accent data-[active=true]:font-medium data-[active=true]:text-accent-foreground"
                          >
                            <Link href={href} className="relative flex items-center gap-2.5">
                              <span
                                className={`absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-primary transition-opacity duration-200 ease-out ${
                                  active ? "opacity-100" : "opacity-0"
                                }`}
                              />
                              <item.icon className="h-4 w-4 transition-transform duration-200 ease-out group-hover:scale-105" />
                              <span>{t(`nav.${item.key}`)}</span>
                            </Link>
                          </SidebarMenuButton>
                        </SidebarMenuItem>
                      );
                    })}
                  </SidebarMenu>
                </SidebarGroupContent>
              </SidebarGroup>
            </SidebarContent>
          </Sidebar>

          <SidebarInset>
            <header className="sticky top-14 z-30 flex h-14 items-center gap-2 border-b border-border bg-background/85 px-4 backdrop-blur print-hide">
              <SidebarTrigger
                aria-label={t("nav.toggle")}
                className="-ml-1 transition-colors duration-200 ease-out hover:bg-accent"
              />
              <span className="text-sm text-muted-foreground">
                {t("common.taxYear")} {taxCase.taxYear}
              </span>
            </header>
            <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
              {!isLiveBackend ? <DemoModeBanner /> : null}
              {/* The workspace waits on the backend for everything it shows, so a
                  sleeping free-tier instance looks like a broken screen here more
                  than anywhere else (#52). */}
              {isLiveBackend ? <BackendStatusBanner /> : null}
              <div className="mt-6">{children}</div>
            </div>
          </SidebarInset>
        </div>
      </SidebarProvider>
    </div>
  );
}
