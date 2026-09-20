"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, ErrorState, Badge, Button, Input, Textarea } from "@/components/ui";
import { PexelsPhotoPicker } from "@/components/pexels-photo-picker";
import { api, ApiError, getAccessToken } from "@/lib/api";

type GenerationType = "TEXT_TO_VIDEO" | "IMAGE_TO_VIDEO";
type PriorityMode = "AUTO" | "QUALITY" | "BALANCED" | "FAST" | "LOW_COST" | "FREE_FIRST";
type JobStatus =
  | "QUEUED"
  | "SUBMITTED"
  | "PROCESSING"
  | "RETRYING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "EXPIRED";

interface VideoJob {
  id: string;
  generation_type: GenerationType;
  priority_mode: PriorityMode;
  status: JobStatus;
  attempt: number;
  max_attempts: number;
  fallback_used: boolean;
  degraded_from_request: boolean;
  primary_model_id: string | null;
  selected_model_id: string | null;
  is_free_route: boolean;
  paid_fallback_used: boolean;
  resolution: string | null;
  aspect_ratio: string | null;
  duration_seconds: number | null;
  cost_estimate: number | null;
  cost_actual: number | null;
  latency_ms: number | null;
  error: string | null;
  error_code: string | null;
  created_at: string;
  submitted_at: string | null;
  completed_at: string | null;
}

interface BlockedResponse {
  status: "NO_FREE_VIDEO_MODEL" | "COST_VERIFICATION_REQUIRED";
  requires_credits: boolean | null;
  paid_fallback_used?: boolean;
  detail?: string;
}

function isBlockedResponse(data: VideoJob | BlockedResponse): data is BlockedResponse {
  return "status" in data && (data.status === "NO_FREE_VIDEO_MODEL" || data.status === "COST_VERIFICATION_REQUIRED");
}

const IN_FLIGHT: JobStatus[] = ["QUEUED", "SUBMITTED", "PROCESSING", "RETRYING"];

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

function statusTone(status: JobStatus): "default" | "success" | "warning" | "danger" {
  if (status === "FAILED" || status === "CANCELLED" || status === "EXPIRED") return "danger";
  if (status === "COMPLETED") return "success";
  return "warning";
}

function routeTone(job: VideoJob): "default" | "success" | "warning" {
  if (job.is_free_route) return "success";
  return "warning";
}

function routeLabel(job: VideoJob): string {
  if (job.is_free_route) return "FREE";
  if (job.paid_fallback_used) return "PAID (fallback)";
  return "PAID";
}

