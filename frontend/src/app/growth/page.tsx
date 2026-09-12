"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { MetricCard } from "@/components/metric-card";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { api } from "@/lib/api";
import type { Channel, GrowthScorecardOut, SubscriberGrowthOut } from "@/lib/types";

export default function GrowthPage() {
  const channelsQuery = useQuery({
    queryKey: ["channels"],
    queryFn: () => api.get<Channel[]>("/channels"),
  });
  const channel = channelsQuery.data?.[0];

  const scorecardQuery = useQuery({
    queryKey: ["growth-scorecard", channel?.id],
    queryFn: () => api.get<GrowthScorecardOut>(`/analytics/growth/${channel!.id}/scorecard`),
    enabled: !!channel,
  });

  const subsQuery = useQuery({
    queryKey: ["subscriber-growth", channel?.id],
    queryFn: () => api.get<SubscriberGrowthOut>(`/analytics/growth/${channel!.id}/subscribers`),
    enabled: !!channel,
  });

  return (
    <AppShell>
      <PageHeader
        title="Growth Scorecard"
        description="Component scores are always shown separately — never merged into one misleading number."
      />

      {!channel && !channelsQuery.isLoading && (
        <EmptyState>Connect a channel to see growth scoring.</EmptyState>
      )}

      {scorecardQuery.isLoading && <LoadingState />}
      {scorecardQuery.data && (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MetricCard label="Content" metric={scorecardQuery.data.content_score} />
            <MetricCard label="Discovery" metric={scorecardQuery.data.discovery_score} />
            <MetricCard label="CTR" metric={scorecardQuery.data.ctr_score} />
            <MetricCard label="Retention" metric={scorecardQuery.data.retention_score} />
            <MetricCard label="Subscriber Conversion" metric={scorecardQuery.data.subscriber_conversion_score} />
            <MetricCard label="Returning Viewers" metric={scorecardQuery.data.returning_viewers_score} />
            <MetricCard label="Distribution" metric={scorecardQuery.data.distribution_score} />
            <MetricCard label="Consistency" metric={scorecardQuery.data.consistency_score} />
          </div>
          <p className="text-sm muted">{scorecardQuery.data.explanation}</p>
        </>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold">Subscriber Growth</h2>
      {subsQuery.data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label="Growth Rate" metric={subsQuery.data.subscriber_growth_rate} />
          <MetricCard label="Conversion Rate %" metric={subsQuery.data.subscriber_conversion_rate} />
          <MetricCard label="Subs / 1000 Views" metric={subsQuery.data.subscribers_per_1000_views} />
          <MetricCard label="Returning Viewer Rate" metric={subsQuery.data.returning_viewer_rate} />
        </div>
      )}
    </AppShell>
  );
}
