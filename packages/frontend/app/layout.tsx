import type { Metadata, Viewport } from "next";
import { Inter, Instrument_Serif } from "next/font/google";
import type { ReactNode } from "react";
import "../src/styles.css";
import { Providers } from "./providers";
import { THEME_BOOT_SCRIPT } from "../src/lib/preferences";
import { Analytics } from "@vercel/analytics/next";

// Fonts are fetched at build time and served from our own origin. Three reasons this
// beats the <link> to fonts.googleapis.com it replaces: the visitor's browser no longer
// requests anything from Google, so their IP address never reaches a third party — the
// point German courts have ruled on; next/font emits a fallback with adjusted metrics,
// so the swap no longer shifts the layout; and the render-blocking stylesheet round trip
// to a second origin is gone. Instrument Serif needs an explicit weight because it is
// not a variable font, and italic because the landing headline sets it.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
  variable: "--font-instrument-serif",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0b1220",
};

export const metadata: Metadata = {
  metadataBase: new URL("https://taxassistant.app"),
  title: "German Tax Assistant",
  description:
    "An AI assistant that explains German tax law in plain English, cites official sources, and guides you through your Steuererklärung.",
  openGraph: {
    type: "website",
    title: "German Tax Assistant",
    description:
      "Understand German taxes without the jargon. Ask questions, get cited answers from official German sources.",
  },
  twitter: {
    card: "summary_large_image",
  },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${instrumentSerif.variable}`}
      suppressHydrationWarning
    >
      {/* favicon: app/icon.svg is auto-served by the App Router */}
      <head>
        {/* Paint the right palette before React hydrates. Without this a dark-theme
            user gets a white flash on every navigation, because the class that
            carries the palette can only be set once the stored choice is read and
            localStorage does not exist on the server. dangerouslySetInnerHTML is
            how Next allows a blocking inline script; the content is a constant in
            src/lib/preferences.ts and interpolates nothing. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
        <Analytics />
      </body>
    </html>
  );
}
