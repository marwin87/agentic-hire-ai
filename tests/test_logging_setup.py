"""Tests for setup_logging configuration branches."""

from src.config.logging import setup_logging


def test_setup_logging_plain_non_debug(monkeypatch: object) -> None:
    monkeypatch.delenv("AGENTIC_HIRE_JSON_LOGS", raising=False)  # type: ignore[attr-defined]
    setup_logging(debug=False, log_level="INFO")


def test_setup_logging_plain_debug(monkeypatch: object) -> None:
    monkeypatch.delenv("AGENTIC_HIRE_JSON_LOGS", raising=False)  # type: ignore[attr-defined]
    setup_logging(debug=True, log_level="DEBUG")


def test_setup_logging_json_mode(monkeypatch: object) -> None:
    monkeypatch.setenv("AGENTIC_HIRE_JSON_LOGS", "true")  # type: ignore[attr-defined]
    setup_logging(debug=False, log_level="WARNING")


def test_setup_logging_json_not_active_by_default(monkeypatch: object) -> None:
    monkeypatch.setenv("AGENTIC_HIRE_JSON_LOGS", "false")  # type: ignore[attr-defined]
    setup_logging(debug=False, log_level="ERROR")
