"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, ErrorState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Channel } from "@/lib/types";

export default function ChannelsPage() {
  const queryClient = useQueryClient();
  const [youtubeChannelId, setYoutubeChannelId] = useState("");
  const [error, setError] = useState<string | null>(null);

  const channelsQuery = useQuery({
    queryKey: ["channels"],
    queryFn: () => api.get<Channel[]>("/channels"),
  });

  const connectMutation = useMutation({
    mutationFn: (id: string) => api.post<Channel>("/channels", { youtube_channel_id: id }),
    onSuccess: () => {
      setYoutubeChannelId("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to connect channel"),
  });

  const syncMutation = useMutation({
    mutationFn: (id: string) => api.post<Channel>(`/channels/${id}/sync`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channels"] }),
  });

  return (
    <AppShell>
      <PageHeader
        title="Channels"
        description="Connect a YouTube channel for public read-only tracking, or use OAuth for authorized analytics and publishing."
      />

      <div className="card mb-6 p-4">
        <h2 className="mb-3 font-medium">Connect a channel (public data)</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (youtubeChannelId.trim()) connectMutation.mutate(youtubeChannelId.trim());
          }}
          className="flex gap-2"
        >
          <Input
            placeholder="YouTube channel ID (e.g. UCxxxxxxxxxxxxxxxxxxxxxx)"
            value={youtubeChannelId}
            onChange={(e) => setYoutubeChannelId(e.target.value)}
          />
          <Button type="submit" disabled={connectMutation.isPending}>
            {connectMutation.isPending ? "Connecting…" : "Connect"}
          </Button>
        </form>
        {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
        <p className="mt-2 text-xs muted">
          For authorized analytics (CTR, retention, subscriber attribution) and publishing, OAuth
          must be configured by an administrator (YOUTUBE_CLIENT_ID/SECRET) — see docs/youtube.md.
        </p>
      </div>

      {channelsQuery.isLoading && <LoadingState />}
      {channelsQuery.isError && <ErrorState message="Failed to load channels." />}
      {channelsQuery.data && channelsQuery.data.length === 0 && (
        <EmptyState>No channels connected yet.</EmptyState>
      )}

      <div className="space-y-3">
        {channelsQuery.data?.map((channel) => (
          <div key={channel.id} className="card flex items-center justify-between p-4">
            <div>
              <Link href={`/channels/${channel.id}`} className="font-medium hover:underline">
                {channel.title}
              </Link>
              <div className="mt-1 flex items-center gap-2 text-xs muted">
                <span>{channel.youtube_channel_id}</span>
                <Badge tone={channel.sync_status === "SUCCEEDED" ? "success" : "warning"}>
                  {channel.sync_status}
                </Badge>
              </div>
            </div>
            <Button
              variant="secondary"
              onClick={() => syncMutation.mutate(channel.id)}
              disabled={syncMutation.isPending}
            >
              {syncMutation.isPending ? "Syncing…" : "Sync now"}
            </Button>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
