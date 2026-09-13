"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { MetricCard } from "@/components/metric-card";
import { FormatComparisonCard } from "@/components/format-comparison-card";
import { PageHeader, LoadingState, ErrorState, EmptyState, Badge } from "@/components/ui";
import { api } from "@/lib/api";
import type { Channel, ChannelIntelligence, GrowthAction, GrowthDiagnosisOut, Recommendation } from "@/lib/types";

export default function DashboardPage() {
  const channelsQuery = useQuery({
    queryKey: ["channels"],
    queryFn: () => api.get<Channel[]>("/channels"),
  });

  const channel = channelsQuery.data?.[0];

  const intelligenceQuery = useQuery({
    queryKey: ["channel-intelligence", channel?.id],
    queryFn: () => api.get<ChannelIntelligence>(`/videos/channel/${channel!.id}/intelligence`),
    enabled: !!channel,
  });

  const diagnosisQuery = useQuery({
    queryKey: ["growth-diagnosis", channel?.id],
    queryFn: () => api.get<GrowthDiagnosisOut>(`/analytics/growth/${channel!.id}/diagnosis`),
    enabled: !!channel,
  });

  const recommendationsQuery = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => api.get<Recommendation[]>("/recommendations"),
  });

  const growthActionsQuery = useQuery({
    queryKey: ["growth-actions"],
    queryFn: () => api.get<GrowthAction[]>("/analytics/growth-actions"),
  });

  return (
    <AppShell>
      <PageHeader title="Creator Health" description="A snapshot of what's real, what's estimated, and what we don't know yet." />

      {channelsQuery.isLoading && <LoadingState />}
      {channelsQuery.isError && <ErrorState message="Failed to load channels." />}

      {channelsQuery.data && channelsQuery.data.length === 0 && (
        <EmptyState>
          No channel connected yet.{" "}
          <Link href="/channels" className="font-medium text-brand-500 hover:underline">
            Connect your YouTube channel
          </Link>{" "}
          to see real data here.
        </EmptyState>
      )}

      {channel && (
        <>
          <div className="mb-2 flex items-center gap-2">
            <h2 className="text-lg font-semibold">{channel.title}</h2>
            <Badge tone={channel.sync_status === "SUCCEEDED" ? "success" : "warning"}>
              {channel.sync_status}
            </Badge>
          </div>

          {intelligenceQuery.isLoading && <LoadingState />}
          {intelligenceQuery.data && (
            <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              <MetricCard label="Total Views" metric={intelligenceQuery.data.total_views} />
              <MetricCard label="Subscribers" metric={intelligenceQuery.data.subscriber_count} />
              <MetricCard label="Avg Views/Video" metric={intelligenceQuery.data.average_views} />
              <MetricCard label="Median Views/Video" metric={intelligenceQuery.data.median_views} />
              <MetricCard label="7-Day View Velocity" metric={intelligenceQuery.data.views_velocity_7d} />
              <MetricCard label="Uploads / Week" metric={intelligenceQuery.data.upload_frequency_per_week} />
              <MetricCard label="Engagement Rate %" metric={intelligenceQuery.data.engagement_rate} />
              <FormatComparisonCard metric={intelligenceQuery.data.shorts_vs_long_form} />
            </div>
          )}

          <h2 className="mb-3 mt-8 text-lg font-semibold">Why isn&apos;t my channel growing?</h2>
          {diagnosisQuery.isLoading && <LoadingState />}
          {diagnosisQuery.data && diagnosisQuery.data.bottlenecks.length === 0 && (
            <EmptyState>{diagnosisQuery.data.note}</EmptyState>
          )}
          {diagnosisQuery.data && diagnosisQuery.data.bottlenecks.length > 0 && (
            <div className="mb-8 space-y-3">
              {diagnosisQuery.data.bottlenecks.map((b) => (
                <div key={b.bottleneck} className="card p-4">
                  <div className="flex items-center gap-2">
                    <Badge tone="warning">{b.bottleneck.replaceAll("_", " ")}</Badge>
                    <Badge>{b.confidence} confidence</Badge>
                  </div>
                  <p className="mt-2 text-sm">{b.evidence}</p>
                  <p className="mt-1 text-sm font-medium">{b.recommended_action}</p>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold">Today&apos;s AI Growth Missions</h2>
      {growthActionsQuery.isLoading && <LoadingState />}
      {growthActionsQuery.data && growthActionsQuery.data.length === 0 && (
        <EmptyState>
          No missions yet — these are generated daily from your Growth Diagnosis bottlenecks
          once the daily growth agent has run for your account.
        </EmptyState>
      )}
      {growthActionsQuery.data && growthActionsQuery.data.length > 0 && (
        <div className="mb-8 space-y-3">
          {growthActionsQuery.data.map((mission) => (
            <div key={mission.id} className="card p-4">
              <div className="flex items-center gap-2">
                <Badge>#{mission.priority}</Badge>
                <Badge tone={mission.confidence === "HIGH" ? "success" : "warning"}>
                  {mission.confidence} confidence
                </Badge>
                <Badge tone={mission.execution_status === "pending" ? "warning" : "success"}>
                  {mission.execution_status}
                </Badge>
                {mission.requires_approval && <Badge tone="warning">Needs approval</Badge>}
              </div>
              <p className="mt-2 font-medium">{mission.title}</p>
              <p className="mt-1 text-sm muted">{mission.reason}</p>
              {mission.evidence && <p className="mt-1 text-xs muted">{mission.evidence}</p>}
            </div>
          ))}
        </div>
      )}

      <h2 className="mb-3 mt-8 text-lg font-semibold">Next Best Video</h2>
      {recommendationsQuery.isLoading && <LoadingState />}
      {recommendationsQuery.data && recommendationsQuery.data.length === 0 && (
        <EmptyState>
          No recommendations yet — visit{" "}
          <Link href="/recommendations" className="font-medium text-brand-500 hover:underline">
            Recommendations
          </Link>{" "}
          to generate your first batch once you have topics with opportunity scores.
        </EmptyState>
      )}
      {recommendationsQuery.data && recommendationsQuery.data.length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {recommendationsQuery.data.slice(0, 3).map((r) => (
            <div key={r.id} className="card p-4">
              <div className="text-xs muted">#{r.rank} · {r.confidence}</div>
              <div className="mt-1 font-medium">{r.topic}</div>
              <p className="mt-1 text-sm muted line-clamp-2">{r.reason}</p>
            </div>
          ))}
        </div>
      )}
    </AppShell>
  );
}
