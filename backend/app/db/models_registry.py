"""Imports every ORM model so Base.metadata is fully populated before Alembic
autogenerate or the test suite's create_all() run. Import this module (not
individual model modules) whenever you need the complete metadata graph.
"""
from app.ai.models import AIGenerationCache  # noqa: F401
from app.db.base import Base  # noqa: F401
from app.jobs.models import Job, KillSwitch  # noqa: F401
from app.modules.analytics.models import (  # noqa: F401
    AnalyticsSnapshot,
    GrowthAction,
    GrowthScore,
    SubscriberGrowthMetric,
)
from app.modules.audit.models import AuditLog  # noqa: F401
from app.modules.channels.models import Channel  # noqa: F401
from app.modules.competitors.models import Competitor, CompetitorVideo  # noqa: F401
from app.modules.content.models import ContentEvent, ContentItem  # noqa: F401
from app.modules.distribution.models import DistributionAsset, DistributionCampaign  # noqa: F401
from app.modules.experiments.models import Experiment, ExperimentVariant  # noqa: F401
from app.modules.hooks.models import Hook  # noqa: F401
from app.modules.media.models import MediaAsset  # noqa: F401
from app.modules.notifications.models import Notification  # noqa: F401
from app.modules.publishing.models import (  # noqa: F401
    PublishingAttempt,
    PublishingRule,
    PublishingRun,
)
from app.modules.recommendations.models import Recommendation  # noqa: F401
from app.modules.research.models import ResearchProject, ResearchSource  # noqa: F401
from app.modules.retention.models import RetentionMetric  # noqa: F401
from app.modules.scripts.models import Script, ScriptVersion  # noqa: F401
from app.modules.seo.models import SeoRecord  # noqa: F401
from app.modules.shorts.models import (  # noqa: F401
    ShortCandidate,
    Transcript,
    TranscriptSegment,
    VideoProcessingJob,
)
from app.modules.thumbnails.models import ThumbnailBrief  # noqa: F401
from app.modules.titles.models import Title  # noqa: F401
from app.modules.topics.models import Opportunity, Topic  # noqa: F401
from app.modules.trends.models import Trend  # noqa: F401
from app.modules.users.models import User, UserSession  # noqa: F401
from app.modules.videos.models import Video, VideoMetricSnapshot  # noqa: F401

__all__ = ["Base"]
