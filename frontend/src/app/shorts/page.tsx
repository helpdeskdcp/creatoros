"use client";

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, ErrorState, Badge, Button } from "@/components/ui";
import { api, ApiError, getAccessToken } from "@/lib/api";

interface VideoProcessingJob {
  id: string;
  status: string;
  progress_pct: number;
  error: string | null;
  source_duration_seconds: number | null;
  created_at: string;
}

interface ShortCandidate {
  id: string;
  job_id: string;
  rank: number;
  start_seconds: number;
  end_seconds: number;
  score: number;
  score_breakdown: Record<string, number>;
  transcript_excerpt: string;
  status: string;
  generated_title: string | null;
  generated_description: string | null;
  generated_hook: string | null;
  rendered_media_asset_id: string | null;
  render_error: string | null;
  rendered_at: string | null;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

async function uploadVideoAndCreateJob(file: File): Promise<VideoProcessingJob> {
  const token = getAccessToken();
  const formData = new FormData();
  formData.append("purpose", "VIDEO");
  formData.append("file", file);

  const uploadRes = await fetch(`${API_BASE_URL}/media/upload`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: formData,
    credentials: "include",
  });
  if (!uploadRes.ok) {
    const body = await uploadRes.json().catch(() => null);
    throw new ApiError(uploadRes.status, body?.error?.code ?? "upload_failed", body?.error?.message ?? "Upload failed");
  }
  const asset = await uploadRes.json();

  return api.post<VideoProcessingJob>("/shorts/jobs", {
    source_media_asset_id: asset.id,
    idempotency_key: `${asset.id}-${Date.now()}`,
  });
}

function statusTone(status: string): "default" | "success" | "warning" | "danger" {
  if (status === "FAILED" || status === "RENDER_FAILED") return "danger";
  if (status === "COMPLETED" || status === "READY_FOR_REVIEW" || status === "RENDERED") return "success";
  return "warning";
}

function CandidateCard({ candidate }: { candidate: ShortCandidate }) {
  const queryClient = useQueryClient();
  const approveMutation = useMutation({
    mutationFn: () => api.post<ShortCandidate>(`/shorts/candidates/${candidate.id}/approve`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["short-candidates", candidate.job_id] }),
  });
  const rejectMutation = useMutation({
    mutationFn: () => api.post<ShortCandidate>(`/shorts/candidates/${candidate.id}/reject`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["short-candidates", candidate.job_id] }),
  });

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Badge>#{candidate.rank}</Badge>
          <span className="text-sm font-medium">Score: {candidate.score.toFixed(1)}</span>
          <Badge tone={statusTone(candidate.status)}>{candidate.status}</Badge>
        </div>
        <span className="text-xs muted">
          {candidate.start_seconds.toFixed(1)}s - {candidate.end_seconds.toFixed(1)}s
        </span>
      </div>
      {candidate.generated_title && <p className="mt-2 font-medium">{candidate.generated_title}</p>}
      {candidate.generated_hook && <p className="mt-1 text-sm">{candidate.generated_hook}</p>}
      <p className="mt-1 text-xs muted line-clamp-2">&ldquo;{candidate.transcript_excerpt}&rdquo;</p>
      <details className="mt-2 text-xs muted">
        <summary className="cursor-pointer">Score breakdown</summary>
        <ul className="mt-1 space-y-0.5">
          {Object.entries(candidate.score_breakdown).map(([key, value]) => (
            <li key={key}>
              {key.replaceAll("_", " ")}: {value}
            </li>
          ))}
        </ul>
      </details>
      {candidate.render_error && (
        <p className="mt-2 text-red-600 dark:text-red-400">{candidate.render_error}</p>
      )}
      {candidate.rendered_media_asset_id && (
        <a
          href={`${API_BASE_URL}/media/${candidate.rendered_media_asset_id}`}
          target="_blank"
          rel="noreferrer"
          className="mt-2 block text-brand-500 hover:underline"
        >
          Preview rendered clip
        </a>
      )}
      {candidate.status === "PENDING_APPROVAL" && (
        <div className="mt-3 flex gap-2">
          <Button onClick={() => approveMutation.mutate()} disabled={approveMutation.isPending}>
            Approve &amp; render
          </Button>
          <Button variant="secondary" onClick={() => rejectMutation.mutate()} disabled={rejectMutation.isPending}>
            Reject
          </Button>
        </div>
      )}
    </div>
  );
}

function JobRow({ job }: { job: VideoProcessingJob }) {
  const candidatesQuery = useQuery({
    queryKey: ["short-candidates", job.id],
    queryFn: () => api.get<ShortCandidate[]>(`/shorts/jobs/${job.id}/candidates`),
    enabled: job.status === "READY_FOR_REVIEW" || job.status === "COMPLETED",
    refetchInterval: job.status === "READY_FOR_REVIEW" ? 5000 : false,
  });

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">Job {job.id.slice(0, 8)}</div>
          {job.source_duration_seconds && (
            <div className="text-xs muted">Source: {job.source_duration_seconds.toFixed(0)}s</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={statusTone(job.status)}>{job.status.replaceAll("_", " ")}</Badge>
          <span className="text-xs muted">{job.progress_pct}%</span>
        </div>
      </div>
      {job.error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{job.error}</p>}

      {candidatesQuery.data && candidatesQuery.data.length > 0 && (
        <div className="mt-4 space-y-2">
          {candidatesQuery.data.map((c) => (
            <CandidateCard key={c.id} candidate={c} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function ShortsPage() {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: ["video-processing-jobs"],
    queryFn: () => api.get<VideoProcessingJob[]>("/shorts/jobs"),
    refetchInterval: 5000,
  });

  const uploadMutation = useMutation({
    mutationFn: uploadVideoAndCreateJob,
    onSuccess: () => {
      setError(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      queryClient.invalidateQueries({ queryKey: ["video-processing-jobs"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Upload failed"),
  });

  return (
    <AppShell>
      <PageHeader
        title="Long Video &rarr; Shorts Factory"
        description="Upload a long video: CreatorOS transcribes it, scores real candidate moments (never a random 30-second window), and renders vertical clips with burned-in captions once you approve a moment."
      />

      <div className="card mb-6 p-4">
        <h2 className="mb-3 font-medium">Upload a source video</h2>
        <input
          ref={fileInputRef}
          type="file"
          accept="video/mp4,video/quicktime,video/webm"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) uploadMutation.mutate(file);
          }}
          className="text-sm"
        />
        {uploadMutation.isPending && <p className="mt-2 text-sm muted">Uploading and queuing for processing&hellip;</p>}
        {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
      </div>

      {jobsQuery.isLoading && <LoadingState />}
      {jobsQuery.isError && <ErrorState message="Failed to load processing jobs." />}
      {jobsQuery.data?.length === 0 && <EmptyState>No videos processed yet. Upload one above.</EmptyState>}

      <div className="space-y-3">
        {jobsQuery.data?.map((job) => (
          <JobRow key={job.id} job={job} />
        ))}
      </div>
    </AppShell>
  );
}
