"""Tests for AgentFactory initialization and get_agent_factory cache."""

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.agents.agents import AgentFactory, get_agent_factory


def _patch_all() -> list:
    return [
        patch("src.agents.agents.ChatOpenAI"),
        patch("src.agents.agents.OpenAIEmbeddings"),
        patch("src.agents.agents.CVVectorManager"),
        patch("src.agents.agents.ScoutAgent"),
        patch("src.agents.agents.OrchestratorAgent"),
        patch("src.agents.agents.TailorAgent"),
        patch("src.agents.agents.JobValidator"),
    ]


def test_agent_factory_creates_all_agents() -> None:
    patches = _patch_all()
    mocks = [p.start() for p in patches]
    try:
        factory = AgentFactory()
        assert factory.scout is mocks[3].return_value
        assert factory.orchestrator is mocks[4].return_value
        assert factory.tailor is mocks[5].return_value
        assert factory.job_validator is mocks[6].return_value
    finally:
        for p in patches:
            p.stop()


def test_agent_factory_uses_provided_user_id() -> None:
    user_id = uuid4()
    patches = _patch_all()
    [p.start() for p in patches]
    try:
        factory = AgentFactory(user_id=user_id)
        assert factory.user_id == user_id
    finally:
        for p in patches:
            p.stop()


def test_agent_factory_generates_default_user_id_when_none() -> None:
    patches = _patch_all()
    [p.start() for p in patches]
    try:
        factory = AgentFactory(user_id=None)
        assert factory.user_id is not None
    finally:
        for p in patches:
            p.stop()


def test_get_agent_factory_returns_cached_instance() -> None:
    get_agent_factory.cache_clear()
    patches = _patch_all()
    [p.start() for p in patches]
    try:
        f1 = get_agent_factory()
        f2 = get_agent_factory()
        assert f1 is f2
    finally:
        for p in patches:
            p.stop()
        get_agent_factory.cache_clear()


def test_get_agent_factory_scopes_by_user_id() -> None:
    get_agent_factory.cache_clear()
    uid1, uid2 = uuid4(), uuid4()
    patches = _patch_all()
    [p.start() for p in patches]
    try:
        f1 = get_agent_factory(user_id=uid1)
        f2 = get_agent_factory(user_id=uid2)
        assert f1 is not f2
    finally:
        for p in patches:
            p.stop()
        get_agent_factory.cache_clear()
