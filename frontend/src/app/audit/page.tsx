"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface AuditLog {
  id: string;
  created_at: string;
  action_type: string;
  provider: string | null;
  result: string;
  failure_reason: string | null;
}

export default function AuditPage() {
  const query = useQuery({ queryKey: ["audit-logs"], queryFn: () => api.get<AuditLog[]>("/audit") });

  return (
    <AppShell>
      <PageHeader title="Audit Log" description="Every autonomous action is recorded. OAuth tokens and secrets are never logged." />

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No audit entries yet.</EmptyState>}

      <div className="space-y-2">
        {query.data?.map((log) => (
          <div key={log.id} className="card flex items-center justify-between p-3 text-sm">
            <div>
              <div className="font-medium">{log.action_type}</div>
              <div className="text-xs muted">{new Date(log.created_at).toLocaleString()}</div>
            </div>
            <Badge tone={log.result === "success" ? "success" : log.result === "blocked" ? "warning" : "danger"}>
              {log.result}
            </Badge>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
