"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Competitor } from "@/lib/types";

interface ContentGap {
  keyword: string;
  competitor_count: number;
  total_competitor_views: number;
  creator_has_covered: boolean;
  signal: string;
}

export default function CompetitorsPage() {
  const queryClient = useQueryClient();
  const [channelId, setChannelId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const competitorsQuery = useQuery({
    queryKey: ["competitors"],
    queryFn: () => api.get<Competitor[]>("/competitors"),
  });

  const gapsQuery = useQuery({
    queryKey: ["content-gaps"],
    queryFn: () => api.get<ContentGap[]>("/competitors/opportunities/content-gaps"),
  });

  const addMutation = useMutation({
    mutationFn: (id: string) => api.post<Competitor>("/competitors", { youtube_channel_id: id }),
    onSuccess: () => {
      setChannelId("");
      queryClient.invalidateQueries({ queryKey: ["competitors"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to add competitor"),
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => api.post<Competitor>(`/competitors/${id}/sync`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["competitors"] }),
  });

  return (
    <AppShell>
      <PageHeader title="Competitors" description="Public data only — never private competitor analytics." />

      <div className="card mb-6 p-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (channelId.trim()) addMutation.mutate(channelId.trim());
          }}
          className="flex gap-2"
        >
          <Input
            placeholder="Competitor YouTube channel ID"
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
          />
          <Button type="submit" disabled={addMutation.isPending}>
            Track
          </Button>
        </form>
        {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>

      {competitorsQuery.isLoading && <LoadingState />}
      {competitorsQuery.data?.length === 0 && <EmptyState>No competitors tracked yet.</EmptyState>}
      <div className="space-y-3">
        {competitorsQuery.data?.map((c) => (
          <div key={c.id} className="card flex items-center justify-between p-4">
            <div>
              <div className="font-medium">{c.title}</div>
              <div className="text-xs muted">
                {c.subscriber_count?.toLocaleString() ?? "—"} subscribers ·{" "}
                {c.video_count?.toLocaleString() ?? "—"} videos
              </div>
            </div>
            <Button variant="secondary" onClick={() => syncMutation.mutate(c.id)}>
              Sync
            </Button>
          </div>
        ))}
      </div>

      <h2 className="mb-3 mt-8 text-lg font-semibold">Content Gaps</h2>
      {gapsQuery.data?.length === 0 && (
        <EmptyState>Track at least 2 competitors and sync them to detect content gaps.</EmptyState>
      )}
      <div className="space-y-2">
        {gapsQuery.data?.map((g) => (
          <div key={g.keyword} className="card p-3 text-sm">
            <span className="font-medium">{g.keyword}</span> — {g.signal}
          </div>
        ))}
      </div>
    </AppShell>
  );
}
