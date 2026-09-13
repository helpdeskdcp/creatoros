"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Badge } from "@/components/ui";
import { api } from "@/lib/api";
import type { ContentItem, Channel } from "@/lib/types";

interface PublishTimingSuggestion {
  quality: "REAL" | "ESTIMATED" | "INSUFFICIENT_DATA";
  best_day_of_week: string | null;
  best_day_median_views: number | null;
  sample_size: number;
  evidence: string;
}

function PublishTimingInsight({ channel }: { channel: Channel }) {
  const query = useQuery({
    queryKey: ["publish-timing", channel.id],
    queryFn: () => api.get<PublishTimingSuggestion>(`/analytics/channel/${channel.id}/publish-timing`),
  });
  if (!query.data) return null;

  return (
    <div className="card mb-2 p-3 text-sm">
      <div className="mb-1 flex items-center gap-2">
        <span className="font-medium">{channel.title}</span>
        <Badge tone={query.data.quality === "REAL" ? "success" : "default"}>
          {query.data.quality === "REAL" ? `Best day: ${query.data.best_day_of_week}` : "Not enough data yet"}
        </Badge>
      </div>
      <p className="muted">{query.data.evidence}</p>
    </div>
  );
}

export default function CalendarPage() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString();
  const end = new Date(now.getFullYear(), now.getMonth() + 2, 0).toISOString();

  const query = useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () =>
      api.get<ContentItem[]>(`/content/calendar?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
  });
  const channelsQuery = useQuery({
    queryKey: ["channels"],
    queryFn: () => api.get<Channel[]>("/channels"),
  });

  return (
    <AppShell>
      <PageHeader title="Content Calendar" description="Scheduled publish dates, shown in each item's own timezone." />

      {channelsQuery.data && channelsQuery.data.length > 0 && (
        <div className="mb-6">
          <h2 className="mb-2 text-sm font-semibold muted">Best day to publish, from your own history</h2>
          {channelsQuery.data.map((c) => (
            <PublishTimingInsight key={c.id} channel={c} />
          ))}
        </div>
      )}

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && (
        <EmptyState>Nothing scheduled. Set a scheduled_publish_at on a content item to see it here.</EmptyState>
      )}

      <div className="space-y-2">
        {query.data?.map((item) => (
          <div key={item.id} className="card flex items-center justify-between p-3 text-sm">
            <span>{item.title}</span>
            <span className="muted">
              {item.scheduled_publish_at ? new Date(item.scheduled_publish_at).toLocaleString() : "—"} (
              {item.timezone})
            </span>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
