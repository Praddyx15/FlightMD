export default function Loading() {
  return (
    <div className="mx-auto max-w-5xl space-y-4 px-4 py-8" aria-busy="true">
      <p className="sr-only" role="status">Loading report</p>
      <div className="panel h-40 animate-pulse" />
      <div className="panel h-24 animate-pulse" />
      <div className="panel h-24 animate-pulse" />
    </div>
  );
}
