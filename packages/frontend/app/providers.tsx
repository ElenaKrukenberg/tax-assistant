"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useMemo } from "react";
import { LocaleProvider } from "@/i18n/locale-provider";
import { ThemeProvider } from "@/components/theme-provider";

export function Providers({ children }: { children: ReactNode }) {
  const queryClient = useMemo(() => new QueryClient(), []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <LocaleProvider>{children}</LocaleProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
