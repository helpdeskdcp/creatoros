"""Moment-detection scoring: deterministic heuristics over real
transcript text, never a random window and never an LLM self-report.
Every test constructs synthetic transcript segments directly -- this
stage needs no video/audio/ML fixtures at all, matching the module's own
design (pure text-in, scores-out)."""
from app.modules.shorts.moment_detection import (
    TranscriptSegmentLike,
    generate_candidate_windows,
    rank_candidates,
    score_candidate,
)


def _seg(start, end, text):
    return TranscriptSegmentLike(start_seconds=start, end_seconds=end, text=text)


def test_generate_candidate_windows_respects_duration_bounds():
    segments = [_seg(i * 5, i * 5 + 5, f"segment {i}") for i in range(10)]  # 50s total, 5s each

    windows = generate_candidate_windows(segments, min_duration=15, max_duration=25)

    assert windows  # at least one window generated
    assert all(15 <= w.duration <= 25 for w in windows)


def test_generate_candidate_windows_never_exceeds_max_duration():
    segments = [_seg(i * 10, i * 10 + 10, f"segment {i}") for i in range(20)]

    windows = generate_candidate_windows(segments, min_duration=15, max_duration=30)

    assert all(w.duration <= 30 for w in windows)


def test_hook_pattern_scores_higher_than_filler_text():
    hook_window_text = "Here's how you can grow your channel fast this year."
    filler_window_text = "So um yeah I was just kind of thinking about stuff you know."

    hook_score = score_candidate(_window(hook_window_text), "full transcript")
    filler_score = score_candidate(_window(filler_window_text), "full transcript")

    assert hook_score.hook_strength > filler_score.hook_strength
    assert hook_score.weighted_total > filler_score.weighted_total


def _window(text, start=0.0, end=20.0):
    from app.modules.shorts.moment_detection import CandidateWindow

    return CandidateWindow(start_seconds=start, end_seconds=end, text=text, segment_indices=[0])


def test_sentence_completeness_rewards_clean_boundaries():
    complete = score_candidate(_window("This is a complete sentence."), "full transcript")
    incomplete = score_candidate(_window("this trails off without and then"), "full transcript")

    assert complete.sentence_completeness > incomplete.sentence_completeness


def test_emotional_words_increase_emotional_intensity_score():
    emotional = score_candidate(_window("This is absolutely amazing and incredible!"), "t")
    neutral = score_candidate(_window("This is a normal statement about things."), "t")

    assert emotional.emotional_intensity > neutral.emotional_intensity


def test_information_density_rewards_specifics_over_filler():
    dense = score_candidate(_window("In 2024, 73 percent of creators grew subscribers by 40 percent."), "t")
    filler = score_candidate(_window("So like you know it was just kind of a thing that happened."), "t")

    assert dense.information_density > filler.information_density


def test_question_answer_structure_rewards_answered_questions():
    answered = score_candidate(_window("Why do most channels fail? Because they never post consistently enough."), "t")
    unanswered = score_candidate(_window("Why do most channels fail?"), "t")
    none_at_all = score_candidate(_window("Most channels fail for many reasons."), "t")

    assert answered.question_answer_structure > unanswered.question_answer_structure
    assert unanswered.question_answer_structure > none_at_all.question_answer_structure


def test_novelty_scores_rare_words_higher_than_repeated_ones():
    full_transcript = "the cat sat on the mat " * 20 + " quantum entanglement explains this rare phenomenon"

    repeated_window = score_candidate(_window("the cat sat on the mat"), full_transcript)
    rare_window = score_candidate(_window("quantum entanglement explains this rare phenomenon"), full_transcript)

    assert rare_window.novelty > repeated_window.novelty


def test_keyword_relevance_boosts_matching_content():
    with_keyword = score_candidate(_window("This video is about photography lighting techniques."), "t", target_keywords=["photography", "lighting"])
    without_keyword = score_candidate(_window("This video is about cooking recipes."), "t", target_keywords=["photography", "lighting"])

    assert with_keyword.keyword_relevance > without_keyword.keyword_relevance


def test_keyword_relevance_is_neutral_when_no_keywords_given():
    result = score_candidate(_window("Any text at all."), "t", target_keywords=None)
    assert result.keyword_relevance == 50.0


def test_duration_fit_penalizes_windows_far_from_target_center():
    target_fit = score_candidate(_window("x", start=0, end=37.5), "t", min_duration=15, max_duration=60)
    edge_fit = score_candidate(_window("x", start=0, end=15), "t", min_duration=15, max_duration=60)

    assert target_fit.duration_fit > edge_fit.duration_fit


def test_rank_candidates_returns_non_overlapping_windows():
    segments = [_seg(i * 5, i * 5 + 5, f"Here's how thing {i} works in detail today.") for i in range(20)]
    full_text = " ".join(s.text for s in segments)

    ranked = rank_candidates(segments, full_text, min_duration=15, max_duration=25, top_k=5)

    assert len(ranked) > 1
    for i in range(len(ranked)):
        for j in range(i + 1, len(ranked)):
            window_a, _ = ranked[i]
            window_b, _ = ranked[j]
            assert not (window_a.start_seconds < window_b.end_seconds and window_b.start_seconds < window_a.end_seconds)


def test_rank_candidates_orders_by_score_descending():
    segments = [
        _seg(0, 20, "So um yeah I was just kind of thinking about stuff you know like whatever."),
        _seg(25, 45, "Here's the secret nobody tells you about growing your channel fast!"),
    ]
    full_text = " ".join(s.text for s in segments)

    ranked = rank_candidates(segments, full_text, min_duration=15, max_duration=25, top_k=5)

    scores = [breakdown.weighted_total for _, breakdown in ranked]
    assert scores == sorted(scores, reverse=True)


def test_score_breakdown_as_dict_is_json_serializable():
    import json

    result = score_candidate(_window("Here's how to do something amazing today!"), "full transcript")
    serialized = json.dumps(result.as_dict())
    assert "weighted_total" in json.loads(serialized)
