import type { Locale } from "@/i18n/locale-provider";

const NUMBER_LOCALE: Record<Locale, string> = {
  en: "en-DE",
  de: "de-DE",
  ru: "ru-RU",
  tr: "tr-TR",
};

export function formatEur(value: number, locale: Locale) {
  return new Intl.NumberFormat(NUMBER_LOCALE[locale], {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
  }).format(value);
}

export function formatCaseDate(value: string, locale: Locale) {
  return new Intl.DateTimeFormat(NUMBER_LOCALE[locale], {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

// next-intl reads a dot as a namespace separator, so a Fact key - "commute.distance_km",
// "profile.employed_months" - cannot be a message key as it stands. The id keeps the
// backend's spelling, which is what makes a value traceable; the message catalogue uses
// this flattened form of it.
export function messageKey(id: string): string {
  return id.replaceAll(".", "__");
}

/**
 * "Anlage N, Zeilen 54-56" rather than "anlage_n 54-56".
 *
 * The form's name is not translated - Anlage N is what the sheet is called in every
 * language, and a filer looking for it will be looking for that. The word for "line"
 * is, because that part is prose. Plural when the figure spans more than one line,
 * which is what a range or a list means.
 */
export function formLabel(
  expense: { form?: string; form_lines?: string; form_line: string },
  t: (key: string) => string,
): string {
  if (!expense.form || !expense.form_lines) return expense.form_line;
  const many = /[-,]/.test(expense.form_lines);
  const name = t(`forms.${expense.form}`);
  return `${name}, ${t(many ? "report.lines" : "report.line")} ${expense.form_lines}`;
}
