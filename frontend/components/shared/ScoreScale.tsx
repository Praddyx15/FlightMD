const SCORE_LABEL_BANDS = [
  { range: "90–100", label: "Excellent", colour: "#0DD97C" },
  { range: "75–89",  label: "Good",      colour: "#3A9CF8" },
  { range: "60–74",  label: "Caution",   colour: "#B89642" },
  { range: "40–59",  label: "Warning",   colour: "#FF7A2F" },
  { range: "0–39",   label: "Critical",  colour: "#FF3D3D" },
];

const LETTER_GRADE_BANDS = [
  { range: "90–100", grade: "A", colour: "#0DD97C" },
  { range: "80–89",  grade: "B", colour: "#3A9CF8" },
  { range: "70–79",  grade: "C", colour: "#B89642" },
  { range: "60–69",  grade: "D", colour: "#B89642" },
  { range: "50–59",  grade: "E", colour: "#FF7A2F" },
  { range: "0–49",   grade: "F", colour: "#FF3D3D" },
];

export function ScoreScale() {
  return (
    <div className="rounded-2xl border border-border bg-card/60 p-5 sm:p-6 backdrop-blur-sm space-y-5">
      <div>
        <h3 className="text-sm font-semibold text-white/80 mb-3">
          Overall score (0–100), weighted across all applicable modules
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {SCORE_LABEL_BANDS.map((b) => (
            <div
              key={b.label}
              className="rounded-lg px-3 py-2 text-center"
              style={{ background: `${b.colour}18`, border: `1px solid ${b.colour}40` }}
            >
              <div className="text-xs font-bold" style={{ color: b.colour }}>
                {b.label}
              </div>
              <div className="text-[10px] text-white/50 mono mt-0.5">{b.range}</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="text-sm font-semibold text-white/80 mb-3">
          Letter grade — same score, mapped to a familiar A–F scale
        </h3>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
          {LETTER_GRADE_BANDS.map((b) => (
            <div
              key={b.grade}
              className="rounded-lg px-3 py-2 text-center"
              style={{ background: `${b.colour}18`, border: `1px solid ${b.colour}40` }}
            >
              <div className="text-sm font-bold" style={{ color: b.colour }}>
                {b.grade}
              </div>
              <div className="text-[10px] text-white/50 mono mt-0.5">{b.range}</div>
            </div>
          ))}
        </div>
      </div>

      <p className="text-xs text-white/50 leading-relaxed">
        Oscillation, vibration, and EKF each weigh 20% of the overall score; battery and GPS
        each weigh 15%; parameters and motors each weigh 5%. Ascent &amp; Recovery Analysis
        (rockets/HABs) is situational and isn&apos;t counted in the weighted score.
      </p>
    </div>
  );
}
