interface Option<T extends string> {
  value: T;
  label: string;
  /** Shorter label for narrow screens (the full one stays the accessible name). */
  short?: string;
}

interface Props<T extends string> {
  label: string;
  value: T;
  options: Option<T>[];
  onChange: (value: T) => void;
}

/** Accessible segmented control (radiogroup) with a sliding thumb. */
export function Segmented<T extends string>({ label, value, options, onChange }: Props<T>) {
  const index = Math.max(0, options.findIndex((o) => o.value === value));
  const onKey = (e: React.KeyboardEvent) => {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = options[(index + step + options.length) % options.length]!;
    onChange(next.value);
    const group = e.currentTarget as HTMLElement;
    requestAnimationFrame(() => group.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
  };
  return (
    <div
      className="segmented"
      role="radiogroup"
      aria-label={label}
      onKeyDown={onKey}
      style={{ ["--count" as string]: options.length, ["--index" as string]: index }}
    >
      <span className="segmented__thumb" aria-hidden />
      {options.map((o) => {
        const checked = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-label={o.short ? o.label : undefined}
            tabIndex={checked ? 0 : -1}
            className={checked ? "is-selected" : ""}
            onClick={() => onChange(o.value)}
          >
            {o.short ? (
              <>
                <span className="segmented__full">{o.label}</span>
                <span className="segmented__short" aria-hidden>{o.short}</span>
              </>
            ) : (
              o.label
            )}
          </button>
        );
      })}
    </div>
  );
}
