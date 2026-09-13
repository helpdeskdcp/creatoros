export type DataQuality = "REAL" | "ESTIMATED" | "INSUFFICIENT_DATA";

export interface Metric<T = number | Record<string, number>> {
  value: T | null;
  quality: DataQuality;
  sample_size: number;
  reason: string | null;
  source: string;
  computed_at: string;
}

export type UserRole = "OWNER" | "ADMIN" | "EDITOR" | "ANALYST" | "VIEWER";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export type SyncStatus = "NEVER_SYNCED" | "PENDING" | "SYNCING" | "SUCCEEDED" | "FAILED";

export interface Channel {
  id: string;
  youtube_channel_id: string;
  title: string;
  description: string | null;
  thumbnail_url: string | null;
  country: string | null;
  subscriber_count: number | null;
  view_count: number | null;
  video_count: number | null;
  sync_status: SyncStatus;
  last_synced_at: string | null;
  last_sync_error: string | null;
}

export interface VideoOut {
  id: string;
  channel_id: string;
  youtube_video_id: string;
  title: string;
  thumbnail_url: string | null;
  published_at: string | null;
  duration_seconds: number | null;
  format: "SHORT" | "LONG_FORM" | null;
  view_count: number | null;
  like_count: number | null;
  comment_count: number | null;
}

export interface FormatStats {
  video_count: number;
  total_views: number;
  avg_views: number | null;
  avg_engagement_rate: number | null;
  sample_size_for_averages: number;
}

export interface ShortsVsLongForm {
  shorts: FormatStats;
  long_form: FormatStats;
}

export interface ChannelIntelligence {
  total_views: Metric;
  subscriber_count: Metric;
  average_views: Metric;
  median_views: Metric;
  views_velocity_7d: Metric;
  upload_frequency_per_week: Metric;
  engagement_rate: Metric;
  shorts_vs_long_form: Metric<ShortsVsLongForm>;
  top_videos: VideoOut[];
  weak_videos: VideoOut[];
}

export interface GrowthBottleneck {
  bottleneck: string;
  evidence: string;
  affected_videos: string[];
  affected_metrics: string[];
  recommended_action: string;
  confidence: string;
  sample_size: number;
}

export interface GrowthAction {
  id: string;
  channel_id: string | null;
  run_date: string;
  priority: number;
  action_type: string;
  title: string;
  reason: string;
  evidence: string | null;
  expected_objective: string | null;
  confidence: string;
  requires_approval: boolean;
  execution_status: string;
}

export interface GrowthDiagnosisOut {
  channel_id: string;
  computed_at: string;
  bottlenecks: GrowthBottleneck[];
  note: string | null;
}

export interface GrowthScorecardOut {
  channel_id: string;
  computed_at: string;
  content_score: Metric;
  discovery_score: Metric;
  ctr_score: Metric;
  retention_score: Metric;
  subscriber_conversion_score: Metric;
  returning_viewers_score: Metric;
  distribution_score: Metric;
  consistency_score: Metric;
  explanation: string;
}

export interface SubscriberGrowthOut {
  channel_id: string;
  dimension: string;
  subscriber_growth_rate: Metric;
  subscriber_conversion_rate: Metric;
  subscribers_per_1000_views: Metric;
  returning_viewer_rate: Metric;
}

export interface Recommendation {
  id: string;
  rank: number;
  topic: string;
  format: string;
  target_audience: string | null;
  content_angle: string | null;
  hook: string | null;
  title_candidates: string[];
  thumbnail_concept: string | null;
  reason: string;
  supporting_evidence: string | null;
  opportunity_score: number | null;
  viral_potential_score: number | null;
  discovery_score: number | null;
  subscriber_potential_score: number | null;
  retention_potential_score: number | null;
  audience_fit_score: number | null;
  confidence: string;
  sample_size: number;
}

export interface Trend {
  id: string;
  keyword: string;
  source: string;
  trend_score: number | null;
  growth_score: number | null;
  competition_score: number | null;
  opportunity_score: number | null;
  sample_size: number;
  explanation: string | null;
  detected_at: string;
}

export interface ContentItem {
  id: string;
  title: string;
  status: string;
  topic_id: string | null;
  video_id: string | null;
  due_at: string | null;
  scheduled_publish_at: string | null;
  timezone: string;
  is_short: boolean;
  notes: string | null;
}

export interface Competitor {
  id: string;
  youtube_channel_id: string;
  title: string;
  thumbnail_url: string | null;
  subscriber_count: number | null;
  view_count: number | null;
  video_count: number | null;
  last_synced_at: string | null;
  notes: string | null;
}
