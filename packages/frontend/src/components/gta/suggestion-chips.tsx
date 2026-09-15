"use client";

import { useRouter } from "next/navigation";

// Landing-page starter questions: hand the question to /chat via
// sessionStorage (same as PromptBox) so it never appears in the URL.
export function SuggestionChips({ suggestions }: { suggestions: string[] }) {
  const router = useRouter();

  function pick(q: string) {
    sessionStorage.setItem("pending-question", q);
    router.push("/chat");
  }

  return (
    <div className="mx-auto mt-6 flex flex-wrap justify-center gap-2">
      {suggestions.map((s) => (
        <button
          key={s}
          onClick={() => pick(s)}
          className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs font-medium text-muted-foreground transition hover:border-border-strong hover:bg-accent hover:text-foreground"
        >
          {s}
        </button>
      ))}
    </div>
  );
}
