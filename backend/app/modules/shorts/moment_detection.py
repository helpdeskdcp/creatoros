"""Candidate-moment scoring: deterministic, explainable heuristics over
real transcript text -- never a random 30-second window, and never an
LLM's self-reported "this will go viral" guess (same discipline the
trend/opportunity engines already apply: a number here is either
computed from real signal or it doesn't exist).

Every score component is independently inspectable via ScoreBreakdown,
so a creator (or an engineer debugging a bad pick) can see WHY a window
ranked where it did, not just that it did -- this is the explicit
'explainable scores' requirement, not an incidental nice-to-have.
"""
import re
from dataclasses import dataclass, field

_HOOK_PATTERNS = [
    r"\bhere'?s (how|why|what)\b", r"\bthe secret\b", r"\byou won'?t believe\b",
    r"\bdid you know\b", r"\bnobody (tells|talks about)\b", r"\bthe truth (about|is)\b",
    r"\bstop doing\b", r"\bwhy (you|everyone)\b", r"\bthis is why\b", r"\bmistake\b",
    r"\bnever\b", r"\balways\b", r"^\s*\d+\s+(ways|reasons|things|tips|steps)\b",
]
_EMOTIONAL_WORDS = {
    "amazing", "incredible", "shocking", "terrifying", "insane", "crazy", "unbelievable",
    "hate", "love", "furious", "devastated", "thrilled", "horrifying", "outrageous",
    "brilliant", "disaster", "genius", "nightmare", "obsessed", "heartbreaking",
}
_FILLER_WORDS = {
    "um", "uh", "like", "you", "know", "so", "just", "actually", "basically", "kind",
    "sort", "really", "very", "the", "a", "an", "and", "or", "but", "is", "was", "to", "of",
}


@dataclass
class TranscriptSegmentLike:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass
class ScoreBreakdown:
    hook_strength: float
    sentence_completeness: float
    emotional_intensity: float
    information_density: float
    question_answer_structure: float
    novelty: float
    keyword_relevance: float
    duration_fit: float
    weighted_total: float

    def as_dict(self) -> dict:
        return {
            "hook_strength": round(self.hook_strength, 1),
            "sentence_completeness": round(self.sentence_completeness, 1),
            "emotional_intensity": round(self.emotional_intensity, 1),
            "information_density": round(self.information_density, 1),
            "question_answer_structure": round(self.question_answer_structure, 1),
            "novelty": round(self.novelty, 1),
            "keyword_relevance": round(self.keyword_relevance, 1),
            "duration_fit": round(self.duration_fit, 1),
            "weighted_total": round(self.weighted_total, 1),
        }


@dataclass
class CandidateWindow:
    start_seconds: float
    end_seconds: float
    text: str
    segment_indices: list[int] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_seconds - self.start_seconds


_WEIGHTS = {
    "hook_strength": 0.20,
    "sentence_completeness": 0.15,
    "emotional_intensity": 0.10,
    "information_density": 0.15,
    "question_answer_structure": 0.10,
    "novelty": 0.15,
    "keyword_relevance": 0.10,
    "duration_fit": 0.05,
}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def _score_hook_strength(text: str) -> float:
    head = text[:120].lower()
    hits = sum(1 for pattern in _HOOK_PATTERNS if re.search(pattern, head))
    return min(hits * 35.0, 100.0)


