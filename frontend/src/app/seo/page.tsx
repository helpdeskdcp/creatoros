"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Textarea } from "@/components/ui";
import { api } from "@/lib/api";

interface SeoRecord {
  id: string;
  title_suggestions: string[];
  description: string | null;
  keywords: string[];
  hashtags: string[];
}

export default function SeoPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const query = useQuery({ queryKey: ["seo"], queryFn: () => api.get<SeoRecord[]>("/seo") });

  const generateMutation = useMutation({
    mutationFn: () => api.post<SeoRecord>("/seo/generate", { title, description }),
    onSuccess: (data) => {
      queryClient.setQueryData(["seo"], (prev: SeoRecord[] | undefined) => [data, ...(prev ?? [])]);
      setTitle("");
      setDescription("");
    },
  });

  return (
    <AppShell>
      <PageHeader title="SEO Engine" description="Natural keywords, chapters, hashtags — never spammy." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) generateMutation.mutate();
        }}
        className="mb-6 space-y-2"
      >
        <Input placeholder="Video title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Textarea
          placeholder="Video description / summary"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
        <Button type="submit" disabled={generateMutation.isPending}>
          {generateMutation.isPending ? "Generating…" : "Generate SEO"}
        </Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No SEO records yet.</EmptyState>}

      <div className="space-y-3">
        {query.data?.map((s) => (
          <div key={s.id} className="card p-4 text-sm">
            <div className="font-medium">Titles: {s.title_suggestions.join(" / ")}</div>
            <div className="mt-1 muted">Keywords: {s.keywords.join(", ")}</div>
            <div className="mt-1 muted">Hashtags: {s.hashtags.join(" ")}</div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
