import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/components/shared/providers";
import { themeBootstrapScript } from "@/lib/theme/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cognitrix — AI-Native Analytics",
  description: "Conversational AI analytics for any structured dataset. Ask questions, generate charts, compose reports.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className="antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrapScript() }} />
      </head>
      <body className="min-h-screen bg-parchment text-near-black font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
