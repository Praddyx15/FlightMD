import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Activity } from "lucide-react";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { UnitsToggle } from "@/components/shared/UnitsToggle";
import { themeInitScript } from "@/lib/themeScript";
import { SUITE_NAME } from "@/lib/suite";
import "./tokens.css";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("meta");
  return {
    title: {
      default: t("title"),
      template: "%s · FlightMD",
    },
    description: t("description"),
    keywords: ["PX4", "ArduPilot", "MAVLink", "ULog", "drone", "UAV", "flight log", "analysis", "diagnostics", "FlightMD"],
    authors: [{ name: "Pradum Behl", url: "https://github.com/Praddyx15" }],
    openGraph: {
      title: "FlightMD",
      description: t("ogDescription"),
      type: "website",
    },
  };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b0e11" },
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
  ],
};

const REPO = "https://github.com/Praddyx15/FlightMD";
const API_DOCS = process.env.NEXT_PUBLIC_API_URL ? `${process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, "")}/docs` : null;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const messages = await getMessages();
  const t = await getTranslations("layout");

  return (
    <html lang={locale} className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-dvh flex-col">
        <NextIntlClientProvider locale={locale} messages={messages}>
          <a href="#main" className="skip-link">{t("skip")}</a>

          <header className="no-print border-b bg-surface">
            <nav aria-label={t("nav")} className="mx-auto flex h-12 max-w-5xl items-center gap-4 px-4">
              <Link href="/" className="flex items-center gap-2 font-medium text-fg no-underline">
                <Activity aria-hidden className="h-5 w-5 text-accent" />
                flightmd
                <span className="hidden border-l pl-2 font-normal text-fg-muted sm:inline">{SUITE_NAME}</span>
              </Link>
              <div className="ml-auto flex items-center gap-1 text-sm">
                <a href={REPO} className="btn border-transparent bg-transparent text-fg-muted hover:text-fg" rel="noopener noreferrer">
                  {t("github")}
                </a>
                {API_DOCS && (
                  <a href={API_DOCS} className="btn hidden border-transparent bg-transparent text-fg-muted hover:text-fg sm:inline-flex" rel="noopener noreferrer">
                    {t("apiDocs")}
                  </a>
                )}
                <UnitsToggle />
                <ThemeToggle />
              </div>
            </nav>
          </header>

          <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
            {children}
          </main>

          <footer className="no-print mt-16 border-t py-6 text-xs text-fg-muted">
            <div className="mx-auto flex max-w-5xl flex-col gap-1 px-4 sm:flex-row sm:flex-wrap sm:justify-between">
              <p>{t("suite", { suite: SUITE_NAME })}</p>
              <p>{t("license")}</p>
            </div>
          </footer>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
