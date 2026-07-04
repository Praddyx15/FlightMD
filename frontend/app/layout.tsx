import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FlightMD — Your drone's flight log, decoded.",
  description:
    "Upload a PX4 ULog file and receive an AI-powered diagnostic report in 20 seconds. " +
    "Oscillation detection, vibration analysis, EKF health, battery assessment, GPS quality, " +
    "parameter anomaly detection, and motor balance — all in plain English.",
  keywords: ["PX4", "ULog", "drone", "flight log", "analysis", "UAV", "diagnostics", "FlightMD"],
  authors: [{ name: "Sixty Motion Aerospace", url: "https://sixtymotion.aero" }],
  openGraph: {
    title: "FlightMD — Your drone's flight log, decoded.",
    description: "AI-powered PX4 flight log diagnostics.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">
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
