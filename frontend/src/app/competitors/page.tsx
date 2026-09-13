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

interface ChannelSearchResult {
  youtube_channel_id: string;
  title: string;
  description: string | null;
  thumbnail_url: string | null;
  subscriber_count: number | null;
  view_count: number | null;
  video_count: number | null;
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
  const [identifier, setIdentifier] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<ChannelSearchResult[] | null>(null);
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
    mutationFn: (identifierToAdd: string) => api.post<Competitor>("/competitors", { identifier: identifierToAdd }),
    onSuccess: () => {
      setIdentifier("");
      setSearchResults(null);
      queryClient.invalidateQueries({ queryKey: ["competitors"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to add competitor"),
  });

  const searchMutation = useMutation({
    mutationFn: (query: string) => api.get<ChannelSearchResult[]>(`/competitors/search?q=${encodeURIComponent(query)}`),
    onSuccess: (results) => {
      setSearchResults(results);
      setError(results.length === 0 ? "No channels found for that search." : null);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Search failed"),
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
            if (identifier.trim()) addMutation.mutate(identifier.trim());
          }}
          className="flex flex-col gap-2 sm:flex-row"
        >
          <Input
            placeholder="@handle, YouTube URL, channel ID, or a name to search"
            value={identifier}
            onChange={(e) => {
              setIdentifier(e.target.value);
              setSearchResults(null);
            }}
          />
          <div className="flex gap-2">
            <Button type="submit" disabled={addMutation.isPending}>
              Track
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={searchMutation.isPending || !identifier.trim()}
              onClick={() => searchMutation.mutate(identifier.trim())}
            >
              Search by name
            </Button>
          </div>
        </form>
        {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}

        {searchResults && searchResults.length > 0 && (
          <div className="mt-3 space-y-2">
            <p className="muted text-xs">Select the channel you meant:</p>
            {searchResults.map((r) => (
              <div key={r.youtube_channel_id} className="flex items-center justify-between rounded border p-2 text-sm" style={{ borderColor: "rgb(var(--border))" }}>
                <div>
                  <div className="font-medium">{r.title}</div>
                  <div className="muted text-xs">
                    {r.subscriber_count?.toLocaleString() ?? "—"} subscribers · {r.video_count?.toLocaleString() ?? "—"} videos
                  </div>
                </div>
                <Button
                  variant="secondary"
                  disabled={addMutation.isPending}
                  onClick={() => addMutation.mutate(r.youtube_channel_id)}
                >
                  Track this channel
                </Button>
              </div>
            ))}
          </div>
        )}
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
