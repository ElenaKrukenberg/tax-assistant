/**
 * The user is told they are talking to an AI system, in their own language, before
 * the first answer rather than after it (#87).
 *
 * Two halves, because the ticket has two failure modes and they fail separately: the
 * string can be missing from a catalogue, and the string can be present everywhere and
 * rendered nowhere. The catalogue half also guards the quieter failure - a key added
 * to `en.json` and copied verbatim into the other three, which reads as translated and
 * is not.
 */

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import tr from "@/i18n/messages/tr.json";

import ChatPage from "../app/chat/page";
import { LocaleProvider } from "@/i18n/locale-provider";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/chat",
}));

const CATALOGUES = { en, de, ru, tr } as Record<string, Record<string, unknown>>;

function lookup(catalogue: Record<string, unknown>, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => {
    if (node && typeof node === "object" && part in node) {
      return (node as Record<string, unknown>)[part];
    }
    return undefined;
  }, catalogue);
}

const DISCLOSURES = ["chat.aiDisclosure", "cases.interview.aiDisclosure"];

describe("AI disclosure", () => {
  it.each(Object.keys(CATALOGUES))("is present and translated in %s", (language) => {
    for (const key of [...DISCLOSURES, "chat.aiBadge"]) {
      const text = lookup(CATALOGUES[language], key);
      expect(typeof text, `${language}: ${key}`).toBe("string");
      expect(String(text).trim().length, `${language}: ${key}`).toBeGreaterThan(0);
    }
    if (language === "en") return;
    // A sentence identical to the English one is a copy, not a translation. The badge
    // is exempt: it is two characters and is asserted by value below.
    for (const key of DISCLOSURES) {
      expect(lookup(CATALOGUES[language], key), `${language}: ${key}`).not.toBe(lookup(en, key));
    }
  });

  it("names the technology in the language of the interface", () => {
    // Not "AI" everywhere: a German reader looking for the disclosure is looking for
    // KI, and a Russian one for ИИ.
    expect(lookup(en, "chat.aiBadge")).toBe("AI");
    expect(lookup(de, "chat.aiBadge")).toBe("KI");
    expect(lookup(ru, "chat.aiBadge")).toBe("ИИ");
    expect(lookup(tr, "chat.aiBadge")).toBe("YZ");
  });

  it("is on the chat screen before the user has asked anything", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 })),
    );
    render(
      <LocaleProvider>
        <ChatPage />
      </LocaleProvider>,
    );

    // The empty state is what a first-time visitor sees, so this is the last moment
    // that still counts as "no later than the first AI interaction".
    expect(screen.getByText(String(lookup(en, "chat.aiDisclosure")))).toBeInTheDocument();
  });

  it("does not rely on the tax-advice disclaimer to carry it", () => {
    // Two different statements, and only one of them is #87's. If the AI sentence were
    // ever folded into the legal one, this fails - which is the point: the ticket says
    // the disclosure must not be hidden inside something else.
    const disclaimer = String(lookup(en, "chat.disclaimer"));
    const disclosure = String(lookup(en, "chat.aiDisclosure"));
    expect(disclaimer).not.toContain(disclosure);
    expect(disclosure).not.toBe(disclaimer);
  });
});
