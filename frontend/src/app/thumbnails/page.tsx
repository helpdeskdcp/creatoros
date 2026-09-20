"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { PageHeader, LoadingState, EmptyState, Button, Input } from "@/components/ui";
import { PexelsPhotoPicker } from "@/components/pexels-photo-picker";
import { api } from "@/lib/api";

interface ThumbnailBrief {
  id: string;
  subject: string;
  emotion: string | null;
  text_overlay: string | null;
  prompt: string | null;
  image_path: string | null;
  image_provider: string | null;
}

function BriefCard({ brief }: { brief: ThumbnailBrief }) {
  const queryClient = useQueryClient();
  const [pickerOpen, setPickerOpen] = useState(false);

  const attachImageMutation = useMutation({
    mutationFn: (imageUrl: string) =>
      api.post<ThumbnailBrief>(`/thumbnails/${brief.id}/image`, { image_url: imageUrl, image_provider: "pexels" }),
    onSuccess: (data) => {
      queryClient.setQueryData(["thumbnail-briefs"], (prev: ThumbnailBrief[] | undefined) =>
        prev?.map((b) => (b.id === data.id ? data : b))
      );
      setPickerOpen(false);
    },
  });

  return (
    <div className="card p-4">
      <div className="font-medium">{brief.subject}</div>
      <div className="mt-1 text-sm muted">Emotion: {brief.emotion} &middot; Overlay: &ldquo;{brief.text_overlay}&rdquo;</div>
      {brief.prompt && <p className="mt-2 text-xs muted">Image prompt: {brief.prompt}</p>}

      {brief.image_path ? (
        <div className="mt-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={brief.image_path} alt={brief.subject} className="h-32 w-auto rounded-lg object-cover" />
          <p className="mt-1 text-xs muted">Source: {brief.image_provider}</p>
          <Button variant="secondary" className="mt-2" onClick={() => setPickerOpen(true)}>
            Change image
          </Button>
        </div>
      ) : (
        <Button variant="secondary" className="mt-3" onClick={() => setPickerOpen((v) => !v)}>
          Choose source image
        </Button>
      )}

      {pickerOpen && (
        <PexelsPhotoPicker onSelect={(url) => attachImageMutation.mutate(url)} />
      )}
    </div>
  );
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
        description="Plans a thumbnail — subject, emotion, overlay text, and an image-generation prompt — then lets you attach a free stock source image from Pexels."
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
          <BriefCard key={b.id} brief={b} />
        ))}
      </div>
    </AppShell>
  );
}
