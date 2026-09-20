"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Input, Button } from "@/components/ui";
import { api } from "@/lib/api";

export interface PexelsPhoto {
  id: number;
  photographer: string | null;
  thumbnail_url: string | null;
  download_url: string | null;
}

/** Shared free-stock-photo picker (Pexels) -- search box + thumbnail
 * grid, hands the caller a chosen photo's direct, permanent CDN URL.
 * Used by the video-generation page (image-to-video source image) and
 * the thumbnails page (thumbnail source image). */
export function PexelsPhotoPicker({ onSelect }: { onSelect: (url: string) => void }) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");

  const searchQuery = useQuery({
    queryKey: ["pexels-photos", submittedQuery],
    queryFn: () => api.get<PexelsPhoto[]>(`/media/pexels/photos?query=${encodeURIComponent(submittedQuery)}`),
    enabled: !!submittedQuery,
  });

  return (
    <div className="mt-2 rounded-lg border p-3" style={{ borderColor: "rgb(var(--border))" }}>
      <div className="flex gap-2">
        <Input
          placeholder="Search free stock photos (Pexels)…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && setSubmittedQuery(query)}
        />
        <Button variant="secondary" onClick={() => setSubmittedQuery(query)} disabled={!query}>
          Search
        </Button>
      </div>
      {searchQuery.isFetching && <p className="mt-1 text-xs muted">Searching…</p>}
      {searchQuery.isError && <p className="mt-1 text-xs text-red-600 dark:text-red-400">Pexels search failed.</p>}
      {searchQuery.data && searchQuery.data.length > 0 && (
        <div className="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-6">
          {searchQuery.data.map((photo) => (
            <button
              key={photo.id}
              type="button"
              onClick={() => photo.download_url && onSelect(photo.download_url)}
              className="overflow-hidden rounded-lg border hover:ring-2 hover:ring-brand-500"
              style={{ borderColor: "rgb(var(--border))" }}
              title={photo.photographer ?? "Pexels photo"}
            >
              {photo.thumbnail_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={photo.thumbnail_url} alt={photo.photographer ?? "Pexels photo"} className="h-16 w-full object-cover" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
