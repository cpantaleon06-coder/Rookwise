import http.server
import subprocess
import sys
import threading
from pathlib import Path

import check_release
import pytest

REPO_LICENSE = Path(__file__).resolve().parents[2] / "LICENSE"

# Key-like strings are built at run time so no tracked file holds one (check (a)).
FAKE_SK = "sk" + "-" + "A1b2C3d4" * 4
FAKE_TVLY = "tvly" + "-" + "Z9y8X7w6" * 3
FAKE_B64 = "QmFzZTY0" + "U3ludGhldGljVG9r" + "ZW5Gb3JUZXN0czEyMzQ1Njc4" + "=="
FAKE_NEBIUS = "NEBIUS_API_KEY" + "=" + "v1." + "Q2w3E4r5" * 3


def git_repo(
    tmp_path: Path, files: dict[str, str], untracked: dict[str, str] | None = None
) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for name, text in {**files, **(untracked or {})}.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "--", *files], cwd=tmp_path, check=True)
    return tmp_path


@pytest.mark.parametrize(
    ("text", "pattern"),
    [
        (f"key = '{FAKE_SK}'", "sk- key"),
        (f"TAVILY={FAKE_TVLY}", "tvly- key"),
        (FAKE_NEBIUS, "NEBIUS_API_KEY= value"),
        (f'"token": "{FAKE_B64}"', "long base64 token"),
    ],
)
def test_key_patterns_found(text, pattern):
    hits = check_release.key_hits("first line\n" + text)
    assert (2, pattern) in [(line, name) for line, name, _ in hits]


@pytest.mark.parametrize(
    "text",
    [
        "NEBIUS_API_KEY=",
        "NEBIUS_API_KEY=<your key>",
        'export NEBIUS_API_KEY="$KEY"',
        "a" * 64,
        "8da1f030185bdfe8471220585162991eaeb970e9f652327d4e953d7957d99e73",
        '"integrity": "sha512-' + "Ab1Cd2Ef3Gh4" * 6 + '=="',
        '"integrity": "sha512-' + "Ab1Cd2Ef/" + "Gh3Ij4Kl5Mn6" * 5 + "+Op7Qr8==" + '"',
        "licenses/knowledge-work-plugins-Apache-2.0-LICENSE",
        "see https://docs.astral.sh/uv/ for setup",
        "sk-short",
    ],
)
def test_key_patterns_ignore_ordinary_text(text):
    assert check_release.key_hits(text) == []


def test_check_keys_reports_tracked_files_only(tmp_path):
    root = git_repo(
        tmp_path,
        {"ok.py": "x = 1\n", "leak.md": f"one\n{FAKE_SK}\n", ".env.example": FAKE_NEBIUS},
        untracked={"local.txt": FAKE_SK},
    )
    result = check_release.check_keys(root)
    assert not result.passed
    assert result.details == [f"leak.md:2: sk- key ({len(FAKE_SK)} chars)"]
    assert FAKE_SK not in "\n".join(result.details)


def test_check_keys_passes_clean_repo(tmp_path):
    root = git_repo(tmp_path, {"ok.py": "x = 1\n"})
    assert check_release.check_keys(root).passed


def test_license_mit(tmp_path):
    (tmp_path / "LICENSE").write_text(REPO_LICENSE.read_text(encoding="utf-8"), "utf-8")
    assert check_release.check_license(tmp_path).passed


def test_license_missing_or_other(tmp_path):
    assert not check_release.check_license(tmp_path).passed
    (tmp_path / "LICENSE").write_text("Apache License\nVersion 2.0\n", encoding="utf-8")
    assert not check_release.check_license(tmp_path).passed


def test_readme_markers(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n\nAll measured.\n", encoding="utf-8")
    assert check_release.check_readme_markers(tmp_path).passed
    readme.write_text("# Title\n\nCost: TBD\nFILL ME\n", encoding="utf-8")
    result = check_release.check_readme_markers(tmp_path)
    assert not result.passed
    assert [d.split(": ")[0] for d in result.details] == ["README.md:3", "README.md:4"]


def test_readme_links_with_fake_status(tmp_path):
    (tmp_path / ".env.example").write_text(
        "NEBIUS_BASE_URL=https://models.example.test/v1/\n", encoding="utf-8"
    )
    (tmp_path / "README.md").write_text(
        "[ok](https://ok.example.test/a). See <https://gone.example.test/b>,\n"
        "https://down.example.test and https://models.example.test/v1/chat.\n"
        "[ok again](https://ok.example.test/a)\n",
        encoding="utf-8",
    )
    statuses = {"https://ok.example.test/a": 200, "https://gone.example.test/b": 404}
    asked: list[tuple[str, float]] = []

    def status_of(url, timeout):
        asked.append((url, timeout))
        if url not in statuses:
            raise TimeoutError
        return statuses[url]

    result = check_release.check_readme_links(tmp_path, status_of=status_of)
    assert not result.passed
    assert [url for url, _ in asked] == [
        "https://ok.example.test/a",
        "https://gone.example.test/b",
        "https://down.example.test",
    ]
    assert {timeout for _, timeout in asked} == {10.0}
    assert result.details == [
        "4 links, 2 checked",
        "HTTP 404: https://gone.example.test/b",
        "could not check: https://down.example.test (TimeoutError)",
        "skipped (model API host): https://models.example.test/v1/chat",
    ]


class Handler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        if self.path == "/no-head":
            self.send_response(405)
        else:
            self.send_response(200 if self.path == "/ok" else 404)
        self.end_headers()

    def do_GET(self):
        self.send_response(200 if self.path in ("/ok", "/no-head") else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_http_status_against_local_server(local_server):
    assert check_release.http_status(f"{local_server}/ok", 5) == 200
    assert check_release.http_status(f"{local_server}/no-head", 5) == 200
    assert check_release.http_status(f"{local_server}/missing", 5) == 404


def test_check_tests_uses_exit_code(tmp_path):
    ok = check_release.check_tests(tmp_path, [sys.executable, "-c", "print('3 passed')"])
    assert ok.passed and ok.details == ["exit 0", "3 passed"]
    bad = check_release.check_tests(tmp_path, [sys.executable, "-c", "raise SystemExit(1)"])
    assert not bad.passed and bad.details[0] == "exit 1"
    missing = check_release.check_tests(tmp_path, ["no-such-command-rookwise"])
    assert not missing.passed


def test_main_exit_code(monkeypatch, capsys):
    results = [check_release.CheckResult("one", True), check_release.CheckResult("two", False)]
    monkeypatch.setattr(check_release, "run_checks", lambda root: results)
    assert check_release.main([]) == 1
    assert capsys.readouterr().out.splitlines() == ["PASS  one", "FAIL  two"]
