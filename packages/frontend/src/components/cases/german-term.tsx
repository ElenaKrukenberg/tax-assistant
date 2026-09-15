"use client";

// A German tax term, translated, with the original beside it.
//
// The product exists to make a German return legible to somebody who does not read
// German officialese, so leaving `Lohnsteuerbescheinigung` on screen and calling it
// help was the contradiction at the centre of the interface. Translating it alone is
// no better: the form says Lohnsteuerbescheinigung, the Finanzamt's letter will say
// it, and a person who has only ever seen "annual wage statement" cannot match the
// two. So both, with the original styled as a quotation of the official word rather
// than as part of the sentence.

import { cn } from "@/lib/utils";

export function GermanTerm({
  children,
  original,
  className,
}: {
  // The translated name, in the reader's language.
  children: React.ReactNode;
  // The official German term. Dropped when it is the same string, which is what the
  // German UI always has.
  original: string;
  className?: string;
}) {
  const translated = typeof children === "string" ? children : null;
  if (!original || (translated !== null && translated === original)) {
    return <>{children}</>;
  }
  return (
    <>
      {children}{" "}
      <span
        lang="de"
        className={cn(
          "whitespace-nowrap rounded bg-muted px-1.5 py-0.5 align-middle font-mono",
          "text-[0.8em] font-normal text-muted-foreground",
          className,
        )}
      >
        {original}
      </span>
    </>
  );
}
