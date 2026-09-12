"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, Button, Badge } from "@/components/ui";
import { api } from "@/lib/api";

interface ControlCenter {
  kill_switch: { is_active: boolean; activated_at: string | null; reason: string | null };
  connected_channels: number;
  active_publishing_rules: number;
  pending_runs: number;
  completed_runs: number;
  failed_runs: number;
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");

  const query = useQuery({
    queryKey: ["control-center"],
    queryFn: () => api.get<ControlCenter>("/settings/control-center"),
  });

  const activateMutation = useMutation({
    mutationFn: () => api.post("/settings/kill-switch/activate", { reason: reason || undefined }),
    onSuccess: () => {
      setReason("");
      queryClient.invalidateQueries({ queryKey: ["control-center"] });
    },
  });

  const deactivateMutation = useMutation({
    mutationFn: () => api.post("/settings/kill-switch/deactivate"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["control-center"] }),
  });

  const killSwitch = query.data?.kill_switch;

  return (
    <AppShell>
      <PageHeader title="Autonomous Control Center" description="Every autonomous publishing/distribution action checks this before starting." />

      {query.isLoading && <LoadingState />}

      {killSwitch && (
        <div className="card mb-6 p-4">
          <div className="flex items-center gap-3">
            <span className="font-medium">Autonomous automation:</span>
            <Badge tone={killSwitch.is_active ? "danger" : "success"}>
              {killSwitch.is_active ? "STOPPED" : "RUNNING"}
            </Badge>
          </div>
          {killSwitch.reason && <p className="mt-1 text-sm muted">Reason: {killSwitch.reason}</p>}
          <div className="mt-3 flex gap-2">
            {!killSwitch.is_active ? (
              <>
                <input
                  placeholder="Reason for stopping (optional)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="flex-1 rounded-lg border bg-transparent px-3 py-2 text-sm"
                  style={{ borderColor: "rgb(var(--border))" }}
                />
                <Button variant="danger" onClick={() => activateMutation.mutate()}>
                  Emergency stop
                </Button>
              </>
            ) : (
              <Button onClick={() => deactivateMutation.mutate()}>Resume automation</Button>
            )}
          </div>
          <p className="mt-2 text-xs muted">
            Stopping never cancels work already in flight and never deletes data — it only blocks
            new autonomous actions from starting.
          </p>
        </div>
      )}

      {query.data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCard label="Connected Channels" value={query.data.connected_channels} />
          <StatCard label="Active Publishing Rules" value={query.data.active_publishing_rules} />
          <StatCard label="Pending Approval" value={query.data.pending_runs} />
          <StatCard label="Published" value={query.data.completed_runs} />
          <StatCard label="Failed" value={query.data.failed_runs} />
        </div>
      )}
    </AppShell>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="card p-4">
      <div className="text-xs muted">{label}</div>
      <div className="mt-1 text-xl font-bold">{value}</div>
    </div>
  );
}
