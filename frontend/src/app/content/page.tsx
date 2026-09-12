"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input } from "@/components/ui";
import { api } from "@/lib/api";
import type { ContentItem } from "@/lib/types";

const STATUSES = [
  "IDEA", "RESEARCH", "OUTLINE", "SCRIPT", "RECORDING", "EDITING",
  "THUMBNAIL", "SEO", "READY", "PUBLISHED", "ANALYZING",
];

export default function ContentPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");

  const query = useQuery({
    queryKey: ["content-items"],
    queryFn: () => api.get<ContentItem[]>("/content/items"),
  });

  const createMutation = useMutation({
    mutationFn: () => api.post<ContentItem>("/content/items", { title }),
    onSuccess: () => {
      setTitle("");
      queryClient.invalidateQueries({ queryKey: ["content-items"] });
    },
  });

  const updateStatusMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch<ContentItem>(`/content/items/${id}/status`, { status }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["content-items"] }),
  });

  const items = query.data ?? [];

  return (
    <AppShell>
      <PageHeader title="Content Workspace" description="Kanban pipeline from idea to published." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) createMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="New content idea" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit">Add card</Button>
      </form>

      {query.isLoading && <LoadingState />}
      {items.length === 0 && <EmptyState>No content items yet.</EmptyState>}

      <div className="flex gap-4 overflow-x-auto pb-4">
        {STATUSES.map((status) => (
          <div key={status} className="w-64 shrink-0">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide muted">
              {status} ({items.filter((i) => i.status === status).length})
            </div>
            <div className="space-y-2">
              {items
                .filter((i) => i.status === status)
                .map((item) => (
                  <div key={item.id} className="card p-3 text-sm">
                    <div>{item.title}</div>
                    <select
                      value={item.status}
                      onChange={(e) =>
                        updateStatusMutation.mutate({ id: item.id, status: e.target.value })
                      }
                      className="mt-2 w-full rounded border bg-transparent px-1 py-1 text-xs"
                      style={{ borderColor: "rgb(var(--border))" }}
                    >
                      {STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </select>
                  </div>
                ))}
            </div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
