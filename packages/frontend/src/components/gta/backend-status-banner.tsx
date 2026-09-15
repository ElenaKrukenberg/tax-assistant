"use client";

import { useTranslations } from "next-intl";
import { CloudOff, Loader2 } from "lucide-react";

import { useBackendHealth } from "@/hooks/use-backend-health";
import { cn } from "@/lib/utils";

/**
 * Says out loud what the user would otherwise infer from a long silence: the free-tier
 * instance is booting, or it is not answering at all. Renders nothing while the check
 * is in flight and nothing once it succeeds — a healthy backend is not news.
 */
export function BackendStatusBanner({ className }: { className?: string }) {
  const status = useBackendHealth();
  const t = useTranslations("status");

  if (status === "checking" || status === "ok") return null;

  const waking = status === "waking";
  const Icon = waking ? Loader2 : CloudOff;

  return (
    <div
      // polite, not assertive: this interrupts nothing the user is doing
      role="status"
      className={cn(
        "flex items-center gap-2 rounded-xl border px-4 py-2.5 text-left text-[13px]",
        waking
          ? "border-border bg-accent/60 text-foreground"
          : "border-destructive/30 bg-destructive/10 text-foreground",
        className,
      )}
    >
      <Icon
        className={cn(
          "h-4 w-4 shrink-0",
          waking ? "animate-spin text-primary" : "text-destructive",
        )}
      />
      {waking ? t("waking") : t("unreachable")}
    </div>
  );
}
