"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Badge, ErrorState } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

interface VideoUpdateProposal {
  id: string;
  video_id: string;
  field: "TITLE" | "DESCRIPTION" | "TAGS";
  previous_value: string | null;
  verified_previous_value: string | null;
  proposed_value: string;
  reason: string;
  evidence: string | null;
  status:
    | "PENDING_APPROVAL"
    | "REJECTED"
    | "EXECUTING"
    | "SUCCEEDED_VERIFIED"
    | "FAILED_NOT_VERIFIED";
  approved_at: string | null;
  executed_at: string | null;
  verified_at: string | null;
  error_message: string | null;
  rollback_of_id: string | null;
  created_at: string;
}

function statusTone(status: string): "default" | "success" | "warning" | "danger" {
  if (status === "SUCCEEDED_VERIFIED") return "success";
  if (status === "FAILED_NOT_VERIFIED") return "danger";
  if (status === "PENDING_APPROVAL") return "warning";
  return "default";
}

function displayValue(field: string, raw: string): string {
  if (field !== "TAGS") return raw;
  try {
    return (JSON.parse(raw) as string[]).join(", ");
  } catch {
    return raw;
  }
}

export default function ApprovalsPage() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["video-update-proposals"],
    queryFn: () => api.get<VideoUpdateProposal[]>("/video-updates"),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["video-update-proposals"] });

  const approveMutation = useMutation({
    mutationFn: (id: string) => api.post(`/video-updates/${id}/approve`),
    onSuccess: invalidate,
  });
  const rejectMutation = useMutation({
    mutationFn: (id: string) => api.post(`/video-updates/${id}/reject`),
    onSuccess: invalidate,
  });
  const rollbackMutation = useMutation({
    mutationFn: (id: string) => api.post(`/video-updates/${id}/rollback`),
    onSuccess: invalidate,
  });

  if (query.isLoading) {
    return (
      <AppShell>
        <PageHeader title="Approval Center" description="Review and approve proposed YouTube changes before they go live." />
        <LoadingState />
      </AppShell>
    );
  }
  if (query.isError) {
    return (
      <AppShell>
        <PageHeader title="Approval Center" description="Review and approve proposed YouTube changes before they go live." />
        <ErrorState message="Could not load proposals." />
      </AppShell>
    );
  }

  const proposals = query.data ?? [];
  const pending = proposals.filter((p) => p.status === "PENDING_APPROVAL");
  const history = proposals.filter((p) => p.status !== "PENDING_APPROVAL");

  return (
    <AppShell>
      <PageHeader
        title="Approval Center"
        description="No proposed change reaches YouTube without your explicit approval. Every applied change is independently re-verified against YouTube's own read-back before it's marked successful."
      />

      <h2 className="mb-3 text-lg font-semibold">Pending your approval</h2>
      {pending.length === 0 && <EmptyState>Nothing pending right now.</EmptyState>}
      <div className="space-y-3">
        {pending.map((p) => (
          <div key={p.id} className="card p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge>{p.field}</Badge>
              <Badge tone={statusTone(p.status)}>{p.status}</Badge>
              {p.rollback_of_id && <Badge tone="warning">Rollback</Badge>}
            </div>
            <div className="grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <div className="muted mb-1">Current value</div>
                <div className="rounded border p-2" style={{ borderColor: "rgb(var(--border))" }}>
                  {p.previous_value ? displayValue(p.field, p.previous_value) : "—"}
                </div>
              </div>
              <div>
                <div className="muted mb-1">Proposed value</div>
                <div className="rounded border p-2 font-medium" style={{ borderColor: "rgb(var(--border))" }}>
                  {displayValue(p.field, p.proposed_value)}
                </div>
              </div>
            </div>
            <p className="mt-2 text-sm">
              <span className="muted">Why: </span>
              {p.reason}
            </p>
            {p.evidence && (
              <p className="text-sm">
                <span className="muted">Evidence: </span>
                {p.evidence}
              </p>
            )}
            <div className="mt-3 flex gap-2">
              <Button onClick={() => approveMutation.mutate(p.id)} disabled={approveMutation.isPending}>
                Approve &amp; Apply
              </Button>
              <Button
                variant="danger"
                onClick={() => rejectMutation.mutate(p.id)}
                disabled={rejectMutation.isPending}
              >
                Reject
              </Button>
            </div>
          </div>
        ))}
      </div>

      <h2 className="mb-3 mt-8 text-lg font-semibold">History</h2>
      {history.length === 0 && <EmptyState>No processed proposals yet.</EmptyState>}
      <div className="space-y-2">
        {history.map((p) => (
          <div key={p.id} className="card p-3 text-sm">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Badge>{p.field}</Badge>
              <Badge tone={statusTone(p.status)}>{p.status}</Badge>
              <span className="muted">{new Date(p.created_at).toLocaleString()}</span>
              {p.status === "SUCCEEDED_VERIFIED" && !p.rollback_of_id && (
                <Button
                  variant="secondary"
                  onClick={() => rollbackMutation.mutate(p.id)}
                  disabled={rollbackMutation.isPending}
                >
                  Roll back
                </Button>
              )}
            </div>
            <div>
              {p.previous_value ? displayValue(p.field, p.previous_value) : "—"} →{" "}
              {displayValue(p.field, p.proposed_value)}
            </div>
            {p.error_message && <p className="mt-1 text-red-600 dark:text-red-400">{p.error_message}</p>}
          </div>
        ))}
      </div>
      {rollbackMutation.isError && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">
          {rollbackMutation.error instanceof ApiError ? rollbackMutation.error.message : "Rollback failed"}
        </p>
      )}
    </AppShell>
  );
}
