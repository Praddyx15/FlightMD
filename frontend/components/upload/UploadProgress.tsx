"use client";

interface Props {
  progress: number;
}

export function UploadProgress({ progress }: Props) {
  return (
    <div className="text-center py-4">
      <div className="text-3xl mb-4">🚀</div>
      <p className="text-white/70 font-medium mb-4">Uploading flight log…</p>
      <div className="w-full h-2 rounded-full bg-white/10 overflow-hidden mb-2">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{
            width: `${progress}%`,
            background: "linear-gradient(90deg, #B89642, #E7C25B)",
          }}
        />
      </div>
      <div className="text-xs text-white/30 font-mono">{progress}%</div>
    </div>
  );
}
