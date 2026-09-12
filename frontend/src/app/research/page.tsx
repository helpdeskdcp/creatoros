"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface ResearchProject {
  id: string;
  title: string;
  summary: string | null;
}
interface ResearchSource {
  id: string;
  url: string;
  title: string | null;
  credibility: string;
}

export default function ResearchPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["research-projects"],
    queryFn: () => api.get<ResearchProject[]>("/research"),
  });

  const createMutation = useMutation({
    mutationFn: () => api.post<ResearchProject>("/research", { title }),
    onSuccess: () => {
      setTitle("");
      queryClient.invalidateQueries({ queryKey: ["research-projects"] });
    },
  });

  return (
    <AppShell>
      <PageHeader title="Research Workspace" description="Sources are unverified until explicitly reviewed — never auto-verified." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) createMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="Research project title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Button type="submit">Create</Button>
      </form>

      {projectsQuery.isLoading && <LoadingState />}
      {projectsQuery.data?.length === 0 && <EmptyState>No research projects yet.</EmptyState>}

      <div className="space-y-3">
        {projectsQuery.data?.map((p) => (
          <ProjectRow key={p.id} project={p} />
        ))}
      </div>
    </AppShell>
  );
}

function ProjectRow({ project }: { project: ResearchProject }) {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");

  const sourcesQuery = useQuery({
    queryKey: ["research-sources", project.id],
    queryFn: () => api.get<ResearchSource[]>(`/research/${project.id}/sources`),
  });

  const addSourceMutation = useMutation({
    mutationFn: () => api.post<ResearchSource>(`/research/${project.id}/sources`, { url }),
    onSuccess: () => {
      setUrl("");
      queryClient.invalidateQueries({ queryKey: ["research-sources", project.id] });
    },
  });

  return (
    <div className="card p-4">
      <div className="font-medium">{project.title}</div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) addSourceMutation.mutate();
        }}
        className="mt-2 flex gap-2"
      >
        <Input placeholder="Source URL" value={url} onChange={(e) => setUrl(e.target.value)} />
        <Button type="submit" variant="secondary">
          Add source
        </Button>
      </form>
      <div className="mt-2 space-y-1">
        {sourcesQuery.data?.map((s) => (
          <div key={s.id} className="flex items-center gap-2 text-sm">
            <Badge tone={s.credibility === "verified" ? "success" : "warning"}>{s.credibility}</Badge>
            <span className="truncate">{s.url}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
