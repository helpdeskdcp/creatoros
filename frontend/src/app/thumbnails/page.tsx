"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input } from "@/components/ui";
import { api } from "@/lib/api";

interface ThumbnailBrief {
  id: string;
  subject: string;
  emotion: string | null;
  text_overlay: string | null;
  prompt: string | null;
}

export default function ThumbnailsPage() {
  const queryClient = useQueryClient();
  const [videoTitle, setVideoTitle] = useState("");

  const query = useQuery({
    queryKey: ["thumbnail-briefs"],
    queryFn: () => api.get<ThumbnailBrief[]>("/thumbnails"),
  });

  const generateMutation = useMutation({
    mutationFn: () => api.post<ThumbnailBrief>("/thumbnails/generate", { video_title: videoTitle }),
    onSuccess: (data) => {
      queryClient.setQueryData(["thumbnail-briefs"], (prev: ThumbnailBrief[] | undefined) => [
        data,
        ...(prev ?? []),
      ]);
      setVideoTitle("");
    },
  });

  return (
    <AppShell>
      <PageHeader
        title="Thumbnail Intelligence"
        description="Plans a thumbnail — subject, emotion, overlay text, and an image-generation prompt. Does not render an image itself."
      />

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (videoTitle.trim()) generateMutation.mutate();
        }}
        className="mb-6 flex gap-2"
      >
        <Input
          placeholder="Video title"
          value={videoTitle}
          onChange={(e) => setVideoTitle(e.target.value)}
        />
        <Button type="submit" disabled={generateMutation.isPending}>
          {generateMutation.isPending ? "Planning…" : "Generate brief"}
        </Button>
      </form>

      {query.isLoading && <LoadingState />}
      {query.data?.length === 0 && <EmptyState>No thumbnail briefs yet.</EmptyState>}

      <div className="space-y-3">
        {query.data?.map((b) => (
          <div key={b.id} className="card p-4">
            <div className="font-medium">{b.subject}</div>
            <div className="mt-1 text-sm muted">Emotion: {b.emotion} · Overlay: &ldquo;{b.text_overlay}&rdquo;</div>
            {b.prompt && <p className="mt-2 text-xs muted">Image prompt: {b.prompt}</p>}
          </div>
        ))}
      </div>
    </AppShell>
  );
}
