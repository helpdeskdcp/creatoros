"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Competitor, Metric } from "@/lib/types";

interface ContentGap {
  keyword: string;
  competitor_count: number;
  total_competitor_views: number;
  creator_has_covered: boolean;
  signal: string;
}

interface FormatBreakdown {
  shorts_count: number;
  long_form_count: number;
  quality: string;
}

interface GapToTopicResult {
  keyword: string;
  topic_id: string | null;
  created: boolean;
  reason: string | null;
}

function CompetitorStats({ competitorId }: { competitorId: string }) {
  const tractionQuery = useQuery({
    queryKey: ["competitor-traction", competitorId],
    queryFn: () => api.get<Metric>(`/competitors/${competitorId}/traction`),
  });
  const cadenceQuery = useQuery({
    queryKey: ["competitor-cadence", competitorId],
    queryFn: () => api.get<Metric>(`/competitors/${competitorId}/cadence`),
  });
  const formatsQuery = useQuery({
    queryKey: ["competitor-formats", competitorId],
    queryFn: () => api.get<FormatBreakdown>(`/competitors/${competitorId}/formats`),
  });

  return (
    <div className="mt-2 flex flex-wrap gap-3 text-xs muted">
      <span>
        Traction:{" "}
        {tractionQuery.data?.quality === "REAL" ? `${tractionQuery.data.value} subs/week` : "insufficient data yet"}
      </span>
      <span>
        Cadence:{" "}
        {cadenceQuery.data?.quality === "REAL" ? `${cadenceQuery.data.value} uploads/week` : "insufficient data yet"}
      </span>
      <span>
        Format:{" "}
        {formatsQuery.data && formatsQuery.data.quality === "REAL"
          ? `${formatsQuery.data.shorts_count} shorts / ${formatsQuery.data.long_form_count} long-form`
          : "insufficient data yet"}
      </span>
    </div>
  );
}

export default function CompetitorsPage() {
  const queryClient = useQueryClient();
  const [channelId, setChannelId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [gapToTopicResults, setGapToTopicResults] = useState<GapToTopicResult[] | null>(null);

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

  const gapsToTopicsMutation = useMutation({
    mutationFn: () => api.post<GapToTopicResult[]>("/competitors/opportunities/content-gaps/create-topics"),
    onSuccess: (results) => {
      setGapToTopicResults(results);
      queryClient.invalidateQueries({ queryKey: ["topics"] });
    },
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
          <div key={c.id} className="card p-4">
            <div className="flex items-center justify-between">
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
            <CompetitorStats competitorId={c.id} />
          </div>
        ))}
      </div>

      <div className="mb-3 mt-8 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Content Gaps</h2>
        <Button
          variant="secondary"
          onClick={() => gapsToTopicsMutation.mutate()}
          disabled={gapsToTopicsMutation.isPending || gapsQuery.data?.length === 0}
        >
          Turn top gaps into Topics
        </Button>
      </div>
      {gapToTopicResults && (
        <div className="mb-3 space-y-1 text-xs muted">
          {gapToTopicResults.map((r) => (
            <div key={r.keyword}>
              &ldquo;{r.keyword}&rdquo;: {r.created ? "topic created" : "already existed"}
              {r.reason ? ` — ${r.reason}` : ""}
            </div>
          ))}
        </div>
      )}
      {gapsQuery.data?.length === 0 && (
        <EmptyState>Track at least 2 competitors and sync them to detect content gaps.</EmptyState>
      )}
      <div className="space-y-2">
        {gapsQuery.data?.map((g) => (
          <div key={g.keyword} className="card flex items-center justify-between p-3 text-sm">
            <span>
              <span className="font-medium">{g.keyword}</span> — {g.signal}
            </span>
            {!g.creator_has_covered && <Badge tone="warning">Gap</Badge>}
          </div>
        ))}
      </div>
    </AppShell>
  );
}
