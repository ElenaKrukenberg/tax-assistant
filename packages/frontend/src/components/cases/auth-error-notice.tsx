"use client";

// Supabase reports a failed sign-in link in the URL hash, not to any callback:
//   /cases#error=access_denied&error_code=otp_expired&error_description=...
// Nothing reads the hash by default, so the user who clicked an already-used
// link saw a silent page. This renders the one message that situation needs:
// the link works once, request a new one — unless a session exists anyway,
// in which case the first click already signed them in and there is nothing
// to complain about.

import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useSession } from "@/hooks/use-session";

export function AuthErrorNotice() {
  const t = useTranslations("cases");
  const session = useSession();
  const [code, setCode] = useState<string | null>(null);

  useEffect(() => {
    const hash = new URLSearchParams(window.location.hash.slice(1));
    const errorCode = hash.get("error_code");
    if (errorCode) {
      setCode(errorCode);
      // Clear the hash so a reload does not re-show a stale error.
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  if (!code || session.status === "signed_in") return null;

  return (
    <div className="mb-6 rounded-lg border border-warning/50 bg-warning/10 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div>
          <p className="text-sm font-medium">
            {code === "otp_expired" ? t("authError.expiredTitle") : t("authError.genericTitle")}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {code === "otp_expired" ? t("authError.expiredBody") : t("authError.genericBody")}
          </p>
          <Button asChild variant="outline" size="sm" className="mt-3">
            <Link href="/login">{t("authError.requestNew")}</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
