"use client";

import type { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";

import { isLiveBackend, supabase } from "@/lib/supabase";

export type SessionState = {
  // "loading" until Supabase has read localStorage — routing on a null session
  // before that signs the user out on every refresh.
  status: "loading" | "signed_in" | "signed_out" | "fixture";
  email: string | null;
};

export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>(
    isLiveBackend ? { status: "loading", email: null } : { status: "fixture", email: null },
  );

  useEffect(() => {
    if (!supabase) return;

    const apply = (session: Session | null) =>
      setState(
        session
          ? { status: "signed_in", email: session.user.email ?? null }
          : { status: "signed_out", email: null },
      );

    supabase.auth.getSession().then(({ data }) => apply(data.session));
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => apply(session));
    return () => sub.subscription.unsubscribe();
  }, []);

  return state;
}

export async function signOut(): Promise<void> {
  // scope "local": clear this browser's session and do not wait on the server.
  // The global variant makes a network call that can hang or 403 when the
  // session is already stale, and then the button looks dead.
  await supabase?.auth.signOut({ scope: "local" });
}
