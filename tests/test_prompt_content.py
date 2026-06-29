"""Smoke-tests that agent prompt templates contain required structural sections.

These tests don't invoke any LLM — they assert that the named constants exist
and contain the sections that make prompts consistent and testable.
"""

from src.agents.orchestrator import _MATCH_PROMPT_TEMPLATE
from src.agents.tailor import _EVALUATION_PROMPT_TEMPLATE, _ADVISOR_SYSTEM_PROMPT

# ===== Orchestrator prompt =====


def test_match_prompt_contains_scoring_rules() -> None:
    assert "SCORING RULES" in _MATCH_PROMPT_TEMPLATE


def test_match_prompt_contains_few_shot_examples() -> None:
    assert "FEW-SHOT EXAMPLES" in _MATCH_PROMPT_TEMPLATE


def test_match_prompt_covers_all_score_bands() -> None:
    """All four score bands (1.0, 0.8, 0.6, <0.5) must appear in the template."""
    for band in ("1.0", "0.8", "0.6", "0.5"):
        assert band in _MATCH_PROMPT_TEMPLATE, f"Score band {band} missing from prompt"


def test_match_prompt_has_placeholders() -> None:
    for placeholder in ("{title}", "{company}", "{description}", "{cv_context}"):
        assert placeholder in _MATCH_PROMPT_TEMPLATE


# ===== Tailor prompt =====


def test_evaluation_prompt_contains_example_output() -> None:
    assert "EXAMPLE OUTPUT" in _EVALUATION_PROMPT_TEMPLATE


def test_evaluation_prompt_requires_single_sentence() -> None:
    assert (
        "ONE" in _EVALUATION_PROMPT_TEMPLATE
        or "single" in _EVALUATION_PROMPT_TEMPLATE.lower()
    )


def test_evaluation_prompt_has_placeholders() -> None:
    for placeholder in (
        "{resume_context}",
        "{title}",
        "{company}",
        "{description}",
        "{analysis}",
    ):
        assert placeholder in _EVALUATION_PROMPT_TEMPLATE


def test_advisor_system_prompt_is_non_empty() -> None:
    assert len(_ADVISOR_SYSTEM_PROMPT.strip()) > 0
