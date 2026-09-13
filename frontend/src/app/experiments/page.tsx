"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface Variant {
  id: string;
  label: string;
  content: string;
  sample_size: number;
  metric_value: number | null;
  video_id: string | null;
  measured_at: string | null;
}
interface Experiment {
  id: string;
  experiment_type: string;
  hypothesis: string;
  status: string;
  confidence: string | null;
  variants: Variant[];
}

export default function ExperimentsPage() {
  const queryClient = useQueryClient();
  const [hypothesis, setHypothesis] = useState("");

  const query = useQuery({
    queryKey: ["experiments"],
    queryFn: () => api.get<Experiment[]>("/experiments"),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.post<Experiment>("/experiments", {
        experiment_type: "title",
        hypothesis,
        metric: "ctr",
        minimum_sample_size: 30,
        variants: ["Control title", "Variant title"],
      }),
    onSuccess: () => {
      setHypothesis("");
      queryClient.invalidateQueries({ queryKey: ["experiments"] });
    },
  });

  const startMutation = useMutation({
    mutationFn: (id: string) => api.post<Experiment>(`/experiments/${id}/start`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiments"] }),
  });

  const measureMutation = useMutation({
    mutationFn: (variantId: string) =>
      api.post<{ variant: Variant; status: string }>(`/experiments/variants/${variantId}/measure`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["experiments"] }),
  });

  return (
    <AppShell>
      <PageHeader title="Growth Experiments" description="A winner is never declared before every variant hits its minimum sample size." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (hypothesis.trim()) createMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input
          placeholder="Hypothesis (e.g. data-driven titles beat story titles)"
          value={hypothesis}
          onChange={(e) => setHypothesis(e.target.value)}
        />
        <Button type="submit">Create A/B test</Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No experiments yet.</EmptyState>}

      <div className="space-y-3">
        {query.data?.map((exp) => (
          <div key={exp.id} className="card p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{exp.hypothesis}</span>
              <Badge>{exp.status}</Badge>
            </div>
            {exp.status === "DRAFT" && (
              <Button variant="secondary" className="mt-2" onClick={() => startMutation.mutate(exp.id)}>
                Start
              </Button>
            )}
            <div className="mt-2 space-y-1 text-sm">
              {exp.variants.map((v) => (
                <div key={v.id} className="flex items-center gap-2">
                  <span>
                    {v.label}: {v.metric_value ?? "—"} (n={v.sample_size})
                    {v.measured_at && <span className="muted"> · measured from real analytics</span>}
                  </span>
                  {exp.status === "RUNNING" && v.video_id && (
                    <Button
                      variant="secondary"
                      onClick={() => measureMutation.mutate(v.id)}
                      disabled={measureMutation.isPending}
                    >
                      Measure from real data
                    </Button>
                  )}
                  {exp.status === "RUNNING" && !v.video_id && (
                    <span className="text-xs muted">
                      Link a video via API (POST /experiments/variants/{"{id}"}/link-video) to measure automatically
                    </span>
                  )}
                </div>
              ))}
            </div>
            {exp.confidence && <div className="mt-1 text-xs muted">Confidence: {exp.confidence}</div>}
          </div>
        ))}
      </div>
    </AppShell>
  );
}
