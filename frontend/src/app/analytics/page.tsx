"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button } from "@/components/ui";
import { api } from "@/lib/api";
import type { Channel } from "@/lib/types";

interface Snapshot {
  id: string;
  captured_at: string;
  total_views: number | null;
  total_subscribers: number | null;
  data_quality: string;
}

export default function AnalyticsPage() {
  const queryClient = useQueryClient();
  const channelsQuery = useQuery({ queryKey: ["channels"], queryFn: () => api.get<Channel[]>("/channels") });
  const channel = channelsQuery.data?.[0];

  const snapshotsQuery = useQuery({
    queryKey: ["snapshots", channel?.id],
    queryFn: () => api.get<Snapshot[]>(`/analytics/channel/${channel!.id}/snapshots`),
    enabled: !!channel,
  });

  const takeSnapshotMutation = useMutation({
    mutationFn: () => api.post<Snapshot>(`/analytics/channel/${channel!.id}/snapshots`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["snapshots", channel?.id] }),
  });

  return (
    <AppShell>
      <PageHeader title="Analytics" description="Point-in-time snapshots computed from real synced video data." />

      {!channel && !channelsQuery.isLoading && <EmptyState>Connect a channel first.</EmptyState>}

      {channel && (
        <Button onClick={() => takeSnapshotMutation.mutate()} disabled={takeSnapshotMutation.isPending}>
          {takeSnapshotMutation.isPending ? "Capturing…" : "Capture snapshot now"}
        </Button>
      )}

      {snapshotsQuery.isLoading && <LoadingState />}
      {snapshotsQuery.data?.length === 0 && (
        <div className="mt-4">
          <EmptyState>No snapshots yet.</EmptyState>
        </div>
      )}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b" style={{ borderColor: "rgb(var(--border))" }}>
              <th className="py-2 pr-4">Captured</th>
              <th className="py-2 pr-4">Total Views</th>
              <th className="py-2 pr-4">Subscribers</th>
              <th className="py-2 pr-4">Quality</th>
            </tr>
          </thead>
          <tbody>
            {snapshotsQuery.data?.map((s) => (
              <tr key={s.id} className="border-b" style={{ borderColor: "rgb(var(--border))" }}>
                <td className="py-2 pr-4">{new Date(s.captured_at).toLocaleString()}</td>
                <td className="py-2 pr-4">{s.total_views?.toLocaleString() ?? "—"}</td>
                <td className="py-2 pr-4">{s.total_subscribers?.toLocaleString() ?? "—"}</td>
                <td className="py-2 pr-4">{s.data_quality}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
