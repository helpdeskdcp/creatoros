"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { api } from "@/lib/api";
import type { ContentItem } from "@/lib/types";

export default function CalendarPage() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1).toISOString();
  const end = new Date(now.getFullYear(), now.getMonth() + 2, 0).toISOString();

  const query = useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () =>
      api.get<ContentItem[]>(`/content/calendar?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`),
  });

  return (
    <AppShell>
      <PageHeader title="Content Calendar" description="Scheduled publish dates, shown in each item's own timezone." />

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
