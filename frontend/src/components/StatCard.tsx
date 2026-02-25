interface Props {
  label: string;
  value: string | number;
  color?: string;
}

export default function StatCard({ label, value, color }: Props) {
  return (
    <div className="bg-surface-1 border border-border-default rounded-lg px-4 py-3.5 min-w-[130px] card-hover relative overflow-hidden group">
      {/* Subtle top accent line */}
      <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-accent/20 to-transparent" />
      <p className="text-[10px] text-text-secondary uppercase tracking-[0.15em] font-medium mb-1.5 font-mono">
        {label}
      </p>
      <p className={`text-xl font-semibold font-mono tracking-tight ${color ?? "text-text-primary"}`}>
        {value}
      </p>
    </div>
  );
}
