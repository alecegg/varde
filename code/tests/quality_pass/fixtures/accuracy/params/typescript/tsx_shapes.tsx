interface Props {
  title: string;
  count?: number;
}

export function Badge({ title, count = 0 }: Props) {
  return (
    <span>
      {title}:{count}
    </span>
  );
}

export function List({
  items,
  onPick,
}: {
  items: string[];
  onPick: (index: number) => void;
}) {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={item} onClick={() => onPick(index)}>
          {item}
        </li>
      ))}
    </ul>
  );
}

export const Wrapped = ({ label }: { label: string }) => <b>{label}</b>;
