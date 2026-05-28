"""
Graceful shutdown integration tests.

These tests verify that Docker Compose services handle SIGTERM cleanly —
no zombie processes, no data corruption, no hung containers.

Requirements:
  - Docker and Docker Compose installed
  - Valid .env file with required secrets
  - Run from the project root

Usage (local only — not part of standard pytest run):
  DOCKER_INTEGRATION=true uv run pytest tests/integration/ -v

In CI these tests are driven by the docker-compose-test job in ci.yml,
which uses `docker compose stop` (sends SIGTERM without triggering restart policy).
"""

import os
import subprocess
import time

import pytest

DOCKER_INTEGRATION = os.getenv("DOCKER_INTEGRATION", "false").lower() == "true"
skip_without_docker = pytest.mark.skipif(
    not DOCKER_INTEGRATION,
    reason="Set DOCKER_INTEGRATION=true to run Docker integration tests",
)


def run(cmd: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)


@skip_without_docker
def test_docker_compose_up_wait() -> None:
    """Services reach healthy state within the timeout window."""
    try:
        result = run("docker compose up -d --wait --timeout 60")
        assert (
            result.returncode == 0
        ), f"docker compose up --wait failed:\n{result.stderr}"
    finally:
        run("docker compose down", check=False)


@skip_without_docker
def test_graceful_shutdown_api() -> None:
    """API service exits cleanly on SIGTERM — Exited (0), not force-killed (137)."""
    try:
        run("docker compose up -d --wait --timeout 60")

        # Use `stop` not `kill -s SIGTERM`: both send SIGTERM, but `kill` triggers
        # restart: unless-stopped and containers come back up immediately.
        run("docker compose stop")

        ps_output = run("docker compose ps -a").stdout
        assert (
            " Up " not in ps_output
        ), f"Containers still running after docker compose stop:\n{ps_output}"

        # Exit code 137 = force-killed (SIGKILL) — means uvicorn ignored SIGTERM
        api_exit = run(
            "docker inspect agentic-hire-api --format='{{.State.ExitCode}}'",
            check=False,
        ).stdout.strip()
        assert (
            api_exit != "137"
        ), "API was force-killed (exit 137) — uvicorn did not respond to SIGTERM within grace period"
    finally:
        run("docker compose down", check=False)


@skip_without_docker
def test_graceful_shutdown_no_zombies() -> None:
    """No defunct uvicorn processes inside the container before graceful stop."""
    try:
        run("docker compose up -d --wait --timeout 60")

        # Check container-internal processes before stopping (host ps is blind to Docker)
        result = run("docker top agentic-hire-api", check=False)
        zombie_lines = [
            line
            for line in result.stdout.splitlines()
            if "defunct" in line or "<defunct>" in line
        ]
        assert not zombie_lines, f"Zombie uvicorn processes found:\n{zombie_lines}"
    finally:
        run("docker compose down", check=False)
