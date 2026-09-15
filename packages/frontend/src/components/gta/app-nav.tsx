"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";
import { Logo } from "./logo";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { signOut, useSession } from "@/hooks/use-session";
import { cn } from "@/lib/utils";

// The address is shown in two shapes, and neither is decoration: the initial is
// what identifies the account when the trigger has no room for text at all, and the
// local part is what a person reads their own address by.
function localPartOf(email: string | null): string {
  if (!email) return "";
  const at = email.indexOf("@");
  return at > 0 ? email.slice(0, at) : email;
}

function initialOf(email: string | null): string {
  return localPartOf(email).charAt(0) || "?";
}

export function AppNav() {
  const pathname = usePathname();
  const t = useTranslations("nav");
  const session = useSession();

  // Settings was hidden from the nav while its controls were scenery; they are real
  // now (#18), and a page nobody can reach is the same as one that does not exist.
  // It sits on the right beside the account rather than in the middle: the four links
  // below are modes of the product, and settings are not a mode.
  const links = [
    { href: "/", label: t("overview") },
    { href: "/chat", label: t("assistant") },
    { href: "/cases", label: t("cases") },
    { href: "/scope", label: t("scope") },
  ] as const;

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur-md">
      {/* Three columns, not one row with an absolutely positioned middle. The old
          layout took the links out of the flow so they would stay centred whatever
          the wordmark did - and the right-hand group, which grows with the length of
          somebody's email address, simply overlapped them. A grid keeps the middle
          centred *and* gives it room nothing else may take. */}
      <div className="mx-auto grid h-14 max-w-6xl grid-cols-[auto_1fr_auto] items-center gap-4 px-6">
        <Link href="/" className="flex items-center gap-3">
          <Logo showWord={false} />
          <span className="text-[15px] font-semibold tracking-tight text-foreground">
            {t("appName")}
          </span>
        </Link>

        <nav className="hidden items-center justify-center gap-3 md:flex">
          {links.map((l) => {
            const active = pathname === l.href || (l.href !== "/" && pathname.startsWith(l.href));
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                  active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>

        {/* Signed in or not: the theme, the answer length and whether the browser
            keeps a chat history all work without an account, and the page itself
            says so by keeping working (`settings/page.tsx:119`). */}
        <div className="flex items-center justify-end gap-2">
          {session.status === "signed_in" ? (
            // One control instead of three. The address, the settings icon and a
            // Sign out button side by side grew with the length of somebody's
            // email until they overlapped the links; the account is one thing, so
            // it is one button, and what belongs to the account lives behind it.
            <DropdownMenu>
              <DropdownMenuTrigger
                className={cn(
                  "flex min-w-0 cursor-pointer items-center gap-2 rounded-md border border-border",
                  "px-2 py-1.5 text-sm font-medium text-muted-foreground transition-colors",
                  "hover:bg-accent hover:text-foreground focus-visible:outline-none",
                  "focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                <span
                  aria-hidden="true"
                  className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent text-xs font-semibold uppercase text-foreground"
                >
                  {initialOf(session.email)}
                </span>
                {/* The local part, not the whole address: it is what the user
                    recognises, and the domain is the half that overflows. The
                    full address is the first line of the menu. */}
                <span className="hidden max-w-36 truncate sm:inline">
                  {localPartOf(session.email)}
                </span>
                <ChevronDown className="size-4 shrink-0" aria-hidden="true" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuLabel className="font-normal">
                  <span className="block text-xs text-muted-foreground">{t("signedInAs")}</span>
                  <span className="block truncate text-sm font-medium text-foreground">
                    {session.email}
                  </span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild className="cursor-pointer">
                  <Link href="/settings">
                    <SlidersHorizontal className="size-4" aria-hidden="true" />
                    {t("settings")}
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="cursor-pointer"
                  onSelect={() => {
                    // A hard navigation, not router.push: it drops every piece of
                    // in-memory state that belonged to the signed-in user.
                    void signOut().finally(() => window.location.assign("/"));
                  }}
                >
                  {t("signOut")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : session.status === "loading" ? (
            // Neither control while the session is still being read: flashing
            // "Sign in" at a signed-in user is the bug this replaced.
            <span className="ml-auto" />
          ) : (
            <>
              {/* Settings is behind the account menu once there is an account. With
                  no account there is no menu, and the page works signed out, so the
                  icon stays: a page nobody can reach is the same as one that does
                  not exist (#18). */}
              <Link
                href="/settings"
                aria-label={t("settings")}
                title={t("settings")}
                className={cn(
                  "flex size-9 shrink-0 items-center justify-center rounded-md border",
                  "transition-colors",
                  pathname.startsWith("/settings")
                    ? "border-border-strong bg-accent text-foreground"
                    : "border-border text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <SlidersHorizontal className="size-4" aria-hidden="true" />
              </Link>
              <Link
                href="/login"
                className="shrink-0 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {t("signIn")}
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
