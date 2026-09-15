"use client";

import Link from "next/link";
import { CheckCircle2, Loader2, MailCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { FormEvent, useState } from "react";

import { DemoModeBanner } from "@/components/cases/states";
import { AppNav } from "@/components/gta/app-nav";
import { BackendStatusBanner } from "@/components/gta/backend-status-banner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { requestMagicLink } from "@/features/cases/case-api.stub";
import { useLocale } from "@/i18n/locale-provider";
import { isLiveBackend, supabase } from "@/lib/supabase";

export default function LoginPage() {
  const t = useTranslations("cases");
  const { locale } = useLocale();
  const [email, setEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [googling, setGoogling] = useState(false);

  async function withGoogle() {
    // No email at all, which is the point. The built-in mailer allows two messages
    // an hour across the whole project, so ten people testing on the same afternoon
    // cannot all get a link - and this path never asks it for one (#52, decided in #6).
    if (!supabase) return;
    setGoogling(true);
    setError(null);
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: `${window.location.origin}/cases` },
    });
    if (oauthError) {
      setError(oauthError.message);
      setGoogling(false);
    }
    // No success branch: the browser is already on its way to Google.
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSending(true);
    setError(null);
    if (isLiveBackend && supabase) {
      // The real magic link. The redirect lands back on /cases with the session
      // in the URL hash, which supabase-js picks up by itself.
      const { error: signInError } = await supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${window.location.origin}/cases`,
          // The UI language, for the email template: Supabase templates read it as
          // {{ .Data.locale }}. Stored in user_metadata on first sign-up; the very
          // first email to a brand-new address may still arrive in English.
          data: { locale },
        },
      });
      if (signInError) {
        setError(signInError.message);
        setSending(false);
        return;
      }
    } else {
      await requestMagicLink(email);
    }
    setSending(false);
    setSent(true);
  }

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />
      <main className="mx-auto flex min-h-[calc(100dvh-3.5rem)] w-full max-w-md flex-col justify-center gap-4 px-4 py-12">
        {!isLiveBackend ? <DemoModeBanner /> : null}
        {/* The first thing anybody touches after a quiet night, and the place a free
            tier's cold start is least explicable: the form accepts the address, and
            then nothing happens for half a minute (#52). */}
        {isLiveBackend ? <BackendStatusBanner /> : null}
        <Card className="border-border bg-surface">
          {sent ? (
            <CardContent className="py-10 text-center">
              <MailCheck className="mx-auto size-8 text-primary" aria-hidden="true" />
              <h1 className="mt-4 font-display text-3xl">{t("login.sentTitle")}</h1>
              <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
                {isLiveBackend
                  ? t("login.sentLiveBody", { email })
                  : t("login.sentStubBody", { email })}
              </p>
              <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
                {!isLiveBackend ? (
                  <Button asChild>
                    <Link href="/cases">
                      <CheckCircle2 className="size-4" />
                      {t("login.openDemo")}
                    </Link>
                  </Button>
                ) : null}
                <Button variant="ghost" onClick={() => setSent(false)}>
                  {t("login.again")}
                </Button>
              </div>
            </CardContent>
          ) : (
            <>
              <CardHeader>
                <h1 className="font-display text-3xl font-normal">{t("login.title")}</h1>
                <CardDescription>{t("login.subtitle")}</CardDescription>
              </CardHeader>
              <CardContent>
                {isLiveBackend ? (
                  <>
                    {/* First, and separated: it is the path that works for everybody
                        at once, and the one below is rate-limited by the mailer. */}
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full"
                      onClick={() => void withGoogle()}
                      disabled={googling || sending}
                    >
                      {googling ? <Loader2 className="size-4 animate-spin" /> : null}
                      {t("login.withGoogle")}
                    </Button>
                    <div className="my-4 flex items-center gap-3">
                      <div className="h-px flex-1 bg-border" />
                      <span className="text-xs text-muted-foreground">{t("login.or")}</span>
                      <div className="h-px flex-1 bg-border" />
                    </div>
                  </>
                ) : null}
                <form className="space-y-4" onSubmit={submit}>
                  <div className="space-y-2">
                    <Label htmlFor="email">{t("login.emailLabel")}</Label>
                    <Input
                      id="email"
                      type="email"
                      required
                      autoComplete="email"
                      placeholder="you@example.com"
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                    />
                  </div>
                  <Button type="submit" className="w-full" disabled={sending}>
                    {sending ? <Loader2 className="size-4 animate-spin" /> : null}
                    {sending ? t("login.sending") : t("login.submit")}
                  </Button>
                  {error ? (
                    <p role="alert" className="text-sm text-destructive">
                      {error}
                    </p>
                  ) : null}
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    {isLiveBackend ? t("login.helperLive") : t("login.helper")}
                  </p>
                </form>
              </CardContent>
            </>
          )}
        </Card>
      </main>
    </div>
  );
}
