import type { ReactNode } from "react";

import { CaseShell } from "@/components/cases/case-shell";

export default function TaxCaseLayout({ children }: { children: ReactNode }) {
  return <CaseShell>{children}</CaseShell>;
}
