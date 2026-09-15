import type { Metadata } from "next";
import { LandingContent } from "@/components/gta/landing-content";

export const metadata: Metadata = {
  title: "German Tax Assistant: understand German taxes, in plain language",
  description:
    "An AI assistant that explains German tax law in plain English, cites official sources, and guides you through your Steuererklärung.",
  openGraph: {
    title: "German Tax Assistant",
    description:
      "Understand German taxes without the jargon. Ask questions, get cited answers from official German sources.",
  },
};

export default function Landing() {
  return <LandingContent />;
}
