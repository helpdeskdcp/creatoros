"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { Button } from "./ui";

export function GoogleSignInButton() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleClick() {
    setError(null);
    setLoading(true);
    try {
      const { authorize_url } = await api.get<{ authorize_url: string }>("/auth/google/authorize");
      window.location.href = authorize_url;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start Google sign-in");
      setLoading(false);
    }
  }

  return (
    <div>
      <Button type="button" variant="secondary" className="w-full" onClick={handleClick} disabled={loading}>
        {loading ? "Redirecting to Google…" : "Continue with Google"}
      </Button>
      {error && <p className="mt-2 text-sm text-red-600 dark:text-red-400">{error}</p>}
    </div>
  );
}
