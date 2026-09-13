"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

function GoogleSignInCompleteInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { completeGoogleSignIn } = useAuth();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const accessToken = searchParams.get("access_token");
    if (!accessToken) {
      setError("No access token was returned by Google sign-in.");
      return;
    }
    completeGoogleSignIn(accessToken)
      .then(() => router.replace("/dashboard"))
      .catch(() => setError("Could not complete Google sign-in."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="card w-full max-w-sm p-6 text-center">
      {error ? (
        <>
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
          <a href="/login" className="mt-4 inline-block text-sm text-brand-500 hover:underline">
            Back to sign in
          </a>
        </>
      ) : (
        <p className="muted text-sm">Finishing sign-in with Google…</p>
      )}
    </div>
  );
}

export default function GoogleSignInCompletePage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Suspense fallback={<p className="muted text-sm">Loading…</p>}>
        <GoogleSignInCompleteInner />
      </Suspense>
    </div>
  );
}
