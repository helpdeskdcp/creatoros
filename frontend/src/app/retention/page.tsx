"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface RetentionMetric {
  id: string;
  early_dropoff_pct: number | null;
  hook_failure_detected: boolean | null;
  data_quality: string;
  insight: string | null;
}

export default function RetentionPage() {
  const [videoId, setVideoId] = useState("");
  const [submittedId, setSubmittedId] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["retention", submittedId],
    queryFn: () => api.get<RetentionMetric[]>(`/retention/video/${submittedId}`),
    enabled: !!submittedId,
  });

  const computeMutation = useMutation({
    mutationFn: () => api.post<RetentionMetric>(`/retention/video/${videoId}/compute`),
    onSuccess: () => setSubmittedId(videoId),
  });

  return (
    <AppShell>
      <PageHeader
        title="Retention Intelligence"
        description="Only computed from authorized YouTube Analytics data — otherwise INSUFFICIENT_DATA."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (videoId.trim()) computeMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="Video ID (CreatorOS UUID)" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
        <Button type="submit" disabled={computeMutation.isPending}>
          Compute retention
        </Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No retention data computed yet for this video.</EmptyState>}

      <div className="space-y-2">
        {query.data?.map((r) => (
          <div key={r.id} className="card p-4 text-sm">
            <Badge tone={r.data_quality === "INSUFFICIENT_DATA" ? "warning" : "success"}>
              {r.data_quality}
            </Badge>
            <p className="mt-2">{r.insight}</p>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
