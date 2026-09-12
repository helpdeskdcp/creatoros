"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, ErrorState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import type { Channel } from "@/lib/types";

interface OAuthAuthorizeResponse {
  authorize_url: string;
  state: string;
}

interface OAuthStatusResponse {
  configured: boolean;
  publishing_status: string;
  redirect_uri: string;
  scopes: string[];
}

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  // Google's own "not an approved tester" block page never redirects back
  // here at all (it dead-ends on accounts.google.com) — so if we ever DO
  // see access_denied, it's more likely a real consent decline. Still
  // mention testing mode since some Google flow variants do redirect back
  // with this code for the same underlying reason.
  access_denied:
    "Google denied access. Either you declined the consent screen, or — if this app's OAuth is " +
    "still in Testing mode — your Google account hasn't been added as an approved Test User yet.",
  missing_code_or_state: "Google's redirect was missing required parameters.",
  invalid_state: "The OAuth session expired or was invalid — please try connecting again.",
  connect_failed: "CreatorOS could not complete the connection with that Google account.",
};

export default function ChannelsPage() {
  const queryClient = useQueryClient();
  const [youtubeChannelId, setYoutubeChannelId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [oauthNotice, setOauthNotice] = useState<{ kind: "success" | "error"; message: string } | null>(
    null
  );

  // This page is also Google's OAuth redirect landing target (the backend's
  // GET /channels/oauth/callback 302s here with ?connected=<id> or
  // ?oauth_error=<code>) — read it once on mount and scrub it from the URL.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const oauthError = params.get("oauth_error");
    if (connected) {
      setOauthNotice({ kind: "success", message: "YouTube channel connected via OAuth." });
    } else if (oauthError) {
      setOauthNotice({
        kind: "error",
        message: OAUTH_ERROR_MESSAGES[oauthError] ?? `OAuth connection failed (${oauthError}).`,
      });
    }
    if (connected || oauthError) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }, []);

  const channelsQuery = useQuery({
    queryKey: ["channels"],
    queryFn: () => api.get<Channel[]>("/channels"),
  });

  const oauthStatusQuery = useQuery({
    queryKey: ["oauth-status"],
    queryFn: () => api.get<OAuthStatusResponse>("/channels/oauth/status"),
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

  const oauthConnectMutation = useMutation({
    mutationFn: () => api.get<OAuthAuthorizeResponse>("/channels/oauth/authorize"),
    onSuccess: (data) => {
      // Top-level navigation to Google — not a fetch — since the consent
      // screen and subsequent redirect back to our backend must happen in
      // the real browser location, not an XHR.
      window.location.href = data.authorize_url;
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to start OAuth flow"),
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

      {oauthNotice && (
        <div
          className={`mb-4 rounded-lg border p-3 text-sm ${
            oauthNotice.kind === "success"
              ? "border-green-300 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300"
              : "border-red-300 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
          }`}
        >
          {oauthNotice.message}
        </div>
      )}

      <div className="card mb-6 p-4">
        <h2 className="mb-3 font-medium">Connect with OAuth (recommended)</h2>
        <p className="mb-3 text-xs muted">
          Required for authorized analytics (CTR, retention, subscriber attribution) and
          publishing. You&apos;ll be sent to Google to sign in and grant CreatorOS access to your
          own YouTube channel — every CreatorOS account connects its own channel independently.
          Make sure you sign in with the same Google account that actually owns the YouTube
          channel you want to connect.
        </p>

        {oauthStatusQuery.data?.configured &&
          oauthStatusQuery.data.publishing_status === "testing" && (
            <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
              <strong>Google OAuth is currently in Testing mode.</strong> Only Google accounts
              added as Test Users in this app&apos;s Google Cloud OAuth consent screen can
              connect. If your account isn&apos;t approved, ask whoever manages this deployment to
              add it there — CreatorOS itself can&apos;t grant that access.
            </div>
          )}
        {oauthStatusQuery.data && !oauthStatusQuery.data.configured && (
          <div className="mb-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
            Google OAuth isn&apos;t configured on this server yet — connecting will use mock
            YouTube data for development purposes only.
          </div>
        )}

        <Button onClick={() => oauthConnectMutation.mutate()} disabled={oauthConnectMutation.isPending}>
          {oauthConnectMutation.isPending ? "Redirecting to Google…" : "Connect with Google"}
        </Button>
      </div>

      <div className="card mb-6 p-4">
        <h2 className="mb-3 font-medium">Connect a channel (public data only)</h2>
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
          No sign-in required, but no authorized analytics or publishing until you also connect
          via OAuth above.
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
