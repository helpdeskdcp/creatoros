"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface PublishingRun {
  id: string;
  mode: string;
  state: string;
  youtube_video_id: string | null;
  failure_reason: string | null;
  requires_approval: boolean;
}

export default function PublishingPage() {
  const query = useQuery({
    queryKey: ["publishing-runs"],
    queryFn: () => api.get<PublishingRun[]>("/publishing/runs"),
  });

  return (
    <AppShell>
      <PageHeader
        title="Publishing"
        description="Every automated publish passes a 13-step safety gate before anything is uploaded. See Control Center for the kill switch and publishing rules."
      />

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && (
        <EmptyState>No publishing runs yet. Create one via the API (POST /publishing/runs) once you have a video ready.</EmptyState>
      )}

      <div className="space-y-2">
        {query.data?.map((run) => (
          <div key={run.id} className="card flex items-center justify-between p-4 text-sm">
            <div>
              <div className="font-medium">{run.mode}</div>
              {run.failure_reason && <div className="mt-1 text-red-600 dark:text-red-400">{run.failure_reason}</div>}
            </div>
            <div className="flex items-center gap-2">
              {run.requires_approval && <Badge tone="warning">Needs approval</Badge>}
              <Badge>{run.state}</Badge>
            </div>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
