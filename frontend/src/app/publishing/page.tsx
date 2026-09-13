"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, ErrorState, Badge, Button } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

interface PublishingRun {
  id: string;
  mode: string;
  state: string;
  youtube_video_id: string | null;
  published_url: string | null;
  published_at: string | null;
  failure_reason: string | null;
  requires_approval: boolean;
  scheduled_at: string | null;
  cancelled_at: string | null;
  retry_count: number;
}

// Collapses the internal state machine into the 7 creator-facing
// categories the product spec calls for -- VALIDATING/UPLOAD_QUEUED/
// UPLOADING/PROCESSING are all internal detail of "Publishing" to a
// creator watching this page.
function displayStatus(run: PublishingRun): { label: string; tone: "default" | "success" | "warning" | "danger" } {
  if (run.state === "CANCELLED") return { label: "Cancelled", tone: "default" };
  if (run.state === "FAILED") return { label: "Failed", tone: "danger" };
  if (run.state === "PUBLISHED") return { label: "Published", tone: "success" };
  if (run.state === "SCHEDULED") return { label: "Scheduled", tone: "warning" };
  if (run.state === "DRAFT" && run.requires_approval) return { label: "Awaiting approval", tone: "warning" };
  if (run.state === "DRAFT") return { label: "Draft", tone: "default" };
  // READY / VALIDATING / UPLOAD_QUEUED / UPLOADING / PROCESSING
  return { label: "Publishing", tone: "warning" };
}

const CANCELLABLE_STATES = new Set(["DRAFT", "READY", "SCHEDULED"]);

export default function PublishingPage() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["publishing-runs"],
    queryFn: () => api.get<PublishingRun[]>("/publishing/runs"),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.post<PublishingRun>(`/publishing/runs/${id}/cancel`),
    onSuccess: () => {
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["publishing-runs"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Failed to cancel run"),
  });

  return (
    <AppShell>
      <PageHeader
        title="Publishing"
        description="Every automated publish passes a 13-step safety gate before anything is uploaded, re-checked again at execution time. See Control Center for the kill switch and publishing rules."
      />

      {error && <p className="mb-3 text-sm text-red-600 dark:text-red-400">{error}</p>}
      {query.isLoading && <LoadingState />}
      {query.isError && <ErrorState message="Failed to load publishing runs." />}
      {query.data?.length === 0 && (
        <EmptyState>
          No publishing runs yet. Upload a video via POST /media/upload, then create one via POST
          /publishing/runs once you have a video ready.
        </EmptyState>
      )}

      <div className="space-y-2">
        {query.data?.map((run) => {
          const status = displayStatus(run);
          const cancellable = CANCELLABLE_STATES.has(run.state);
          return (
            <div key={run.id} className="card flex items-center justify-between p-4 text-sm">
              <div>
                <div className="font-medium">{run.mode}</div>
                {run.scheduled_at && run.state === "SCHEDULED" && (
                  <div className="mt-1 text-xs muted">
                    Scheduled for {new Date(run.scheduled_at).toLocaleString()}
                  </div>
                )}
                {run.published_url && (
                  <a
                    href={run.published_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block text-brand-500 hover:underline"
                  >
                    {run.published_url}
                  </a>
                )}
                {run.failure_reason && (
                  <div className="mt-1 text-red-600 dark:text-red-400">{run.failure_reason}</div>
                )}
                {run.retry_count > 0 && (
                  <div className="mt-1 text-xs muted">{run.retry_count} retry attempt(s)</div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={status.tone}>{status.label}</Badge>
                {cancellable && (
                  <Button
                    variant="secondary"
                    onClick={() => cancelMutation.mutate(run.id)}
                    disabled={cancelMutation.isPending}
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </AppShell>
  );
}
