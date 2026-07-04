import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import { SmoothScroll } from "@/components/shared/SmoothScroll";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "FlightMD — Your drone's flight log, decoded.",
  description:
    "Upload a PX4, ArduPilot, or MAVLink telemetry flight log and receive a " +
    "deterministic diagnostic report in seconds — no AI required. " +
    "Oscillation detection, vibration analysis, EKF health, battery assessment, GPS quality, " +
    "parameter anomaly detection, and motor balance — all in plain English.",
  keywords: ["PX4", "ArduPilot", "MAVLink", "ULog", "drone", "UAV", "flight log", "analysis", "diagnostics", "FlightMD"],
  authors: [{ name: "Sixty Motion Aerospace", url: "https://sixtymotion.aero" }],
  openGraph: {
    title: "FlightMD — Your drone's flight log, decoded.",
    description: "Deterministic drone flight log diagnostics for PX4, ArduPilot, and MAVLink.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={spaceGrotesk.variable}>
      <body className="min-h-screen">
        <SmoothScroll />
        <nav className="border-b border-white/8 px-6 py-3 flex items-center justify-between sticky top-0 z-50"
          style={{ background: "rgba(8,13,26,0.92)", backdropFilter: "blur(12px)" }}>
          <a href="/" className="flex items-center gap-2 no-underline">
            <span className="text-lg font-bold tracking-wider" style={{ color: "#E8A020" }}>
              ✈ FLIGHTMD
            </span>
            <span className="text-xs text-white/40 hidden sm:inline">
              by Sixty Motion Aerospace
            </span>
          </a>
          <div className="flex items-center gap-4 text-sm text-white/50">
            <a
              href="https://github.com/sixtymotion/flightmd"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-white/80 transition-colors"
            >
              GitHub
            </a>
            <a
              href="https://flightmd-api.onrender.com/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-white/80 transition-colors"
            >
              API Docs
            </a>
          </div>
        </nav>
        <main>{children}</main>
        <footer className="border-t border-white/8 py-6 text-center text-xs text-white/30 mt-16">
          FlightMD v1.0 · MIT License · Sixty Motion Aerospace · India
          <br className="sm:hidden" />
          <span className="hidden sm:inline"> · </span>
          Reports expire after 1 hour · No data stored permanently
        </footer>
      </body>
    </html>
  );
}
