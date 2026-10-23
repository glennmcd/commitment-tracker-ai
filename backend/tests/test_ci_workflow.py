"""The CI workflow runs repository code on every push and pull request, so its permissions and its
actions are checked as text: read-only token, actions pinned to commits, no secrets, and the jobs
the plan calls for, with the checks each one must run. No YAML parser is needed.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ".github/workflows/ci.yml"


def read() -> str:
    return (ROOT / WORKFLOW).read_text(encoding="utf-8")


def job(name: str) -> str:
    """The text of one job, from its key to the next job (or the end)."""
    body = read().split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([a-z0-9-]+):\n", body, flags=re.MULTILINE)
    jobs = dict(zip(parts[1::2], parts[2::2], strict=True))
    return jobs[name]


def test_runs_on_every_push_and_pull_request() -> None:
    on_block = read().split("\non:\n", 1)[1].split("\n\n", 1)[0]
    assert on_block == "  push:\n  pull_request:"


def test_never_runs_on_pull_request_target() -> None:
    # That trigger runs with a write token on code from forks.
    assert "pull_request_target" not in read()


def test_the_token_is_read_only() -> None:
    block = read().split("\npermissions:\n", 1)[1].split("\n\n", 1)[0]
    lines = [line.strip() for line in block.splitlines() if not line.strip().startswith("#")]
    assert lines == ["contents: read"]


def test_every_action_is_pinned_to_a_commit_with_its_tag_in_a_comment() -> None:
    lines = [line for line in read().splitlines() if re.match(r"^\s*-?\s*uses:", line)]
    assert len(lines) >= 6
    for line in lines:
        assert re.search(r"uses:\s*[\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+(\.\d+)*\s*$", line), line


def test_uses_no_secrets() -> None:
    assert "secrets." not in read()


def test_three_jobs_each_with_a_timeout() -> None:
    body = read().split("\njobs:\n", 1)[1]
    assert re.findall(r"^  ([a-z-]+):\n", body, flags=re.MULTILINE) == [
        "backend",
        "frontend",
        "infra",
    ]
    for name in ("backend", "frontend", "infra"):
        assert re.search(r"^    timeout-minutes: \d+$", job(name), re.MULTILINE), name


def test_backend_runs_tests_lint_format_and_types_from_the_lockfile() -> None:
    text = job("backend")
    for command in (
        "uv sync --locked",
        "uv run pytest",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
    ):
        assert command in text, command
    assert "working-directory: backend" in text


def test_frontend_lints_types_tests_and_checks_the_client() -> None:
    text = job("frontend")
    for command in (
        "bun install --frozen-lockfile",
        "bunx biome ci .",
        "bun run --cwd frontend typecheck",
        "bun run --cwd frontend test",
        "bun test scripts",
        "bun run --cwd frontend gen:api",
        "git diff --exit-code",
    ):
        assert command in text, command
    assert "playwright install" not in text and "frontend e2e" not in text, "e2e has its own job"


def test_the_browser_test_runs_in_the_playwright_image_matching_the_locked_version() -> None:
    text = job("e2e")
    for command in ("bun install --frozen-lockfile", "bun run --cwd frontend e2e"):
        assert command in text, command
    # The image ships the browsers for exactly one Playwright version; a mismatch fails at launch.
    image = re.search(r"image: mcr\.microsoft\.com/playwright:v(\d+\.\d+\.\d+)-", text)
    assert image, "the e2e job must run in the Playwright image"
    lock = (ROOT / "bun.lock").read_text(encoding="utf-8")
    locked = re.search(r'"@playwright/test@(\d+\.\d+\.\d+)"', lock)
    assert locked and image.group(1) == locked.group(1)


def test_the_generated_client_is_compared_with_the_committed_one() -> None:
    text = job("frontend")
    assert text.index("gen:api") < text.index("git diff --exit-code")
    assert "frontend/src/api/schema.d.ts" in text


def test_infra_tests_and_synthesizes_without_credentials() -> None:
    text = job("infra")
    for command in ("bun install --frozen-lockfile", "bun --cwd infra test", "cdk synth"):
        assert command in text, command
    # A placeholder account pins the stacks, so no AWS credentials are needed.
    assert "CDK_DEFAULT_ACCOUNT: '123456789012'" in text
    assert "aws-actions" not in read()


def test_the_pinned_python_and_bun_versions_match_the_repository() -> None:
    assert (ROOT / "backend/.python-version").read_text().strip() == "3.12"
    assert "bun-version: 1.4.2" in read()
    assert "bun@1.4.2" in (ROOT / "infra/lib/web-stack.ts").read_text(encoding="utf-8")
