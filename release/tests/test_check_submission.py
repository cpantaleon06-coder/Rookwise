import http.server
import subprocess
import threading
from pathlib import Path

import check_submission as cs
import pytest

REPO_LICENSE = Path(__file__).resolve().parents[2] / "LICENSE"

README_OK = """# Rookwise

## Quick start

Run `uv sync`.

## How we use NVIDIA Nemotron and Nebius Token Factory

Every level uses a Nemotron model.

What Token Factory made possible: one endpoint for four sizes.

Findings are in FEEDBACK.md.
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def feedback(entries: int) -> str:
    return "# Feedback\n\n## 2026-10-12\n" + "".join(
        f"- Finding {i}.\n  - Sent: detail.\n" for i in range(entries)
    )


class FakeRunner:
    def __init__(self, code=0, error=None):
        self.code, self.error, self.calls = code, error, []

    def __call__(self, command, env, timeout):
        self.calls.append((list(command), env))
        if self.error:
            raise self.error
        return self.code


def test_public_repo_runs_anonymous_ls_remote():
    runner = FakeRunner(0)
    result = cs.check_public_repo("https://example.test/x.git", runner)
    assert result.status == cs.PASS
    command, env = runner.calls[0]
    assert command == [
        "git",
        "-c",
        "credential.helper=",
        "ls-remote",
        "--heads",
        "https://example.test/x.git",
    ]
    assert env["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.parametrize(
    "runner", [FakeRunner(128), FakeRunner(error=subprocess.TimeoutExpired("git", 60))]
)
def test_public_repo_fails(runner):
    assert cs.check_public_repo("https://example.test/x.git", runner).status == cs.FAIL


def test_license(tmp_path):
    (tmp_path / "LICENSE").write_text(REPO_LICENSE.read_text(encoding="utf-8"), encoding="utf-8")
    assert cs.check_license(tmp_path).status == cs.PASS
    (tmp_path / "LICENSE").write_text("Apache License\nVersion 2.0\n", encoding="utf-8")
    assert cs.check_license(tmp_path).status == cs.FAIL
    (tmp_path / "LICENSE").unlink()
    assert cs.check_license(tmp_path).details == ["LICENSE not found"]


def test_readme_topics_pass(tmp_path):
    results = cs.check_readme_topics(write(tmp_path, {"README.md": README_OK}))
    assert [r.status for r in results] == [cs.PASS] * 4
    assert results[0].details == ["line 3: ## Quick start"]


def test_readme_topics_fail(tmp_path):
    text = "# Rookwise\n\nToken Factory is an API.\n\nNothing else here.\n"
    results = {
        r.name: r.status for r in cs.check_readme_topics(write(tmp_path, {"README.md": text}))
    }
    assert results == {
        "README.md covers setup instructions": cs.FAIL,
        "README.md covers how Nemotron is used": cs.FAIL,
        "README.md covers where Token Factory helped": cs.FAIL,
        "README.md covers feedback log": cs.FAIL,
    }


@pytest.mark.parametrize(("entries", "status"), [(5, cs.PASS), (4, cs.FAIL)])
def test_feedback_entries(tmp_path, entries, status):
    result = cs.check_feedback(write(tmp_path, {"FEEDBACK.md": feedback(entries)}))
    assert result.status == status
    assert result.details == [f"{entries} entries"]


def test_feedback_missing(tmp_path):
    assert cs.check_feedback(tmp_path).status == cs.FAIL


def test_readme_markers(tmp_path):
    write(tmp_path, {"README.md": "ok\n| a | TBD |\n<!-- FILL: x -->\n"})
    result = cs.check_readme_markers(tmp_path)
    assert result.status == cs.FAIL
    assert [d.split(":")[1] for d in result.details] == ["2", "3"]
    write(tmp_path, {"README.md": "ok\n"})
    assert cs.check_readme_markers(tmp_path).status == cs.PASS


@pytest.mark.parametrize(
    ("answer", "status"),
    [
        ((200, "<title>Rookwise</title>"), cs.PASS),
        ((200, "<title>Vite App</title>"), cs.FAIL),
        ((404, ""), cs.FAIL),
        (OSError("down"), cs.FAIL),
    ],
)
def test_demo_with_fake_fetcher(answer, status):
    def fetcher(url, timeout):
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert cs.check_demo("https://demo.example.test/", fetcher).status == status


def test_demo_not_given_is_manual():
    assert cs.check_demo(None).status == cs.MANUAL
    assert cs.check_demo("ftp://x.test/").status == cs.FAIL


def test_fetch_against_local_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><title>Rookwise</title></html>"
            self.send_response(200 if self.path == "/" else 404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        assert cs.check_demo(base + "/").status == cs.PASS
        assert cs.check_demo(base + "/missing").details[0].endswith("HTTP 404")
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    ("url", "status"),
    [
        ("https://youtu.be/abc123", cs.PASS),
        ("https://www.youtube.com/watch?v=abc123", cs.PASS),
        ("https://m.youtube.com/watch?v=abc123", cs.PASS),
        ("https://vimeo.com/123", cs.FAIL),
        ("https://youtube.com.evil.test/watch", cs.FAIL),
        (None, cs.MANUAL),
    ],
)
def test_video(url, status):
    link, hand = cs.check_video(url)
    assert link.status == status
    assert hand.status == cs.MANUAL
    assert hand.details == ["length and public status must be checked by hand"]


def test_run_checks_exit_status(tmp_path):
    (tmp_path / "LICENSE").write_text(REPO_LICENSE.read_text(encoding="utf-8"), encoding="utf-8")
    write(tmp_path, {"README.md": README_OK, "FEEDBACK.md": feedback(5)})
    results = cs.run_checks(tmp_path, None, "https://youtu.be/x", runner=FakeRunner(0))
    assert {r.status for r in results} == {cs.PASS, cs.MANUAL}
    results = cs.run_checks(tmp_path, None, None, runner=FakeRunner(2))
    assert results[0].status == cs.FAIL
