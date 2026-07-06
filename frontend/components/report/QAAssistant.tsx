import React, { useState } from "react";
import { FlightMDReport, Finding } from "../../lib/types";
import { askAI } from "../../lib/api";
import { Search, Sparkles, AlertCircle, CheckCircle2, ArrowRight } from "lucide-react";

interface QAAssistantProps {
  report: FlightMDReport;
}

interface QAResponse {
  query: string;
  answer: string;
  matchedFindings: Finding[];
  matchedParams: any[];
  aiPowered?: boolean;
}

export default function QAAssistant({ report }: QAAssistantProps) {
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<QAResponse[]>([]);
  const [useAI, setUseAI] = useState(false);
  const [aiUnavailable, setAiUnavailable] = useState(false);
  const [thinking, setThinking] = useState(false);

  const handleSearch = async (text: string) => {
    if (!text.trim()) return;

    if (useAI && !aiUnavailable) {
      setThinking(true);
      try {
        const result = await askAI(report.report_id, text);
        if (!result.configured) {
          // Backend has no AI key configured — fall back to local search
          // for this and future questions in this session.
          setAiUnavailable(true);
        } else {
          setHistory((prev) => [
            ...prev,
            {
              query: text,
              answer: result.answer || "The AI assistant did not return an answer.",
              matchedFindings: [],
              matchedParams: [],
              aiPowered: true,
            },
          ]);
          setQuery("");
          setThinking(false);
          return;
        }
      } catch {
        // Network/server error — fall back to local keyword search below.
        setAiUnavailable(true);
      }
      setThinking(false);
    }

    handleLocalSearch(text);
  };

  const handleLocalSearch = (text: string) => {
    const lowerQuery = text.toLowerCase();
    let answer = "";
    let matchedFindings: Finding[] = [];
    let matchedParams: any[] = [];

    // Rule-based responses for PX4 domain
    if (lowerQuery.includes("oscillation") || lowerQuery.includes("wobble") || lowerQuery.includes("shake")) {
      const oscResult = report.analyser_results.find(r => r.analyser === "OscillationAnalyser");
      matchedFindings = report.findings.filter(f => f.category === "oscillation");
      const score = oscResult ? oscResult.health_score : 100;

      answer = `Oscillation Analysis (Module Health: ${score}/100): `;
      if (matchedFindings.length > 0) {
        answer += `Detected active oscillations. Standard causes include loose airframe joints, incorrect PID gains (MC_ROLLRATE_P, MC_PITCHRATE_P), or excessive actuator lag.`;
      } else {
        answer += `No significant control loop oscillations detected in this flight. Control surfaces and gains appear stable.`;
      }
    } else if (lowerQuery.includes("battery") || lowerQuery.includes("voltage") || lowerQuery.includes("power") || lowerQuery.includes("sag")) {
      const batResult = report.analyser_results.find(r => r.analyser === "BatteryAnalyser");
      matchedFindings = report.findings.filter(f => f.category === "battery");
      const score = batResult ? batResult.health_score : 100;

      answer = `Battery & Power Analysis (Module Health: ${score}/100): `;
      if (matchedFindings.length > 0) {
        answer += `Identified power delivery or cell health issues. Check for voltage sag under load, potential high internal resistance, or capacity fade.`;
      } else {
        answer += `Battery performance is healthy. Nominal cell voltages and sag thresholds were respected.`;
      }
    } else if (lowerQuery.includes("vibration") || lowerQuery.includes("clip") || lowerQuery.includes("accel") || lowerQuery.includes("imu")) {
      const vibResult = report.analyser_results.find(r => r.analyser === "VibrationAnalyser");
      matchedFindings = report.findings.filter(f => f.category === "vibration");
      const score = vibResult ? vibResult.health_score : 100;

      answer = `Vibration & IMU Analysis (Module Health: ${score}/100): `;
      if (matchedFindings.length > 0) {
        answer += `Vibrations exceed safe limits. High high-frequency vibration causes sensor clipping, estimator drift (EKF failures), and motor overheating. Balance props and verify dampening.`;
      } else {
        answer += `IMU vibration levels are well within the acceptable threshold (under 30 m/s² peak). Dampening is excellent.`;
      }
    } else if (lowerQuery.includes("gps") || lowerQuery.includes("satellites") || lowerQuery.includes("jamming") || lowerQuery.includes("spoofing")) {
      const gpsResult = report.analyser_results.find(r => r.analyser === "GPSAnalyser");
      matchedFindings = report.findings.filter(f => f.category === "gps");
      const score = gpsResult ? gpsResult.health_score : 100;

      answer = `GPS & Jamming Analysis (Module Health: ${score}/100): `;
      if (matchedFindings.length > 0) {
        answer += `GPS anomalies found. Inspect satellite count drops, HDOP spikes, or jamming flags which indicate signal interference or antenna shielding.`;
      } else {
        answer += `GPS fix type was sustained at 3D/DGPS with stable satellite visibility and zero jamming/spoofing indicators.`;
      }
    } else if (lowerQuery.includes("param") || lowerQuery.includes("tune") || lowerQuery.includes("change") || lowerQuery.includes("recommend")) {
      matchedParams = report.param_change_sheet;
      answer = `Parameter Change Recommendations: `;
      if (matchedParams.length > 0) {
        answer += `Identified ${matchedParams.length} parameters requiring adjustments based on flight performance. Refer to the list below to update PX4 configurations.`;
      } else {
        answer += `No parameter adjustments recommended. All system configurations are aligned with observed flight characteristics.`;
      }
    } else {
      // General text matching
      matchedFindings = report.findings.filter(f =>
        f.title.toLowerCase().includes(lowerQuery) ||
        f.plain_english.toLowerCase().includes(lowerQuery) ||
        f.recommendation.toLowerCase().includes(lowerQuery)
      );

      matchedParams = report.param_change_sheet.filter(p =>
        p.param_name.toLowerCase().includes(lowerQuery) ||
        p.reason.toLowerCase().includes(lowerQuery)
      );

      if (matchedFindings.length > 0 || matchedParams.length > 0) {
        answer = `Found relevant flight records matching "${text}":`;
      } else {
        answer = `No specific matching findings or parameters found for "${text}". Try asking about "battery", "vibrations", "oscillations", or "gps".`;
      }
    }

    setHistory(prev => [
      ...prev,
      { query: text, answer, matchedFindings, matchedParams }
    ]);
    setQuery("");
  };

  const presets = [
    "Check for oscillations",
    "Analyze vibration levels",
    "Show battery health status",
    "List param change suggestions"
  ];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-6">
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div className="flex items-center space-x-2">
          <div className="p-2 bg-gold-500/10 text-gold-500 rounded-lg">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-slate-100">Q&A Assistant</h3>
            <p className="text-xs text-slate-400">
              {useAI && !aiUnavailable
                ? "AI-powered — grounded in this report's own data"
                : "Local keyword search over findings & parameter recommendations"}
            </p>
          </div>
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer select-none">
          <span>Ask AI</span>
          <button
            type="button"
            role="switch"
            aria-checked={useAI && !aiUnavailable}
            disabled={aiUnavailable}
            onClick={() => setUseAI((v) => !v)}
            className={`relative h-5 w-9 rounded-full transition-colors ${
              useAI && !aiUnavailable ? "bg-gold-600" : "bg-slate-700"
            } ${aiUnavailable ? "opacity-40 cursor-not-allowed" : ""}`}
            title={aiUnavailable ? "AI assistant is not configured on this server" : ""}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                useAI && !aiUnavailable ? "translate-x-4.5" : "translate-x-0.5"
              }`}
            />
          </button>
        </label>
      </div>

      {/* History */}
      <div className="space-y-4 max-h-[350px] overflow-y-auto pr-2 custom-scrollbar">
        {history.length === 0 && !thinking ? (
          <div className="text-center py-6 text-slate-500 text-sm">
            Ask a question below or use a preset to analyze your flight log.
          </div>
        ) : (
          history.map((item, idx) => (
            <div key={idx} className="space-y-3 border-b border-slate-800/50 pb-4 last:border-0 last:pb-0">
              <div className="flex justify-end">
                <div className="bg-gold-600/90 text-white rounded-2xl rounded-tr-none px-4 py-2 text-sm max-w-[80%] shadow-md">
                  {item.query}
                </div>
              </div>
              <div className="flex justify-start">
                <div className="bg-slate-850 border border-slate-800 text-slate-200 rounded-2xl rounded-tl-none px-4 py-3 text-sm max-w-[90%] shadow-sm space-y-3">
                  <p>{item.answer}</p>
                  
                  {item.matchedFindings.length > 0 && (
                    <div className="mt-2 space-y-2">
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Related Findings</p>
                      {item.matchedFindings.map((f, fIdx) => (
                        <div key={fIdx} className="flex items-start space-x-2 bg-slate-900/50 p-2 rounded-lg border border-slate-800">
                          <AlertCircle className={`w-4 h-4 mt-0.5 flex-shrink-0 ${
                            f.severity === "critical" ? "text-rose-400" : "text-amber-400"
                          }`} />
                          <div>
                            <p className="text-xs font-medium text-slate-200">{f.title}</p>
                            <p className="text-xxs text-slate-400 line-clamp-2">{f.plain_english}</p>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {item.matchedParams.length > 0 && (
                    <div className="mt-2 space-y-2">
                      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Parameter Recommendations</p>
                      {item.matchedParams.map((p, pIdx) => (
                        <div key={pIdx} className="bg-slate-900/50 p-2 rounded-lg border border-slate-800 flex items-center justify-between">
                          <div>
                            <span className="text-xs font-mono text-gold-500">{p.param_name}</span>
                            <p className="text-xxs text-slate-400">{p.reason}</p>
                          </div>
                          <div className="text-right text-xs">
                            <span className="text-slate-400">{p.current_value}</span>
                            <ArrowRight className="w-3 h-3 inline mx-1 text-slate-500" />
                            <span className="text-emerald-400 font-semibold">{p.suggested_value}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
        {thinking && (
          <div className="flex justify-start">
            <div className="bg-slate-850 border border-slate-800 text-slate-400 rounded-2xl rounded-tl-none px-4 py-3 text-sm flex items-center gap-2">
              <span className="flex gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-gold-500 animate-bounce [animation-delay:-0.3s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-gold-500 animate-bounce [animation-delay:-0.15s]" />
                <span className="w-1.5 h-1.5 rounded-full bg-gold-500 animate-bounce" />
              </span>
              Thinking…
            </div>
          </div>
        )}
      </div>

      {/* Presets */}
      <div className="flex flex-wrap gap-2">
        {presets.map((preset, idx) => (
          <button
            key={idx}
            disabled={thinking}
            onClick={() => handleSearch(preset)}
            className="text-xs bg-slate-800/60 hover:bg-gold-900/40 hover:text-gold-300 border border-slate-700/60 hover:border-gold-700/80 text-slate-300 rounded-full px-3 py-1.5 transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {preset}
          </button>
        ))}
      </div>

      {/* Input */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSearch(query);
        }}
        className="flex items-center space-x-2"
      >
        <div className="relative flex-1">
          <input
            type="text"
            value={query}
            disabled={thinking}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask about oscillations, vibration thresholds, battery cells..."
            className="w-full bg-slate-950 border border-slate-800 focus:border-gold-500 focus:ring-1 focus:ring-gold-500 text-slate-200 rounded-xl px-4 py-3 pl-10 text-sm outline-none transition-all disabled:opacity-50"
          />
          <Search className="w-4 h-4 text-slate-500 absolute left-3 top-3.5" />
        </div>
        <button
          type="submit"
          disabled={thinking}
          className="bg-gold-600 hover:bg-gold-500 text-white rounded-xl px-5 py-3 text-sm font-semibold transition-all duration-200 shadow-lg shadow-gold-600/20 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </form>
    </div>
  );
}
