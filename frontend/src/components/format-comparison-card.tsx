import type { FormatStats, Metric, ShortsVsLongForm } from "@/lib/types";

function Row({ label, shorts, longForm, format }: { label: string; shorts: number | null; longForm: number | null; format: (n: number) => string }) {
  return (
    <div className="grid grid-cols-3 gap-2 py-1.5 text-sm">
      <div className="muted">{label}</div>
      <div className="text-right font-medium">{shorts === null ? "—" : format(shorts)}</div>
      <div className="text-right font-medium">{longForm === null ? "—" : format(longForm)}</div>
    </div>
  );
}

function LowSampleNote({ label, stats }: { label: string; stats: FormatStats }) {
  const needsMore = stats.video_count > 0 && (stats.avg_views === null || stats.avg_engagement_rate === null);
  if (!needsMore) return null;
  return (
    <div className="mt-1 text-[11px] muted">
      {label}: not enough videos of this format yet for a trustworthy average ({stats.sample_size_for_averages} eligible)
    </div>
  );
}

export function FormatComparisonCard({ metric }: { metric: Metric<ShortsVsLongForm> }) {
  if (metric.quality === "INSUFFICIENT_DATA" || !metric.value) {
    return (
      <div className="card p-4">
        <div className="text-xs font-medium uppercase tracking-wide muted">Shorts vs Long-form</div>
        <div className="mt-2 text-sm font-semibold text-amber-600 dark:text-amber-400">INSUFFICIENT_DATA</div>
        {metric.reason && <div className="mt-1 text-xs muted">{metric.reason}</div>}
      </div>
    );
  }

  const { shorts, long_form: longForm } = metric.value;

  return (
    <div className="card p-4">
      <div className="text-xs font-medium uppercase tracking-wide muted">Shorts vs Long-form</div>
      <div className="mt-3 grid grid-cols-3 gap-2 border-b pb-1.5 text-xs font-semibold uppercase tracking-wide muted" style={{ borderColor: "rgb(var(--border))" }}>
        <div />
        <div className="text-right">Shorts</div>
        <div className="text-right">Long-form</div>
      </div>
      <Row label="Videos" shorts={shorts.video_count} longForm={longForm.video_count} format={(n) => n.toLocaleString()} />
      <Row label="Total views" shorts={shorts.total_views} longForm={longForm.total_views} format={(n) => n.toLocaleString()} />
      <Row label="Avg views" shorts={shorts.avg_views} longForm={longForm.avg_views} format={(n) => n.toLocaleString()} />
      <Row
        label="Avg engagement"
        shorts={shorts.avg_engagement_rate}
        longForm={longForm.avg_engagement_rate}
        format={(n) => `${n}%`}
      />
      <LowSampleNote label="Shorts" stats={shorts} />
      <LowSampleNote label="Long-form" stats={longForm} />
      <div className="mt-2 text-[11px] muted">n={metric.sample_size} videos total · {metric.quality}</div>
    </div>
  );
}
