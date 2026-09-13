"use client";

import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { MetricCard } from "@/components/metric-card";
import { PageHeader, LoadingState, ErrorState, Button, Input } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Channel, ChannelIntelligence, VideoOut } from "@/lib/types";

function ProposeTitleUpdate({ video }: { video: VideoOut }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(video.title);

  const proposeMutation = useMutation({
    mutationFn: () =>
      api.post("/video-updates", {
        video_id: video.id,
        field: "TITLE",
        proposed_value: title,
        reason: "Manually proposed from the channel video list",
      }),
    onSuccess: () => {
      setEditing(false);
      queryClient.invalidateQueries({ queryKey: ["video-update-proposals"] });
    },
  });

  if (!editing) {
    return (
      <Button variant="secondary" onClick={() => setEditing(true)}>
        Propose title update
      </Button>
    );
  }
  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <Input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={100} />
      <div className="flex gap-2">
        <Button onClick={() => proposeMutation.mutate()} disabled={proposeMutation.isPending}>
          Submit for approval
        </Button>
        <Button variant="secondary" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
      {proposeMutation.isError && (
        <span className="text-sm text-red-600 dark:text-red-400">
          {proposeMutation.error instanceof ApiError ? proposeMutation.error.message : "Failed to propose"}
        </span>
      )}
    </div>
  );
}

export default function ChannelDetailPage() {
  const params = useParams<{ id: string }>();
  const channelId = params.id;

  const channelQuery = useQuery({
    queryKey: ["channel", channelId],
    queryFn: () => api.get<Channel>(`/channels/${channelId}`),
  });

  const intelligenceQuery = useQuery({
    queryKey: ["channel-intelligence", channelId],
    queryFn: () => api.get<ChannelIntelligence>(`/videos/channel/${channelId}/intelligence`),
  });

  const videosQuery = useQuery({
    queryKey: ["videos", channelId],
    queryFn: () => api.get<VideoOut[]>(`/videos/channel/${channelId}`),
  });

  return (
    <AppShell>
      {channelQuery.isLoading && <LoadingState />}
      {channelQuery.isError && <ErrorState message="Failed to load channel." />}
      {channelQuery.data && (
        <PageHeader title={channelQuery.data.title} description={channelQuery.data.description ?? undefined} />
      )}

      {intelligenceQuery.data && (
        <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label="Total Views" metric={intelligenceQuery.data.total_views} />
          <MetricCard label="Avg Views/Video" metric={intelligenceQuery.data.average_views} />
          <MetricCard label="Engagement Rate %" metric={intelligenceQuery.data.engagement_rate} />
          <MetricCard label="Uploads / Week" metric={intelligenceQuery.data.upload_frequency_per_week} />
        </div>
      )}

      <h2 className="mb-3 mt-6 text-lg font-semibold">Videos</h2>
      {videosQuery.isLoading && <LoadingState />}
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b" style={{ borderColor: "rgb(var(--border))" }}>
              <th className="py-2 pr-4">Title</th>
              <th className="py-2 pr-4">Format</th>
              <th className="py-2 pr-4">Views</th>
              <th className="py-2 pr-4">Likes</th>
              <th className="py-2 pr-4">Published</th>
              <th className="py-2 pr-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {videosQuery.data?.map((v) => (
              <tr key={v.id} className="border-b" style={{ borderColor: "rgb(var(--border))" }}>
                <td className="max-w-xs truncate py-2 pr-4">{v.title}</td>
                <td className="py-2 pr-4">{v.format ?? "—"}</td>
                <td className="py-2 pr-4">{v.view_count?.toLocaleString() ?? "—"}</td>
                <td className="py-2 pr-4">{v.like_count?.toLocaleString() ?? "—"}</td>
                <td className="py-2 pr-4">
                  {v.published_at ? new Date(v.published_at).toLocaleDateString() : "—"}
                </td>
                <td className="min-w-[220px] py-2 pr-4">
                  <ProposeTitleUpdate video={v} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted mt-2 text-xs">
        Proposed changes require approval in the Approval Center before they reach YouTube.
      </p>
    </AppShell>
  );
}
