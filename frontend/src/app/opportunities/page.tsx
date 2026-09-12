"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface Topic {
  id: string;
  title: string;
  description: string | null;
  trend_id: string | null;
}

interface Opportunity {
  id: string;
  topic_id: string;
  level: string;
  sample_size: number;
  explanation: string;
}

export default function OpportunitiesPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");

  const topicsQuery = useQuery({ queryKey: ["topics"], queryFn: () => api.get<Topic[]>("/topics") });

  const createMutation = useMutation({
    mutationFn: (t: string) => api.post<Topic>("/topics", { title: t }),
    onSuccess: () => {
      setTitle("");
      queryClient.invalidateQueries({ queryKey: ["topics"] });
    },
  });

  const computeMutation = useMutation({
    mutationFn: (topicId: string) => api.post<Opportunity>(`/topics/${topicId}/opportunity`),
    onSuccess: (data, topicId) => {
      queryClient.setQueryData(["opportunity", topicId], data);
    },
  });

  return (
    <AppShell>
      <PageHeader
        title="Topic Opportunity Engine"
        description="Link a topic to a detected trend on the Trends page for the strongest scoring."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) createMutation.mutate(title.trim());
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="New topic idea" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit">Add topic</Button>
      </form>

      {topicsQuery.isLoading && <LoadingState />}
      {topicsQuery.data?.length === 0 && <EmptyState>No topics yet — add one above.</EmptyState>}

      <div className="space-y-3">
        {topicsQuery.data?.map((topic) => (
          <TopicRow key={topic.id} topic={topic} onCompute={() => computeMutation.mutate(topic.id)} />
        ))}
      </div>
    </AppShell>
  );
}

function TopicRow({ topic, onCompute }: { topic: Topic; onCompute: () => void }) {
  const opportunityQuery = useQuery<Opportunity | undefined>({
    queryKey: ["opportunity", topic.id],
    queryFn: () => Promise.resolve(undefined),
    enabled: false,
  });
  const opportunity = opportunityQuery.data;

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between">
        <span className="font-medium">{topic.title}</span>
        <Button variant="secondary" onClick={onCompute}>
          Compute opportunity
        </Button>
      </div>
      {opportunity && (
        <div className="mt-2">
          <Badge
            tone={
              opportunity.level === "HIGH_OPPORTUNITY"
                ? "success"
                : opportunity.level === "MEDIUM_OPPORTUNITY"
                  ? "warning"
                  : "default"
            }
          >
            {opportunity.level}
          </Badge>
          <p className="mt-2 text-sm muted">{opportunity.explanation}</p>
        </div>
      )}
    </div>
  );
}
