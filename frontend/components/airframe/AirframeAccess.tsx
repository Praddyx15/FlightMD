"use client";

import { useState } from "react";
import { Check, Copy, Eye, EyeOff, KeyRound, Lock } from "lucide-react";
import { AirframeAuthError, updateAirframeConfig } from "@/lib/api";
import { forgetAirframeToken, getAirframeToken, setAirframeToken } from "@/lib/storage";
import { copyToClipboard } from "@/lib/utils";

// Shown instead of the airframe page when the API answers 401/403.
export function AirframeLocked({ label, error, onUnlocked }: { label: string; error: AirframeAuthError; onUnlocked: () => void }) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function claim() {
    setBusy(true);
    setMsg(null);
    try {
      await updateAirframeConfig(label, {});
      onUnlocked();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not claim this airframe.");
    } finally {
      setBusy(false);
    }
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setAirframeToken(label, token);
    onUnlocked();
  }

  if (error.unclaimed) {
    return (
      <div className="panel mx-auto max-w-xl space-y-3 p-5">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <KeyRound aria-hidden className="h-4 w-4 text-accent" />
          &quot;{label}&quot; is not claimed yet
        </h2>
        <p className="text-sm text-fg-muted">
          Claiming the label creates an access token for it. Only someone with the token can read its
          trend history or change its maintenance log, alerts and webhook. The token is saved in this
          browser; copy it somewhere safe to use it elsewhere.
        </p>
        {msg && <p role="alert" className="text-sm text-critical">{msg}</p>}
        <button type="button" onClick={claim} disabled={busy} className="btn-primary">
          Claim this airframe
        </button>
      </div>
    );
  }

  const wrong = error.status === 403 || !!getAirframeToken(label);

  return (
    <div className="panel mx-auto max-w-xl space-y-3 p-5">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <Lock aria-hidden className="h-4 w-4 text-caution" />
        {wrong ? "That access token doesn't match" : "This airframe needs its access token"}
      </h2>
      <p className="text-sm text-fg-muted">
        &quot;{label}&quot; belongs to whoever claimed it. Paste the token you saved when you claimed it.
      </p>
      <form onSubmit={save} className="flex flex-wrap gap-2">
        <label htmlFor="af-token" className="sr-only">Access token</label>
        <input
          id="af-token"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="input num min-w-0 flex-1"
          placeholder="Access token"
        />
        <button type="submit" className="btn-primary" disabled={!token.trim()}>Use token</button>
      </form>
      {wrong && (
        <button
          type="button"
          className="btn text-xs"
          onClick={() => {
            forgetAirframeToken(label);
            setToken("");
          }}
        >
          Forget the saved token
        </button>
      )}
    </div>
  );
}

// "token saved in this browser" line with reveal / copy / forget
export function AirframeTokenInfo({ label, onForget }: { label: string; onForget: () => void }) {
  const [shown, setShown] = useState(false);
  const [copied, setCopied] = useState(false);
  const token = getAirframeToken(label);
  if (!token) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
      <KeyRound aria-hidden className="h-3.5 w-3.5" />
      <span>Access token saved in this browser:</span>
      <code className="num rounded-sm bg-elevated px-1.5 py-0.5 text-fg">{shown ? token : "••••••••"}</code>
      <button type="button" className="btn px-2 text-xs" onClick={() => setShown((s) => !s)} aria-label={shown ? "Hide token" : "Show token"}>
        {shown ? <EyeOff aria-hidden className="h-3.5 w-3.5" /> : <Eye aria-hidden className="h-3.5 w-3.5" />}
      </button>
      <button
        type="button"
        className="btn px-2 text-xs"
        aria-label="Copy token"
        onClick={async () => {
          await copyToClipboard(token);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check aria-hidden className="h-3.5 w-3.5 text-ok" /> : <Copy aria-hidden className="h-3.5 w-3.5" />}
      </button>
      <button
        type="button"
        className="btn px-2 text-xs"
        onClick={() => {
          forgetAirframeToken(label);
          onForget();
        }}
      >
        Forget
      </button>
    </div>
  );
}
