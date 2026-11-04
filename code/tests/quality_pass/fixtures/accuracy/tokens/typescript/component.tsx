interface PanelProps {
  title: string;
  items: string[];
  onSelect?: (index: number) => void;
}

export function Panel({ title, items, onSelect }: PanelProps) {
  const empty = items.length === 0;
  return (
    <section className="panel">
      <h1>{title}</h1>
      {empty ? (
        <p>No items yet</p>
      ) : (
        <ul>
          {items.map((item, index) => (
            <li key={item} onClick={() => onSelect && onSelect(index)}>
              {item}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Badge({ label }: { label: string }) {
  return <span className="badge">{label.toUpperCase()}</span>;
}
