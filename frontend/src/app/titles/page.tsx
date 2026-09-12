"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input } from "@/components/ui";
import { api } from "@/lib/api";

interface Title {
  id: string;
  text: string;
  ctr_potential_score: number | null;
}

export default function TitlesPage() {
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");

  const query = useQuery({ queryKey: ["titles"], queryFn: () => api.get<Title[]>("/titles") });

  const generateMutation = useMutation({
    mutationFn: () => api.post<Title[]>("/titles/generate", { topic, count: 6 }),
    onSuccess: (data) => {
      queryClient.setQueryData(["titles"], (prev: Title[] | undefined) => [...data, ...(prev ?? [])]);
      setTopic("");
    },
  });

  return (
    <AppShell>
      <PageHeader title="Title Engine" description="Never misleading clickbait, spam, or keyword-stuffed." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) generateMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="Video topic" value={topic} onChange={(e) => setTopic(e.target.value)} />
        <Button type="submit" disabled={generateMutation.isPending}>
          {generateMutation.isPending ? "Generating…" : "Generate titles"}
        </Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No titles yet — generate some above.</EmptyState>}

      <div className="space-y-2">
        {query.data?.map((t) => (
          <div key={t.id} className="card flex items-center justify-between p-3">
            <span>{t.text}</span>
            <span className="text-xs muted">CTR potential: {t.ctr_potential_score}</span>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
