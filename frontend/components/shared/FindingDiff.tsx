// Finding titles, with a repeated title shown once as "× n".
export function FindingDiff({
  title, icon, items, empty, heading = "h2",
}: {
  title: string;
  icon: React.ReactNode;
  items: string[];
  empty: string;
  heading?: "h2" | "h3" | "h4";
}) {
  const Heading = heading;
  const counts = new Map<string, number>();
  for (const item of items) counts.set(item, (counts.get(item) ?? 0) + 1);
  return (
    <section className="panel p-4">
      <Heading className="mb-2 flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title} <span className="num font-normal text-fg-muted">({items.length})</span>
      </Heading>
      {items.length === 0 ? (
        <p className="text-xs text-fg-muted">{empty}</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {Array.from(counts, ([text, n]) => (
            <li key={text}>
              {text}
              {n > 1 && <span className="num text-fg-muted"> × {n}</span>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
