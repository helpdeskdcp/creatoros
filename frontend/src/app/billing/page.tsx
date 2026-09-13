"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, ErrorState, Button, Input, Badge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";

interface Organization {
  id: string;
  name: string;
  plan: "FREE" | "PRO" | "AGENCY" | "ENTERPRISE";
  is_white_label: boolean;
  white_label_brand_name: string | null;
}

interface Subscription {
  id: string;
  plan: string;
  status: string;
  payment_provider: string;
  current_period_end: string | null;
}

interface Member {
  id: string;
  user_id: string;
  role: "OWNER" | "ADMIN" | "MEMBER";
}

type PlanLimits = Record<
  string,
  {
    max_channels: number;
    max_team_members: number;
    max_competitors_tracked: number;
    white_label: boolean;
    ai_generations_per_day: number;
  }
>;

function formatLimit(value: number): string {
  return value === -1 ? "Unlimited" : String(value);
}

function statusTone(status: string): "default" | "success" | "warning" | "danger" {
  if (status === "ACTIVE" || status === "TRIALING") return "success";
  if (status === "PAST_DUE") return "danger";
  if (status === "CONFIGURATION_REQUIRED") return "warning";
  return "default";
}

export default function BillingPage() {
  const queryClient = useQueryClient();
  const [checkoutError, setCheckoutError] = useState<string | null>(null);
  const [inviteUserId, setInviteUserId] = useState("");

  const orgQuery = useQuery({
    queryKey: ["billing", "organization"],
    queryFn: () => api.get<Organization>("/billing/me"),
  });
  const subscriptionQuery = useQuery({
    queryKey: ["billing", "subscription"],
    queryFn: () => api.get<Subscription>("/billing/subscription"),
    enabled: !!orgQuery.data,
  });
  const plansQuery = useQuery({
    queryKey: ["billing", "plans"],
    queryFn: () => api.get<PlanLimits>("/billing/plans"),
  });
  const membersQuery = useQuery({
    queryKey: ["billing", "members", orgQuery.data?.id],
    queryFn: () => api.get<Member[]>(`/billing/organizations/${orgQuery.data!.id}/members`),
    enabled: !!orgQuery.data,
  });

  const checkoutMutation = useMutation({
    mutationFn: (plan: string) =>
      api.post("/billing/checkout", {
        plan,
        success_url: typeof window !== "undefined" ? window.location.href : "",
      }),
    onMutate: () => setCheckoutError(null),
    onError: (err: unknown) => {
      setCheckoutError(err instanceof ApiError ? err.message : "Checkout failed");
    },
  });

  const inviteMutation = useMutation({
    mutationFn: () =>
      api.post(`/billing/organizations/${orgQuery.data!.id}/members`, {
        user_id: inviteUserId,
        role: "MEMBER",
      }),
    onSuccess: () => {
      setInviteUserId("");
      queryClient.invalidateQueries({ queryKey: ["billing", "members"] });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) =>
      api.delete(`/billing/organizations/${orgQuery.data!.id}/members/${userId}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["billing", "members"] }),
  });

  if (orgQuery.isLoading) {
    return (
      <AppShell>
        <PageHeader title="Billing" description="Plan, usage limits, and team access." />
        <LoadingState />
      </AppShell>
    );
  }

  if (orgQuery.isError || !orgQuery.data) {
    return (
      <AppShell>
        <PageHeader title="Billing" description="Plan, usage limits, and team access." />
        <ErrorState message="Could not load organization." />
      </AppShell>
    );
  }

  const org = orgQuery.data;
  const limits = plansQuery.data?.[org.plan];

  return (
    <AppShell>
      <PageHeader title="Billing" description="Plan, usage limits, and team access." />

      <div className="grid gap-6 md:grid-cols-2">
        <section className="card p-5">
          <h2 className="mb-3 text-lg font-semibold">{org.name}</h2>
          <div className="mb-2 flex items-center gap-2 text-sm">
            <span className="muted">Plan</span>
            <Badge tone={org.plan === "FREE" ? "default" : "success"}>{org.plan}</Badge>
          </div>
          {subscriptionQuery.data && (
            <div className="mb-2 flex items-center gap-2 text-sm">
              <span className="muted">Subscription</span>
              <Badge tone={statusTone(subscriptionQuery.data.status)}>
                {subscriptionQuery.data.status}
              </Badge>
              <span className="muted">via {subscriptionQuery.data.payment_provider}</span>
            </div>
          )}
          {limits && (
            <ul className="mt-4 space-y-1 text-sm">
              <li>Channels: {formatLimit(limits.max_channels)}</li>
              <li>Team members: {formatLimit(limits.max_team_members)}</li>
              <li>Competitors tracked: {formatLimit(limits.max_competitors_tracked)}</li>
              <li>AI generations / day: {formatLimit(limits.ai_generations_per_day)}</li>
              <li>White-label: {limits.white_label ? "Included" : "Not available"}</li>
            </ul>
          )}

          <div className="mt-5 flex flex-wrap gap-2">
            {["PRO", "AGENCY", "ENTERPRISE"].map((plan) => (
              <Button
                key={plan}
                variant="secondary"
                disabled={org.plan === plan || checkoutMutation.isPending}
                onClick={() => checkoutMutation.mutate(plan)}
              >
                Upgrade to {plan}
              </Button>
            ))}
          </div>
          {checkoutError && (
            <p className="mt-3 text-sm text-amber-600 dark:text-amber-400">{checkoutError}</p>
          )}
        </section>

        <section className="card p-5">
          <h2 className="mb-3 text-lg font-semibold">Team members</h2>
          {membersQuery.isLoading && <LoadingState />}
          {membersQuery.data && (
            <ul className="space-y-2 text-sm">
              {membersQuery.data.map((member) => (
                <li key={member.id} className="flex items-center justify-between gap-2">
                  <span>
                    {member.user_id} <Badge>{member.role}</Badge>
                  </span>
                  {member.role !== "OWNER" && (
                    <Button
                      variant="danger"
                      onClick={() => removeMutation.mutate(member.user_id)}
                      disabled={removeMutation.isPending}
                    >
                      Remove
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}

          <form
            className="mt-4 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (inviteUserId.trim()) inviteMutation.mutate();
            }}
          >
            <Input
              placeholder="User ID to invite"
              value={inviteUserId}
              onChange={(e) => setInviteUserId(e.target.value)}
            />
            <Button type="submit" disabled={inviteMutation.isPending}>
              Invite
            </Button>
          </form>
          {inviteMutation.isError && (
            <p className="mt-2 text-sm text-red-600 dark:text-red-400">
              {inviteMutation.error instanceof ApiError
                ? inviteMutation.error.message
                : "Could not invite member"}
            </p>
          )}
        </section>
      </div>
    </AppShell>
  );
}
