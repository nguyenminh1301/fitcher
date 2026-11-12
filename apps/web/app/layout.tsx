import type { Metadata } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import { I18nProvider } from "@/lib/i18n/react";
import { ThemeProvider } from "@/lib/theme";

import "./globals.css";

const inter = Inter({ subsets: ["latin", "vietnamese"], weight: ["400", "500", "600"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "fitcher",
  description: "Ask your data in plain language; every number comes from a query you can open.",
  icons: { icon: "/brand/favicon.svg" },
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <I18nProvider>{children}</I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
