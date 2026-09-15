import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Null when the env vars are absent, and every screen treats null as "fixture
// mode": the workspace stays browsable for anyone who cloned the repo without a
// Supabase project, which is also what the Vitest suite runs against.
const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const supabase: SupabaseClient | null = url && anonKey ? createClient(url, anonKey) : null;

export const isLiveBackend = supabase !== null;
