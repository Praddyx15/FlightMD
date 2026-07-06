import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { SmoothScroll } from "@/components/shared/SmoothScroll";
import PillNav from "@/components/shared/PillNav";
import Lightfall from "@/components/shared/Lightfall";
import "./globals.css";

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
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-screen">
        <div className="fixed inset-0 -z-10 pointer-events-none">
          <Lightfall
            colors={["#B89642", "#E7C25B", "#D1AE52"]}
            backgroundColor="#0A0A0A"
            speed={0.4}
            streakCount={3}
            streakWidth={1.2}
            streakLength={1.4}
            glow={1.2}
            density={0.45}
            twinkle={1.0}
            zoom={2.5}
            backgroundGlow={0.5}
            opacity={0.6}
            mouseInteraction={false}
          />
        </div>
        <SmoothScroll />
        <div className="sticky top-0 z-50 w-full py-4 flex justify-center pointer-events-none [&>*]:pointer-events-auto">
          <PillNav
            logo="https://api.iconify.design/clarity:airplane-solid.svg?color=%23B89642"
            logoAlt="FlightMD Logo"
            items={[
              { label: 'Home', href: '/' },
              { label: 'GitHub', href: 'https://github.com/Praddyx15/FlightMD' },
              { label: 'API Docs', href: 'https://flightmd-api.onrender.com/docs' }
            ]}
            baseColor="#111111"
            pillColor="#B89642"
            hoveredPillTextColor="#0A0A0A"
            pillTextColor="#F5F5F2"
            initialLoadAnimation={true}
          />
        </div>
        <main>{children}</main>
        <footer className="border-t border-white/8 py-6 text-center text-xs text-white/70 mt-16">
          FlightMD v1.0 · MIT License · Pradum Behl · India
          <br className="sm:hidden" />
          <span className="hidden sm:inline"> · </span>
          Reports expire after 1 hour · No data stored permanently
        </footer>
      </body>
    </html>
  );
}
