"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input } from "@/components/ui";
import { api } from "@/lib/api";

interface ScriptVersion {
  id: string;
  version_number: number;
  full_text: string | null;
}
interface Script {
  id: string;
  title: string;
  format: string;
  versions: ScriptVersion[];
}

const FORMATS = ["SHORT", "FIVE_MIN", "TEN_MIN", "FIFTEEN_MIN", "LONG_FORM"];

export default function ScriptsPage() {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [format, setFormat] = useState(FORMATS[1]);

  const query = useQuery({ queryKey: ["scripts"], queryFn: () => api.get<Script[]>("/scripts") });

  const generateMutation = useMutation({
    mutationFn: () => api.post<Script>("/scripts/generate", { title, format, key_points: [] }),
    onSuccess: (data) => {
      queryClient.setQueryData(["scripts"], (prev: Script[] | undefined) => [data, ...(prev ?? [])]);
      setTitle("");
    },
  });

  return (
    <AppShell>
      <PageHeader title="Script Engine" description="Hook, setup, promise, main points, CTA, ending — with full version history." />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) generateMutation.mutate();
        }}
        className="mb-6 flex flex-wrap gap-2"
      >
        <Input
          placeholder="Video title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="flex-1"
        />
        <select
          value={format}
          onChange={(e) => setFormat(e.target.value)}
          className="rounded-lg border bg-transparent px-3 py-2 text-sm"
          style={{ borderColor: "rgb(var(--border))" }}
        >
          {FORMATS.map((f) => (
            <option key={f} value={f}>
              {f.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <Button type="submit" disabled={generateMutation.isPending}>
          {generateMutation.isPending ? "Writing…" : "Generate script"}
        </Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No scripts yet — generate one above.</EmptyState>}

      <div className="space-y-3">
        {query.data?.map((s) => (
          <details key={s.id} className="card p-4">
            <summary className="cursor-pointer font-medium">
              {s.title} <span className="muted">({s.format})</span>
            </summary>
            {s.versions.map((v) => (
              <pre key={v.id} className="mt-3 whitespace-pre-wrap text-sm">
                {v.full_text}
              </pre>
            ))}
          </details>
        ))}
      </div>
    </AppShell>
  );
}