function JobVideoPreview({ job }: { job: VideoJob }) {
  const videoQuery = useQuery({
    queryKey: ["video-job-blob", job.id],
    queryFn: async () => {
      const token = getAccessToken();
      const res = await fetch(`${API_BASE_URL}/video/jobs/${job.id}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        credentials: "include",
      });
      if (!res.ok) throw new Error("Video output is not available yet.");
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    },
    enabled: job.status === "COMPLETED",
    staleTime: Infinity,
  });

  if (job.status !== "COMPLETED") return null;
  if (videoQuery.isLoading) return <p className="mt-2 text-xs muted">Loading video…</p>;
  if (videoQuery.isError || !videoQuery.data) return null;

  return (
    <div className="mt-3">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video controls src={videoQuery.data} className="w-full max-w-md rounded-lg" />
      <a href={videoQuery.data} download={`${job.id}.mp4`} className="mt-1 block text-xs text-brand-500 hover:underline">
        Download MP4
      </a>
    </div>
  );
}

function JobRoutingDetails({ job }: { job: VideoJob }) {
  const routingQuery = useQuery({
    queryKey: ["video-job-routing", job.id],
    queryFn: () => api.get<{
      remaining_fallback_chain: string[];
      degradation_notes: string[];
    }>(`/video/jobs/${job.id}/routing`),
    enabled: false,
  });

  return (
    <details className="mt-2 text-xs muted">
      <summary className="cursor-pointer" onClick={() => routingQuery.refetch()}>
        Routing details
      </summary>
      {routingQuery.isFetching && <p className="mt-1">Loading…</p>}
      {routingQuery.data && (
        <div className="mt-1 space-y-1">
          <div>Primary model: {job.primary_model_id ?? "—"}</div>
          <div>Selected model: {job.selected_model_id ?? "—"}</div>
          {routingQuery.data.remaining_fallback_chain.length > 0 && (
            <div>Remaining fallback: {routingQuery.data.remaining_fallback_chain.join(", ")}</div>
          )}
          {routingQuery.data.degradation_notes.length > 0 && (
            <div>Degradation notes: {routingQuery.data.degradation_notes.join("; ")}</div>
          )}
        </div>
      )}
    </details>
  );
}

function JobCard({ job }: { job: VideoJob }) {
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{job.id.slice(0, 8)}</span>
          <Badge tone={statusTone(job.status)}>{job.status}</Badge>
          <Badge tone={routeTone(job)}>{routeLabel(job)}</Badge>
          {job.degraded_from_request && <Badge tone="warning">Degraded config</Badge>}
          {job.fallback_used && <Badge>Fallback used</Badge>}
        </div>
        <span className="text-xs muted">{job.priority_mode} &middot; {job.generation_type.replaceAll("_", " ")}</span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs muted sm:grid-cols-4">
        <div>Attempt: {job.attempt}/{job.max_attempts}</div>
        <div>Resolution: {job.resolution ?? "—"}</div>
        <div>Duration: {job.duration_seconds ? `${job.duration_seconds}s` : "—"}</div>
        <div>
          Cost: {job.cost_actual != null ? `$${job.cost_actual.toFixed(4)}` : job.cost_estimate != null ? `~$${job.cost_estimate.toFixed(4)} est.` : "—"}
        </div>
      </div>

      {job.error && (
        <p className="mt-2 text-sm text-red-600 dark:text-red-400">
          {job.error_code && <span className="font-mono text-xs">[{job.error_code}]</span>} {job.error}
        </p>
      )}

      <JobVideoPreview job={job} />
      <JobRoutingDetails job={job} />
    </div>
  );
}

export default function VideoPage() {
  const queryClient = useQueryClient();
  const [prompt, setPrompt] = useState("");
  const [generationType, setGenerationType] = useState<GenerationType>("TEXT_TO_VIDEO");
  const [imageUrl, setImageUrl] = useState("");
  const [priorityMode, setPriorityMode] = useState<PriorityMode>("AUTO");
  const [allowPaidFallback, setAllowPaidFallback] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [duration, setDuration] = useState("");
  const [resolution, setResolution] = useState("");
  const [aspectRatio, setAspectRatio] = useState("");
  const [audio, setAudio] = useState(false);
  const [banner, setBanner] = useState<{ tone: "warning" | "danger"; message: string } | null>(null);

  const jobsQuery = useQuery({
    queryKey: ["video-jobs"],
    queryFn: () => api.get<VideoJob[]>("/video/jobs"),
    refetchInterval: (query) => (query.state.data?.some((j) => IN_FLIGHT.includes(j.status)) ? 5000 : false),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<VideoJob | BlockedResponse>("/video/jobs", {
        generation_type: generationType,
        prompt: prompt || null,
        priority_mode: priorityMode,
        input_image_urls: generationType === "IMAGE_TO_VIDEO" && imageUrl ? [imageUrl] : null,
        allow_paid_fallback: priorityMode === "FREE_FIRST" ? allowPaidFallback : false,
        duration: duration ? Number(duration) : null,
        resolution: resolution || null,
        aspect_ratio: aspectRatio || null,
        audio,
      }),
    onSuccess: (data) => {
      if (isBlockedResponse(data)) {
        setBanner({
          tone: "warning",
          message:
            data.status === "NO_FREE_VIDEO_MODEL"
              ? "No free video-generation model is currently available. Enable “Allow paid fallback” to use a paid model instead, or try again later."
              : `Cost verification required before this model can be used automatically. ${data.detail ?? ""}`,
        });
        return;
      }
      setBanner(null);
      setPrompt("");
      queryClient.invalidateQueries({ queryKey: ["video-jobs"] });
    },
    onError: (err) => setBanner({ tone: "danger", message: err instanceof ApiError ? err.message : "Failed to create video job." }),
  });

  return (
    <AppShell>
      <PageHeader
        title="AI Video Generation"
        description="Generate video from a text prompt or image via OpenRouter's video API. FREE_FIRST never spends credits unless you explicitly allow a paid fallback."
      />

      <div className="card mb-6 p-4">
        <h2 className="mb-3 font-medium">New video</h2>
        <div className="space-y-3">
          <Textarea
            placeholder="Describe the video you want…"
            value={prompt}
            maxLength={4000}
            rows={3}
            onChange={(e) => setPrompt(e.target.value)}
          />

          <div className="flex flex-wrap gap-3">
            <label className="text-sm">
              Type{" "}
              <select
                value={generationType}
                onChange={(e) => setGenerationType(e.target.value as GenerationType)}
                className="rounded-lg border bg-transparent px-2 py-1 text-sm"
                style={{ borderColor: "rgb(var(--border))" }}
              >
                <option value="TEXT_TO_VIDEO">Text to video</option>
                <option value="IMAGE_TO_VIDEO">Image to video</option>
              </select>
            </label>

            <label className="text-sm">
              Priority{" "}
              <select
                value={priorityMode}
                onChange={(e) => setPriorityMode(e.target.value as PriorityMode)}
                className="rounded-lg border bg-transparent px-2 py-1 text-sm"
                style={{ borderColor: "rgb(var(--border))" }}
              >
                <option value="AUTO">Auto</option>
                <option value="FREE_FIRST">Free first</option>
                <option value="LOW_COST">Low cost</option>
                <option value="BALANCED">Balanced</option>
                <option value="FAST">Fast</option>
                <option value="QUALITY">Quality</option>
              </select>
            </label>

            {priorityMode === "FREE_FIRST" && (
              <label className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={allowPaidFallback} onChange={(e) => setAllowPaidFallback(e.target.checked)} />
                Allow paid fallback
              </label>
            )}
          </div>

          {generationType === "IMAGE_TO_VIDEO" && (
            <div>
              <Input placeholder="Source image URL" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} />
              <PexelsPhotoPicker onSelect={setImageUrl} />
            </div>
          )}

          <details onToggle={(e) => setShowAdvanced((e.target as HTMLDetailsElement).open)}>
            <summary className="cursor-pointer text-xs muted">Advanced options</summary>
            {showAdvanced && (
              <div className="mt-2 flex flex-wrap gap-3">
                <Input
                  placeholder="Duration (seconds)"
                  type="number"
                  min={1}
                  max={60}
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  className="w-40"
                />
                <Input placeholder="Resolution (e.g. 720p)" value={resolution} onChange={(e) => setResolution(e.target.value)} className="w-40" />
                <Input placeholder="Aspect ratio (e.g. 16:9)" value={aspectRatio} onChange={(e) => setAspectRatio(e.target.value)} className="w-40" />
                <label className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={audio} onChange={(e) => setAudio(e.target.checked)} />
                  Generate audio
                </label>
              </div>
            )}
          </details>

          <Button onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !prompt}>
            {createMutation.isPending ? "Submitting…" : "Generate video"}
          </Button>

          {banner && (
            <div
              className={`rounded-lg border p-3 text-sm ${
                banner.tone === "danger"
                  ? "border-red-300 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                  : "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
              }`}
            >
              {banner.message}
            </div>
          )}
        </div>
      </div>

      {jobsQuery.isLoading && <LoadingState />}
      {jobsQuery.isError && <ErrorState message="Failed to load video jobs." />}
      {jobsQuery.data?.length === 0 && <EmptyState>No video jobs yet. Create one above.</EmptyState>}

      <div className="space-y-3">
        {jobsQuery.data?.map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
      </div>
    </AppShell>
  );
}
