"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Button, Input } from "@/components/ui";
import { GoogleSignInButton } from "@/components/google-signin-button";

function GoogleErrorBanner() {
  const searchParams = useSearchParams();
  const googleError = searchParams.get("google_error");
  if (!googleError) return null;
  return <p className="mt-3 text-sm text-red-600 dark:text-red-400">Google sign-in failed: {googleError}</p>;
}

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await login(email, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="card w-full max-w-sm p-6">
        <h1 className="text-xl font-bold">Sign in to CreatorOS</h1>
        <Suspense fallback={null}>
          <GoogleErrorBanner />
        </Suspense>
        <div className="mt-6">
          <GoogleSignInButton />
        </div>
        <div className="my-4 flex items-center gap-2 text-xs muted">
          <div className="h-px flex-1" style={{ backgroundColor: "rgb(var(--border))" }} />
          or
          <div className="h-px flex-1" style={{ backgroundColor: "rgb(var(--border))" }} />
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="mb-1 block text-sm font-medium">Email</label>
            <Input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium">Password</label>
            <Input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </div>
          {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm muted">
          No account?{" "}
          <Link href="/register" className="font-medium text-brand-500 hover:underline">
            Register
          </Link>
        </p>
        <p className="mt-4 text-center text-xs muted">
          <Link href="/privacy" className="hover:underline">
            Privacy Policy
          </Link>
          {" · "}
          <Link href="/terms" className="hover:underline">
            Terms of Service
          </Link>
        </p>
      </div>
    </div>
  );
}
