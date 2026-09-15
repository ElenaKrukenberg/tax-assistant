"use client";

import { AppNav } from "@/components/gta/app-nav";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { LOCALES, useLocale, type Locale } from "@/i18n/locale-provider";
import { Trash2 } from "lucide-react";

import { useTheme } from "@/components/theme-provider";
import { ApiError, deleteCase, listCases } from "@/features/cases/api";
import { useSession } from "@/hooks/use-session";
import { clearConversations } from "@/lib/conversation-history";
import {
  DEPTHS,
  THEMES,
  getAnswersFollowUi,
  getDepth,
  getSaveHistory,
  getShowTrace,
  setAnswersFollowUi,
  setDepth,
  setSaveHistory,
  setShowTrace,
  type Depth,
} from "@/lib/preferences";
import { isLiveBackend } from "@/lib/supabase";

/**
 * Every control on this screen does what it says, or is not on the screen.
 *
 * Two are absent on purpose. **Export** returns when the operation behind it
 * exists. **"Improve the model with my chats"** is gone for good: every provider
 * call already carries a zero-data-retention policy, so the switch could not have
 * changed the outcome either way - and a privacy switch that cannot change the
 * outcome is worse than the plain sentence that replaced it (#18, decided in #70).
 */

type CaseOption = { id: string; taxYear: number; status: string };

