"""Creator-specific learning loop: turns concluded experiments (real
measured winners, never an LLM's self-reported guess) into persistent
per-creator signals that future AI generation can actually read. Every
signal here traces back to a real experiment outcome -- win/loss counts
on a real content pattern (a keyword, a format), not a vibe.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import extract_keywords
from app.modules.experiments.models import CreatorLearningSignal, Experiment

_MIN_TOTAL_FOR_CONTEXT = 2  # don't surface a signal from a single coin-flip experiment


async def _upsert_signal(db: AsyncSession, owner_user_id: uuid.UUID, signal_type: str, signal_key: str, *, won: bool) -> None:
    signal = await db.scalar(
        select(CreatorLearningSignal).where(
            CreatorLearningSignal.owner_user_id == owner_user_id,
            CreatorLearningSignal.signal_type == signal_type,
            CreatorLearningSignal.signal_key == signal_key,
        )
    )
    if not signal:
        signal = CreatorLearningSignal(
            owner_user_id=owner_user_id, signal_type=signal_type, signal_key=signal_key, wins=0, losses=0,
        )
        db.add(signal)
        await db.flush()
    if won:
        signal.wins += 1
    else:
        signal.losses += 1


async def record_experiment_outcome(db: AsyncSession, experiment: Experiment) -> None:
    """Called once an experiment concludes with a real winner (see
    service._maybe_conclude). Extracts keyword-level signals from the
    winning variant's content vs every losing variant's content, plus a
    format-level signal for the experiment_type itself."""
    if not experiment.winning_variant_id:
        return

    winner = next((v for v in experiment.variants if v.id == experiment.winning_variant_id), None)
    losers = [v for v in experiment.variants if v.id != experiment.winning_variant_id]
    if not winner:
        return

    signal_type = f"{experiment.experiment_type}_keyword"
    winner_keywords = extract_keywords(winner.content)
    loser_keywords: set[str] = set()
    for loser in losers:
        loser_keywords |= extract_keywords(loser.content)

    # A keyword unique to the winner is a real positive signal; a
    # keyword present in BOTH winner and losers didn't differentiate the
    # outcome and is skipped rather than double-counted as a win.
    for keyword in winner_keywords - loser_keywords:
        await _upsert_signal(db, experiment.owner_user_id, signal_type, keyword, won=True)
    for keyword in loser_keywords - winner_keywords:
        await _upsert_signal(db, experiment.owner_user_id, signal_type, keyword, won=False)

    await _upsert_signal(
        db, experiment.owner_user_id, "experiment_type", experiment.experiment_type, won=True
    )
    await db.commit()


async def get_learning_context_text(db: AsyncSession, owner_user_id: uuid.UUID, signal_type: str | None = None) -> str | None:
    """Summarizes the creator's strongest learned signals into a short
    text block for injection into an AI-generation prompt. Returns None
    when there isn't enough real experiment history yet -- an empty
    learning profile must never be padded with invented advice."""
    query = select(CreatorLearningSignal).where(CreatorLearningSignal.owner_user_id == owner_user_id)
    if signal_type:
        query = query.where(CreatorLearningSignal.signal_type == signal_type)
    signals = list(await db.scalars(query))

    scored = [
        (s, s.wins / (s.wins + s.losses))
        for s in signals
        if (s.wins + s.losses) >= _MIN_TOTAL_FOR_CONTEXT
    ]
    if not scored:
        return None

    scored.sort(key=lambda pair: pair[1], reverse=True)
    top = scored[:5]
    lines = [
        f"- \"{s.signal_key}\" won {s.wins}/{s.wins + s.losses} real A/B experiments"
        for s, _ in top
        if s.wins >= s.losses  # only surface things that actually helped, not underperformers
    ]
    if not lines:
        return None
    return (
        "This creator's own real experiment history (not a guess) shows:\n" + "\n".join(lines)
    )
