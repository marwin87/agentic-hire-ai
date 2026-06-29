"""Tests for CVVectorManager structured CV detection."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from src.tools.vectordb import CVVectorManager, CVDetectionResult


@pytest.fixture
def manager(tmp_path: Path) -> CVVectorManager:
    mock_vision = MagicMock()
    mock_embeddings = MagicMock()
    return CVVectorManager(
        vision_model=mock_vision,
        embeddings=mock_embeddings,
        user_id=uuid4(),
        cv_cache_dir=str(tmp_path),
    )


def test_detect_if_cv_passes_when_is_cv_true(manager: CVVectorManager) -> None:
    """No exception raised when vision model confirms the page is a CV."""
    mock_detector = MagicMock()
    mock_detector.invoke.return_value = CVDetectionResult(
        is_cv=True, reason="This is a professional resume with work history."
    )
    manager.vision_model.with_structured_output.return_value = mock_detector

    manager._detect_if_cv("base64encodedimage==")

    manager.vision_model.with_structured_output.assert_called_once_with(
        CVDetectionResult
    )


def test_detect_if_cv_raises_when_is_cv_false(manager: CVVectorManager) -> None:
    """ValueError raised with reason text when page is not a CV."""
    mock_detector = MagicMock()
    mock_detector.invoke.return_value = CVDetectionResult(
        is_cv=False, reason="This appears to be a company brochure, not a CV."
    )
    manager.vision_model.with_structured_output.return_value = mock_detector

    with pytest.raises(ValueError, match="company brochure"):
        manager._detect_if_cv("base64encodedimage==")


def test_detect_if_cv_uses_structured_output_not_raw_string(
    manager: CVVectorManager,
) -> None:
    """with_structured_output is used — raw invoke is never called directly."""
    mock_detector = MagicMock()
    mock_detector.invoke.return_value = CVDetectionResult(
        is_cv=True, reason="CV confirmed."
    )
    manager.vision_model.with_structured_output.return_value = mock_detector

    manager._detect_if_cv("base64encodedimage==")

    manager.vision_model.invoke.assert_not_called()
