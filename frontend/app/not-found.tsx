import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-4 py-20 text-center">
      <h1 className="mb-2 text-value font-semibold">Page not found</h1>
      <p className="text-sm text-fg-muted">There is nothing at this address.</p>
      <Link href="/" className="btn mt-6">Analyse a log</Link>
    </div>
  );
}