export default function SettingsPage() {
  const t = useTranslations("settings");
  const tCases = useTranslations("cases");
  const { locale, setLocale } = useLocale();
  const { theme, setTheme } = useTheme();
  const session = useSession();

  // Preferences are read after mount, not during render: localStorage is
  // client-only and the server has no idea what any of these are.
  const [answersFollowUi, setAnswersFollowUiState] = useState(false);
  const [depth, setDepthState] = useState<Depth>("balanced");
  const [showTrace, setShowTraceState] = useState(true);
  const [saveHistory, setSaveHistoryState] = useState(true);

  useEffect(() => {
    setAnswersFollowUiState(getAnswersFollowUi());
    setDepthState(getDepth());
    setShowTraceState(getShowTrace());
    setSaveHistoryState(getSaveHistory());
  }, []);

  function toggleAnswersFollowUi(v: boolean) {
    setAnswersFollowUi(v);
    setAnswersFollowUiState(v);
  }

  function chooseDepth(v: string) {
    setDepth(v as Depth);
    setDepthState(v as Depth);
  }

  function toggleShowTrace(v: boolean) {
    setShowTrace(v);
    setShowTraceState(v);
  }

  function toggleSaveHistory(v: boolean) {
    // Off also forgets what is already stored. Stopping at "no new writes" would
    // leave every earlier transcript sitting in this browser, which is not what
    // someone turning the switch off is asking for.
    setSaveHistory(v);
    setSaveHistoryState(v);
    if (!v) clearConversations();
  }

  // --- the Tax Case this screen can delete ---------------------------------------
  //
  // Settings has no case list of its own, so the choice is explicit: a picker, and
  // the delete acts on what it names. Deleting "everything" from a screen that shows
  // nothing would be the same failure this ticket exists to end.
  const [cases, setCases] = useState<CaseOption[] | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signedIn = isLiveBackend && session.status === "signed_in";

  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    listCases()
      .then((list) => {
        if (cancelled) return;
        setCases(list.map((c) => ({ id: c.id, taxYear: c.tax_year, status: c.status })));
      })
      .catch((exc) => {
        if (cancelled) return;
        // A 401 here is not worth a redirect: nothing on this screen needed the
        // session except this one row, and the rest keeps working signed out.
        setCases([]);
        if (!(exc instanceof ApiError && exc.status === 401)) {
          setError(exc instanceof Error ? exc.message : String(exc));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [signedIn]);

  async function removeCase() {
    if (!selected) return;
    // The same warning the case list shows for the same act, from the same string:
    // two wordings for one delete is how they drift apart.
    if (!window.confirm(tCases("list.deleteConfirm"))) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteCase(selected);
      setCases((prev) => (prev ?? []).filter((c) => c.id !== selected));
      setSelected("");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="min-h-dvh bg-background">
      <AppNav />
      <main className="mx-auto max-w-3xl px-6 py-14">
        <header className="mb-10">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">{t("title")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{t("subtitle")}</p>
        </header>

        <div className="space-y-8">
          <Section title={t("general")} description={t("generalDesc")}>
            <Row id="ui-language" label={t("uiLanguage")} hint={t("uiLanguageHint")}>
              <Select value={locale} onValueChange={(v) => setLocale(v as Locale)}>
                <SelectTrigger id="ui-language" className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LOCALES.map((l) => (
                    <SelectItem key={l} value={l}>
                      {{ en: "English", de: "Deutsch", tr: "Türkçe", ru: "Русский" }[l]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Row>

            <Divider />

            <ToggleRow
              id="answers-follow-ui"
              label={t("answersFollowUi")}
              hint={t("answersFollowUiHint")}
              value={answersFollowUi}
              onChange={toggleAnswersFollowUi}
            />

            <Divider />

            <Row label={t("theme")} hint={t("themeHint")}>
              <RadioGroup
                value={theme}
                onValueChange={(v) => setTheme(v as (typeof THEMES)[number])}
                className="flex gap-4"
              >
                {THEMES.map((option) => (
                  <label
                    key={option}
                    htmlFor={`theme-${option}`}
                    className="flex cursor-pointer items-center gap-2 text-sm text-foreground"
                  >
                    <RadioGroupItem id={`theme-${option}`} value={option} />
                    <span>{t(`theme_${option}`)}</span>
                  </label>
                ))}
              </RadioGroup>
            </Row>
          </Section>

          <Section title={t("answers")} description={t("answersDesc")}>
            <Row id="response-depth" label={t("depth")} hint={t("depthHint")}>
              <Select value={depth} onValueChange={chooseDepth}>
                <SelectTrigger id="response-depth" className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DEPTHS.map((option) => (
                    <SelectItem key={option} value={option}>
                      {t(`depth_${option}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Row>

            <Divider />

            <ToggleRow
              id="show-trace"
              label={t("showTrace")}
              hint={t("showTraceHint")}
              value={showTrace}
              onChange={toggleShowTrace}
            />
          </Section>

          <Section title={t("privacy")} description={t("privacyDesc")}>
            <ToggleRow
              id="save-history"
              label={t("saveHistory")}
              hint={t("saveHistoryHint")}
              value={saveHistory}
              onChange={toggleSaveHistory}
            />

            <Divider />

            {/* Not a control, because there is no choice to offer: the zero-data-
                retention policy travels with every call, so this is true whatever a
                switch might have said. */}
            <div className="py-4">
              <Label className="text-sm font-medium text-foreground">{t("noTraining")}</Label>
              <p className="mt-0.5 text-xs text-muted-foreground">{t("noTrainingHint")}</p>
            </div>

            {signedIn && (
              <>
                <Divider />

                <Row id="delete-case" label={t("yourCase")} hint={t("deleteCaseHint")}>
                  {cases === null ? (
                    <span className="text-xs text-muted-foreground">{t("loadingCases")}</span>
                  ) : cases.length === 0 ? (
                    <span className="text-xs text-muted-foreground">{t("noCases")}</span>
                  ) : (
                    <div className="flex flex-col items-end gap-2 sm:flex-row sm:items-center">
                      <Select value={selected} onValueChange={setSelected}>
                        <SelectTrigger id="delete-case" className="w-56">
                          <SelectValue placeholder={t("chooseCase")} />
                        </SelectTrigger>
                        <SelectContent>
                          {cases.map((c) => (
                            <SelectItem key={c.id} value={c.id}>
                              {c.taxYear} · {tCases(`status.${c.status}`)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={!selected || deleting}
                        onClick={removeCase}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        {t("deleteCase")}
                      </Button>
                    </div>
                  )}
                </Row>
              </>
            )}

            {error && <p className="pb-4 text-xs text-destructive">{error}</p>}
          </Section>

          <Section title={t("account")} description={accountLine(session, t)}>
            <Row label={t("plan")} hint={t("planHint")}>
              <span className="rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-foreground">
                {t("planBadge")}
              </span>
            </Row>
          </Section>
        </div>
      </main>
    </div>
  );
}

/** What the Account card says about who is actually signed in. */
function accountLine(
  session: ReturnType<typeof useSession>,
  t: ReturnType<typeof useTranslations<"settings">>,
): string {
  if (session.status === "fixture") return t("accountFixture");
  if (session.status === "loading") return t("accountLoading");
  if (session.status === "signed_out") return t("accountSignedOut");
  return session.email
    ? t("accountSignedIn", { email: session.email })
    : t("accountSignedInNoEmail");
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-border bg-surface shadow-elevated">
      {/* A section title has to look like one. At 15px semibold it was a single
          pixel away from the 14px medium labels of the controls beneath it, so the
          block read as one flat list and its name looked like another setting. */}
      <header className="border-b border-border px-6 py-5">
        <h2 className="font-display text-lg leading-tight tracking-tight text-foreground">
          {title}
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </header>
      <div className="px-6 py-2">{children}</div>
    </section>
  );
}

/**
 * `htmlFor` is not decoration here: a switch or a select whose label is merely next
 * to it has no accessible name at all, so a screen reader announces "switch, off"
 * with nothing to say what it governs. Every control on this screen therefore
 * carries an id and its Row names it.
 */
function Row({
  id,
  label,
  hint,
  children,
}: {
  id?: string;
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 flex-1 pr-4">
        <Label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
        </Label>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function ToggleRow({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint?: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <Row id={id} label={label} hint={hint}>
      <Switch id={id} checked={value} onCheckedChange={onChange} />
    </Row>
  );
}

function Divider() {
  return <div className="h-px bg-border" />;
}
