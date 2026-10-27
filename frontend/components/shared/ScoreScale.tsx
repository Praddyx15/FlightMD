import { TONE_CLASSES, type Tone } from "@/lib/utils";
import { TONE_ICON } from "./SeverityBadge";

const SCORE_BANDS: { range: string; label: string; tone: Tone }[] = [
  { range: "90–100", label: "Excellent", tone: "ok" },
  { range: "80–89",  label: "Good",      tone: "ok" },
  { range: "60–79",  label: "Caution",   tone: "caution" },
  { range: "50–59",  label: "Warning",   tone: "caution" },
  { range: "0–49",   label: "Critical",  tone: "critical" },
];

const GRADES = [
  { range: "90–100", grade: "A" },
  { range: "80–89",  grade: "B" },
  { range: "70–79",  grade: "C" },
  { range: "60–69",  grade: "D" },
  { range: "50–59",  grade: "E" },
  { range: "0–49",   grade: "F" },
];

export function ScoreScale() {
  return (
    <div className="panel space-y-4 p-4">
      <div>
        <h3 className="mb-2 text-sm font-semibold">Overall score, 0–100, weighted across the modules that were assessed</h3>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {SCORE_BANDS.map((b) => {
            const Icon = TONE_ICON[b.tone];
            return (
              <li key={b.label} className={`rounded border px-2 py-1.5 ${TONE_CLASSES[b.tone]}`}>
                <div className="flex items-center gap-1 text-xs font-semibold">
                  <Icon aria-hidden className="h-3.5 w-3.5" />
                  {b.label}
                </div>
                <div className="num text-2xs text-fg-muted">{b.range}</div>
              </li>
            );
          })}
        </ul>
      </div>

      <div>
        <h3 className="mb-2 text-sm font-semibold">Letter grade: the same score on an A–F scale</h3>
        <ul className="grid grid-cols-3 gap-2 sm:grid-cols-6">
          {GRADES.map((g) => (
            <li key={g.grade} className="rounded border bg-elevated px-2 py-1.5 text-center">
              <div className="text-sm font-semibold">{g.grade}</div>
              <div className="num text-2xs text-fg-muted">{g.range}</div>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-xs text-fg-muted">
        Oscillation, vibration and EKF weigh 20 % each; battery and GPS 15 % each; parameters and
        motors 5 % each. Ascent &amp; Recovery (rockets, balloons) is situational and not weighted.
        A module that could not be assessed is left out of the score and shown as &quot;Not
        assessed&quot;, never as 100.
      </p>
    </div>
  );
}
