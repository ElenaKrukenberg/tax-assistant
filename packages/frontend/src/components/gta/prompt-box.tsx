"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowUp, Globe, Check } from "lucide-react";
import { useState, type FormEvent, type KeyboardEvent } from "react";
import { cn } from "@/lib/utils";
import { LOCALES, useLocale, type Locale } from "@/i18n/locale-provider";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  de: "Deutsch",
  tr: "Türkçe",
  ru: "Русский",
};

export function PromptBox({
  size = "hero",
  placeholder,
  autoFocus = false,
  onSubmit,
}: {
  size?: "hero" | "compact";
  placeholder?: string;
  autoFocus?: boolean;
  onSubmit?: (value: string) => void;
}) {
  const [value, setValue] = useState("");
  const router = useRouter();
  const t = useTranslations("chat");
  const { locale, setLocale } = useLocale();

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const v = value.trim();
    if (!v) return;
    if (onSubmit) {
      onSubmit(v);
    } else {
      // hand the question over via sessionStorage instead of ?q= so the
      // query never flashes in the address bar
      sessionStorage.setItem("pending-question", v);
      router.push("/chat");
    }
    setValue("");
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form
      onSubmit={submit}
      className={cn(
        "group relative w-full overflow-hidden rounded-2xl border border-border-strong bg-surface shadow-elevated transition",
        "focus-within:border-ring/60 focus-within:ring-4 focus-within:ring-ring/10",
      )}
    >
      <textarea
        autoFocus={autoFocus}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKey}
        placeholder={placeholder ?? t("promptPlaceholder")}
        rows={size === "hero" ? 3 : 1}
        className={cn(
          "block w-full resize-none bg-transparent px-5 pt-4 text-foreground placeholder:text-muted-foreground/70 focus:outline-none",
          size === "hero" ? "text-[17px] leading-relaxed" : "text-[15px] leading-6",
        )}
      />
      <div className="flex items-center justify-between px-3 pb-3 pt-1">
        <div className="flex items-center gap-1 text-muted-foreground">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs font-medium hover:bg-accent hover:text-foreground"
              >
                <Globe className="h-3.5 w-3.5" />
                {locale.toUpperCase()}
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {LOCALES.map((l) => (
                <DropdownMenuItem key={l} onClick={() => setLocale(l)} className="gap-2 text-sm">
                  <Check
                    className={cn("h-3.5 w-3.5", l === locale ? "opacity-100" : "opacity-0")}
                  />
                  {LOCALE_LABELS[l]}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <button
          type="submit"
          disabled={!value.trim()}
          aria-label="Send"
          className={cn(
            "inline-flex h-9 w-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-elevated transition",
            "disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground disabled:shadow-none",
            "hover:brightness-110",
          )}
        >
          <ArrowUp className="h-4 w-4" />
        </button>
      </div>
    </form>
  );
}
