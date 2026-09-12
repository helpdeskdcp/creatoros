"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface Hook {
  id: string;
  text: string;
  category: string;
  hook_score: number | null;
  clarity_score: number | null;
  curiosity_score: number | null;
}

export default function HooksPage() {
  const queryClient = useQueryClient();
  const [topic, setTopic] = useState("");

  const query = useQuery({ queryKey: ["hooks"], queryFn: () => api.get<Hook[]>("/hooks") });

  const generateMutation = useMutation({
    mutationFn: () => api.post<Hook[]>("/hooks/generate", { topic, count: 6 }),
    onSuccess: (data) => {
      queryClient.setQueryData(["hooks"], (prev: Hook[] | undefined) => [...data, ...(prev ?? [])]);
      setTopic("");
    },
  });

  return (
    <AppShell>
      <PageHeader title="Hook Engine" description="AI-generated, scored 0-100 for clarity, curiosity, specificity, audience fit." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (topic.trim()) generateMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="Video topic" value={topic} onChange={(e) => setTopic(e.target.value)} />
        <Button type="submit" disabled={generateMutation.isPending}>
          {generateMutation.isPending ? "Generating…" : "Generate hooks"}
        </Button>
      </form>
      {generateMutation.isError && (
        <p className="mb-4 text-sm text-red-600 dark:text-red-400">
          Generation failed — check that Ollama (or your configured AI provider) is reachable.
        </p>
      )}

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No hooks yet — generate some above.</EmptyState>}

      <div className="space-y-2">
        {query.data?.map((h) => (
          <div key={h.id} className="card p-3">
            <div className="flex items-center justify-between">
              <span>{h.text}</span>
              <Badge>{h.category}</Badge>
            </div>
            <div className="mt-1 text-xs muted">Score: {h.hook_score}</div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
