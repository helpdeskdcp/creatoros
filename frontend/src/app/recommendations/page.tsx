"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Badge } from "@/components/ui";
import { api } from "@/lib/api";
import type { Recommendation } from "@/lib/types";

export default function RecommendationsPage() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: ["recommendations"],
    queryFn: () => api.get<Recommendation[]>("/recommendations"),
  });

  const generateMutation = useMutation({
    mutationFn: () => api.post<Recommendation[]>("/recommendations/next-best-video"),
    onSuccess: (data) => queryClient.setQueryData(["recommendations"], data),
  });

  return (
    <AppShell>
      <PageHeader
        title="Next Best Video"
        description="Viral, discovery, subscriber, retention, and audience-fit potential are always shown separately."
      />

      <Button onClick={() => generateMutation.mutate()} disabled={generateMutation.isPending}>
        {generateMutation.isPending ? "Generating…" : "Generate Top 10"}
      </Button>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && (
        <div className="mt-4">
          <EmptyState>
            No recommendations yet. Recommendations are generated from topics that already have a
            HIGH or MEDIUM opportunity score — score some topics first on the Opportunities page.
          </EmptyState>
        </div>
      )}

      <div className="mt-4 space-y-4">
        {query.data?.map((r) => (
          <div key={r.id} className="card p-4">
            <div className="flex items-center justify-between">
              <span className="font-semibold">
                #{r.rank} {r.topic}
              </span>
              <Badge>{r.confidence} confidence</Badge>
            </div>
            <p className="mt-2 text-sm">{r.reason}</p>
            {r.hook && <p className="mt-1 text-sm italic">&ldquo;{r.hook}&rdquo;</p>}
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
              <ScoreChip label="Viral" value={r.viral_potential_score} />
              <ScoreChip label="Discovery" value={r.discovery_score} />
              <ScoreChip label="Subscriber" value={r.subscriber_potential_score} />
              <ScoreChip label="Retention" value={r.retention_potential_score} />
              <ScoreChip label="Audience Fit" value={r.audience_fit_score} />
            </div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}

function ScoreChip({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg border p-2 text-center" style={{ borderColor: "rgb(var(--border))" }}>
      <div className="muted">{label}</div>
      <div className="font-semibold">{value ?? "—"}</div>
    </div>
  );
}
