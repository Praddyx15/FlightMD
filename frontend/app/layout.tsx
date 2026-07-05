import type { Metadata } from "next";
import { Space_Grotesk } from "next/font/google";
import { SmoothScroll } from "@/components/shared/SmoothScroll";
import PillNav from "@/components/shared/PillNav";
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
  authors: [{ name: "Pradum Behl", url: "https://github.com/Praddyx15" }],
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
        <div className="sticky top-0 z-50 w-full py-4 bg-[#060B08]/85 backdrop-blur-md border-b border-white/5 flex justify-center">
          <PillNav
            logo="https://api.iconify.design/clarity:airplane-solid.svg?color=%238ec970"
            logoAlt="FlightMD Logo"
            items={[
              { label: 'Home', href: '/' },
              { label: 'GitHub', href: 'https://github.com/Praddyx15/FlightMD' },
              { label: 'API Docs', href: 'https://flightmd-api.onrender.com/docs' }
            ]}
            baseColor="#060B08"
            pillColor="#8EC970"
            hoveredPillTextColor="#060B08"
            pillTextColor="#8EC970"
            initialLoadAnimation={true}
          />
        </div>
        <main>{children}</main>
        <footer className="border-t border-white/8 py-6 text-center text-xs text-white/30 mt-16">
          FlightMD v1.0 · MIT License · Pradum Behl · India
          <br className="sm:hidden" />
          <span className="hidden sm:inline"> · </span>
          Reports expire after 1 hour · No data stored permanently
        </footer>
      </body>
    </html>
  );
}
