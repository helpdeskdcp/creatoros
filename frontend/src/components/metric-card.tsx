import type { Metric } from "@/lib/types";

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return value.toLocaleString();
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function MetricCard({ label, metric }: { label: string; metric: Metric }) {
  const insufficient = metric.quality === "INSUFFICIENT_DATA";

  return (
    <div className="card p-4">
      <div className="text-xs font-medium uppercase tracking-wide muted">{label}</div>
      {insufficient ? (
        <div className="mt-2">
          <div className="text-sm font-semibold text-amber-600 dark:text-amber-400">
            INSUFFICIENT_DATA
          </div>
          {metric.reason && <div className="mt-1 text-xs muted">{metric.reason}</div>}
        </div>
      ) : (
        <div className="mt-2">
          <div className="text-2xl font-bold">{formatValue(metric.value)}</div>
          <div className="mt-1 text-xs muted">
            {metric.quality} · n={metric.sample_size}
          </div>
        </div>
      )}
    </div>
  );
}
