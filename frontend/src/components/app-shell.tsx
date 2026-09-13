"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect } from "react";
import { useAuth } from "@/lib/auth-context";
import { ThemeToggle } from "./theme-toggle";

const NAV_SECTIONS: { label: string; items: { href: string; label: string }[] }[] = [
  {
    label: "Overview",
    items: [
      { href: "/dashboard", label: "Dashboard" },
      { href: "/growth", label: "Growth" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { href: "/channels", label: "Channels" },
      { href: "/competitors", label: "Competitors" },
      { href: "/trends", label: "Trends" },
      { href: "/opportunities", label: "Opportunities" },
      { href: "/research", label: "Research" },
    ],
  },
  {
    label: "Content",
    items: [
      { href: "/content", label: "Workspace" },
      { href: "/calendar", label: "Calendar" },
      { href: "/hooks", label: "Hooks" },
      { href: "/titles", label: "Titles" },
      { href: "/scripts", label: "Scripts" },
      { href: "/thumbnails", label: "Thumbnails" },
      { href: "/seo", label: "SEO" },
      { href: "/shorts", label: "Shorts Factory" },
    ],
  },
  {
    label: "Performance",
    items: [
      { href: "/analytics", label: "Analytics" },
      { href: "/retention", label: "Retention" },
      { href: "/recommendations", label: "Recommendations" },
      { href: "/experiments", label: "Experiments" },
    ],
  },
  {
    label: "Distribution",
    items: [
      { href: "/publishing", label: "Publishing" },
      { href: "/distribution", label: "Distribution" },
    ],
  },
  {
    label: "System",
    items: [
      { href: "/settings", label: "Control Center" },
      { href: "/audit", label: "Audit Log" },
    ],
  },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.replace("/login");
    }
  }, [isLoading, user, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="muted">Loading CreatorOS…</p>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="flex min-h-screen">
      <aside
        className="hidden w-64 shrink-0 flex-col border-r p-4 sm:flex"
        style={{ borderColor: "rgb(var(--border))" }}
      >
        <div className="mb-6 px-2 text-lg font-bold">CreatorOS</div>
        <nav className="flex-1 space-y-5 overflow-y-auto">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <div className="mb-1 px-2 text-xs font-semibold uppercase tracking-wide muted">
                {section.label}
              </div>
              <div className="space-y-0.5">
                {section.items.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`block rounded-lg px-2 py-1.5 text-sm ${
                      pathname?.startsWith(item.href)
                        ? "bg-brand-500 text-white"
                        : "hover:bg-black/5 dark:hover:bg-white/10"
                    }`}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="mt-4 space-y-2 border-t pt-4" style={{ borderColor: "rgb(var(--border))" }}>
          <div className="px-2 text-sm">
            <div className="font-medium">{user.email}</div>
            <div className="muted">{user.role}</div>
          </div>
          <button
            onClick={() => logout().then(() => router.replace("/login"))}
            className="w-full rounded-lg border px-3 py-1.5 text-left text-sm hover:bg-black/5 dark:hover:bg-white/10"
            style={{ borderColor: "rgb(var(--border))" }}
          >
            Log out
          </button>
        </div>
      </aside>
      <div className="flex flex-1 flex-col">
        <header
          className="flex items-center justify-between border-b p-4 sm:hidden"
          style={{ borderColor: "rgb(var(--border))" }}
        >
          <span className="text-lg font-bold">CreatorOS</span>
          <ThemeToggle />
        </header>
        <div className="hidden justify-end p-4 sm:flex">
          <ThemeToggle />
        </div>
        <main className="flex-1 px-4 pb-10 sm:px-8">{children}</main>
      </div>
    </div>
  );
}
