"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface Campaign {
  id: string;
  name: string;
  status: string;
}

export default function DistributionPage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");

  const query = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api.get<Campaign[]>("/distribution/campaigns"),
  });

  const createMutation = useMutation({
    mutationFn: () => api.post<Campaign>("/distribution/campaigns", { name }),
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["campaigns"] });
    },
  });

  return (
    <AppShell>
      <PageHeader
        title="Distribution Campaigns"
        description="YouTube publishing is fully wired. Instagram/Facebook/X/LinkedIn require each platform's own developer-app authorization before their assets can actually be posted."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) createMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input placeholder="Campaign name" value={name} onChange={(e) => setName(e.target.value)} />
        <Button type="submit">Create campaign</Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No campaigns yet.</EmptyState>}

      <div className="space-y-2">
        {query.data?.map((c) => (
          <div key={c.id} className="card flex items-center justify-between p-4">
            <span>{c.name}</span>
            <Badge>{c.status}</Badge>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
