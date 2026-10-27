import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Activity } from "lucide-react";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { themeInitScript } from "@/lib/themeScript";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "FlightMD: drone flight log diagnostics",
    template: "%s · FlightMD",
  },
  description:
    "Upload a PX4, ArduPilot or MAVLink telemetry log and get a deterministic diagnostic " +
    "report: oscillation, vibration, EKF health, battery, GPS, parameters and motors, with " +
    "the parameter changes to make.",
  keywords: ["PX4", "ArduPilot", "MAVLink", "ULog", "drone", "UAV", "flight log", "analysis", "diagnostics", "FlightMD"],
  authors: [{ name: "Pradum Behl", url: "https://github.com/Praddyx15" }],
  openGraph: {
    title: "FlightMD",
    description: "Deterministic drone flight log diagnostics for PX4, ArduPilot and MAVLink.",
    type: "website",
  },
};

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

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
      </head>
      <body className="flex min-h-dvh flex-col">
        <a href="#main" className="skip-link">Skip to main content</a>

        <header className="no-print border-b bg-surface">
          <nav aria-label="Site" className="mx-auto flex h-12 max-w-5xl items-center gap-4 px-4">
            <Link href="/" className="flex items-center gap-2 font-medium text-fg no-underline">
              <Activity aria-hidden className="h-5 w-5 text-accent" />
              flightmd
            </Link>
            <div className="ml-auto flex items-center gap-1 text-sm">
              <a href={REPO} className="btn border-transparent bg-transparent text-fg-muted hover:text-fg" rel="noopener noreferrer">
                GitHub
              </a>
              {API_DOCS && (
                <a href={API_DOCS} className="btn hidden border-transparent bg-transparent text-fg-muted hover:text-fg sm:inline-flex" rel="noopener noreferrer">
                  API docs
                </a>
              )}
              <ThemeToggle />
            </div>
          </nav>
        </header>

        <main id="main" tabIndex={-1} className="flex-1 focus:outline-none">
          {children}
        </main>

        <footer className="no-print mt-16 border-t py-6 text-xs text-fg-muted">
          <div className="mx-auto flex max-w-5xl flex-col gap-1 px-4 sm:flex-row sm:flex-wrap sm:justify-between">
            <p>Part of the UAV suite: FlightMD · AeroAtlas · UAOP</p>
            <p>
              MIT License · Pradum Behl · Untagged reports expire after 1 hour
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
