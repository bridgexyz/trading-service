const config: Record<string, { bg: string; text: string; dot: string }> = {
  active: {
    bg: "bg-accent/8 border-accent/20",
    text: "text-accent",
    dot: "bg-accent shadow-[0_0_6px_var(--color-accent)]",
  },
  paused: {
    bg: "bg-warning/8 border-warning/20",
    text: "text-warning",
    dot: "bg-warning",
  },
  error: {
    bg: "bg-negative/8 border-negative/20",
    text: "text-negative",
    dot: "bg-negative shadow-[0_0_6px_var(--color-negative)]",
  },
  success: {
    bg: "bg-accent/8 border-accent/20",
    text: "text-accent",
    dot: "bg-accent shadow-[0_0_6px_var(--color-accent)]",
  },
  flat: {
    bg: "bg-surface-3/50 border-border-default",
    text: "text-text-secondary",
    dot: "bg-text-muted",
  },
};

interface Props {
  status: string;
}

export default function StatusBadge({ status }: Props) {
  const c = config[status] ?? config.flat;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-[10px] font-medium font-mono uppercase tracking-[0.12em] ${c.bg} ${c.text}`}
    >
      <span className={`w-1 h-1 rounded-full ${c.dot}`} />
      {status}
    </span>
  );
}
