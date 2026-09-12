"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Badge } from "@/components/ui";
import { api } from "@/lib/api";
import type { Trend } from "@/lib/types";

export default function TrendsPage() {
  const queryClient = useQueryClient();

  const trendsQuery = useQuery({
    queryKey: ["trends"],
    queryFn: () => api.get<Trend[]>("/trends"),
  });

  const refreshMutation = useMutation({
    mutationFn: () => api.post<Trend[]>("/trends/refresh"),
    onSuccess: (data) => queryClient.setQueryData(["trends"], data),
  });

  return (
    <AppShell>
      <PageHeader
        title="Trend Engine"
        description="Detected from your own video history and tracked competitors — never invented."
      />

      <Button onClick={() => refreshMutation.mutate()} disabled={refreshMutation.isPending}>
        {refreshMutation.isPending ? "Refreshing…" : "Refresh trends"}
      </Button>

      {trendsQuery.isLoading && <LoadingState />}
      {trendsQuery.data?.length === 0 && (
        <div className="mt-4">
          <EmptyState>
            No trends detected yet. Connect a channel and track competitors, then refresh — trends
            need at least a few videos sharing a keyword before a signal is confident enough to show.
          </EmptyState>
        </div>
      )}

      <div className="mt-4 space-y-3">
        {trendsQuery.data?.map((t) => (
          <div key={t.id} className="card p-4">
            <div className="flex items-center justify-between">
              <span className="font-medium">{t.keyword}</span>
              <Badge>{t.source.replaceAll("_", " ")}</Badge>
            </div>
            <div className="mt-1 text-sm muted">n={t.sample_size} · opportunity {t.opportunity_score}</div>
            {t.explanation && <p className="mt-2 text-sm">{t.explanation}</p>}
          </div>
        ))}
      </div>
    </AppShell>
  );
}