def _score_sentence_completeness(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    starts_clean = stripped[0].isupper() or stripped[0].isdigit()
    ends_clean = stripped[-1] in ".!?"
    return (50.0 if starts_clean else 0.0) + (50.0 if ends_clean else 0.0)


def _score_emotional_intensity(text: str) -> float:
    words = _words(text)
    if not words:
        return 0.0
    emotional_hits = sum(1 for w in words if w in _EMOTIONAL_WORDS)
    exclamations = text.count("!")
    density = emotional_hits / max(len(words), 1)
    return min(density * 400 + exclamations * 10, 100.0)


def _score_information_density(text: str) -> float:
    words = _words(text)
    if not words:
        return 0.0
    content_words = [w for w in words if w not in _FILLER_WORDS]
    content_ratio = len(content_words) / len(words)
    has_numbers = bool(re.search(r"\d", text))
    unique_ratio = len(set(content_words)) / max(len(content_words), 1)
    return min(content_ratio * 60 + unique_ratio * 30 + (10 if has_numbers else 0), 100.0)


def _score_question_answer(text: str) -> float:
    if "?" not in text:
        return 0.0
    q_index = text.index("?")
    remainder = text[q_index + 1 :].strip()
    # A question with something substantive after it (an attempted
    # answer) scores higher than a question left hanging.
    return 100.0 if len(remainder) > 20 else 55.0


def _score_novelty(window_text: str, full_transcript_text: str) -> float:
    window_words = set(_words(window_text)) - _FILLER_WORDS
    if not window_words:
        return 0.0
    full_words = _words(full_transcript_text)
    if not full_words:
        return 50.0
    from collections import Counter

    freq = Counter(full_words)
    total = len(full_words)
    # Words in this window that are rare across the WHOLE transcript
    # signal a distinct, non-repeated moment rather than a recap of
    # something said (and scoreable) elsewhere too.
    rarity_scores = [1 - (freq[w] / total) for w in window_words if w in freq]
    if not rarity_scores:
        return 50.0
    return min((sum(rarity_scores) / len(rarity_scores)) * 100, 100.0)


def _score_keyword_relevance(text: str, target_keywords: list[str] | None) -> float:
    if not target_keywords:
        return 50.0  # neutral -- no target given, doesn't penalize or reward
    text_lower = text.lower()
    hits = sum(1 for kw in target_keywords if kw.lower() in text_lower)
    return min(hits * 40.0, 100.0)


def _score_duration_fit(duration: float, min_duration: float, max_duration: float) -> float:
    target_center = (min_duration + max_duration) / 2
    target_half_range = (max_duration - min_duration) / 2
    if target_half_range <= 0:
        return 100.0
    distance = abs(duration - target_center) / target_half_range
    return max(0.0, 100.0 - distance * 60.0)


def score_candidate(
    window: CandidateWindow,
    full_transcript_text: str,
    *,
    target_keywords: list[str] | None = None,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
) -> ScoreBreakdown:
    hook = _score_hook_strength(window.text)
    completeness = _score_sentence_completeness(window.text)
    emotional = _score_emotional_intensity(window.text)
    density = _score_information_density(window.text)
    qa = _score_question_answer(window.text)
    novelty = _score_novelty(window.text, full_transcript_text)
    keyword = _score_keyword_relevance(window.text, target_keywords)
    duration_fit = _score_duration_fit(window.duration, min_duration, max_duration)

    weighted_total = (
        hook * _WEIGHTS["hook_strength"]
        + completeness * _WEIGHTS["sentence_completeness"]
        + emotional * _WEIGHTS["emotional_intensity"]
        + density * _WEIGHTS["information_density"]
        + qa * _WEIGHTS["question_answer_structure"]
        + novelty * _WEIGHTS["novelty"]
        + keyword * _WEIGHTS["keyword_relevance"]
        + duration_fit * _WEIGHTS["duration_fit"]
    )

    return ScoreBreakdown(
        hook_strength=hook, sentence_completeness=completeness, emotional_intensity=emotional,
        information_density=density, question_answer_structure=qa, novelty=novelty,
        keyword_relevance=keyword, duration_fit=duration_fit, weighted_total=weighted_total,
    )


def generate_candidate_windows(
    segments: list[TranscriptSegmentLike], *, min_duration: float = 15.0, max_duration: float = 60.0
) -> list[CandidateWindow]:
    """Every contiguous run of segments starting at each segment index
    whose total duration falls in [min_duration, max_duration] -- not
    fixed-size chunks, so a window can end exactly where a natural
    sentence/thought does rather than at an arbitrary time boundary."""
    windows: list[CandidateWindow] = []
    n = len(segments)
    for i in range(n):
        acc_text: list[str] = []
        for j in range(i, n):
            acc_text.append(segments[j].text)
            duration = segments[j].end_seconds - segments[i].start_seconds
            if duration > max_duration:
                break
            if duration >= min_duration:
                windows.append(
                    CandidateWindow(
                        start_seconds=segments[i].start_seconds,
                        end_seconds=segments[j].end_seconds,
                        text=" ".join(acc_text).strip(),
                        segment_indices=list(range(i, j + 1)),
                    )
                )
    return windows


def _overlaps(a: CandidateWindow, b: CandidateWindow) -> bool:
    return a.start_seconds < b.end_seconds and b.start_seconds < a.end_seconds


def rank_candidates(
    segments: list[TranscriptSegmentLike],
    full_transcript_text: str,
    *,
    target_keywords: list[str] | None = None,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
    top_k: int = 5,
) -> list[tuple[CandidateWindow, ScoreBreakdown]]:
    """Returns up to top_k NON-OVERLAPPING candidates, highest score
    first -- greedy selection so the result is genuinely distinct clip
    opportunities, not five slight variations of the same moment."""
    windows = generate_candidate_windows(segments, min_duration=min_duration, max_duration=max_duration)
    scored = [
        (w, score_candidate(w, full_transcript_text, target_keywords=target_keywords,
                             min_duration=min_duration, max_duration=max_duration))
        for w in windows
    ]
    scored.sort(key=lambda pair: pair[1].weighted_total, reverse=True)

    selected: list[tuple[CandidateWindow, ScoreBreakdown]] = []
    for window, breakdown in scored:
        if any(_overlaps(window, chosen) for chosen, _ in selected):
            continue
        selected.append((window, breakdown))
        if len(selected) >= top_k:
            break
    return selected
