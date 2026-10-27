"""Check the Devpost submission requirements. Prints PASS, FAIL or MANUAL for each.

1. public repo: an anonymous `git ls-remote` of REPO_URL succeeds (credential helpers and
   prompts turned off, timeout 60 s).
2. license: LICENSE exists at the root and is the MIT license text.
3. readme topics: README.md covers setup instructions, how Nemotron is used, where Token
   Factory helped and the feedback log. Each topic passes when one paragraph or heading
   matches its pattern (see TOPICS); the matching README line is printed.
4. feedback entries: FEEDBACK.md exists and has at least 5 entries. An entry is a
   top-level list item ("- " at the start of a line), the file's one-entry-per-finding
   format, or a "###" heading.
5. readme markers: README.md contains no `TBD` and no `FILL` (case-sensitive).
6. demo url (--demo-url): a GET answers HTTP 200 and the body contains "Rookwise".
   MANUAL when no URL is given.
7. video url (--video-url): the host is youtube.com (any subdomain) or youtu.be. Its
   length and public status are always MANUAL. MANUAL when no URL is given.

MANUAL does not fail. The exit code is 1 on any FAIL. Nothing from .env is read and no
model API is called.

Usage:
    python release/check_submission.py
    python release/check_submission.py --demo-url https://... --video-url https://youtu.be/...
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/cpantaleon06-coder/Rookwise.git"
LS_REMOTE_TIMEOUT_S = 60.0
HTTP_TIMEOUT_S = 15.0
USER_AGENT = "rookwise-submission-check"
MIN_FEEDBACK_ENTRIES = 5
MIT_MARKERS = (
    "MIT License",
    "Permission is hereby granted, free of charge",
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND',
)
# Topic name, then patterns that must all match inside one paragraph (case-insensitive).
TOPICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("setup instructions", (r"\b(quick ?start|setup|set up|install(ation)?|getting started)\b",)),
    ("how Nemotron is used", (r"\bnemotron\b", r"\b(use[sd]?|using|model|level)\b")),
    (
        "where Token Factory helped",
        (r"\btoken factory\b", r"\b(help(ed|s)?|made possible|enabl(ed|es)|let us|lets)\b"),
    ),
    ("feedback log", (r"FEEDBACK\.md|\bfeedback\b",)),
)
YOUTUBE_HOSTS = ("youtube.com", "youtu.be")

PASS, FAIL, MANUAL = "PASS", "FAIL", "MANUAL"


@dataclass
class CheckResult:
    name: str
    status: str
    details: list[str] = field(default_factory=list)


Runner = Callable[[Sequence[str], dict[str, str], float], int]
Fetcher = Callable[[str, float], tuple[int, str]]


def run_command(command: Sequence[str], env: dict[str, str], timeout: float) -> int:
    done = subprocess.run(list(command), env=env, capture_output=True, timeout=timeout)
    return done.returncode


def check_public_repo(url: str = REPO_URL, runner: Runner = run_command) -> CheckResult:
    name = "repository is public (anonymous git ls-remote)"
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "",
        "SSH_ASKPASS": "",
        "GCM_INTERACTIVE": "never",
    }
    # An empty credential.helper drops every configured helper, so no stored login is used.
    command = ["git", "-c", "credential.helper=", "ls-remote", "--heads", url]
    try:
        code = runner(command, env, LS_REMOTE_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckResult(name, FAIL, [f"{url}: {type(error).__name__}"])
    return CheckResult(name, PASS if code == 0 else FAIL, [f"{url}: exit {code}"])


def check_license(root: Path) -> CheckResult:
    name = "LICENSE exists at the root and is MIT"
    path = root / "LICENSE"
    if not path.is_file():
        return CheckResult(name, FAIL, ["LICENSE not found"])
    text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())
    missing = [m for m in MIT_MARKERS if m not in text]
    return CheckResult(name, FAIL if missing else PASS, [f"missing: {m!r}" for m in missing])


def paragraphs(text: str) -> list[tuple[int, str]]:
    """(first line number, text) for each block between blank lines; headings stand alone."""
    blocks: list[tuple[int, str]] = []
    current: list[str] = []
    start = 1
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            if current:
                blocks.append((start, "\n".join(current)))
                current = []
            if line.strip():
                blocks.append((number, line))
            continue
        if not current:
            start = number
        current.append(line)
    if current:
        blocks.append((start, "\n".join(current)))
    return blocks


def check_readme_topics(root: Path) -> list[CheckResult]:
    path = root / "README.md"
    if not path.is_file():
        return [
            CheckResult(f"README.md covers {t}", FAIL, ["README.md not found"]) for t, _ in TOPICS
        ]
    blocks = paragraphs(path.read_text(encoding="utf-8"))
    results = []
    for topic, patterns in TOPICS:
        hit = next(
            (
                (line, block)
                for line, block in blocks
                if all(re.search(p, block, re.IGNORECASE) for p in patterns)
            ),
            None,
        )
        if hit is None:
            results.append(
                CheckResult(f"README.md covers {topic}", FAIL, ["no matching paragraph"])
            )
        else:
            line, block = hit
            first = block.splitlines()[0].strip()[:90]
            results.append(
                CheckResult(f"README.md covers {topic}", PASS, [f"line {line}: {first}"])
            )
    return results


def count_feedback_entries(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith(("- ", "### ")))


def check_feedback(root: Path, minimum: int = MIN_FEEDBACK_ENTRIES) -> CheckResult:
    name = f"FEEDBACK.md exists with at least {minimum} entries"
    path = root / "FEEDBACK.md"
    if not path.is_file():
        return CheckResult(name, FAIL, ["FEEDBACK.md not found"])
    count = count_feedback_entries(path.read_text(encoding="utf-8"))
    return CheckResult(name, PASS if count >= minimum else FAIL, [f"{count} entries"])


def check_readme_markers(root: Path) -> CheckResult:
    name = "README.md has no TBD or FILL"
    path = root / "README.md"
    if not path.is_file():
        return CheckResult(name, FAIL, ["README.md not found"])
    details = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for marker in ("TBD", "FILL"):
            if marker in line:
                details.append(f"README.md:{number}: {marker}: {line.strip()[:90]}")
    return CheckResult(name, FAIL if details else PASS, details)


def fetch(url: str, timeout: float) -> tuple[int, str]:
    """Status and body text of a GET. Raises OSError (URLError, timeouts) when there is no
    status."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, ""


def check_demo(url: str | None, fetcher: Fetcher = fetch) -> CheckResult:
    name = "demo URL answers 200 and mentions Rookwise"
    if not url:
        return CheckResult(name, MANUAL, ["no --demo-url given"])
    if urlparse(url).scheme not in ("http", "https"):
        return CheckResult(name, FAIL, [f"not an http(s) URL: {url}"])
    try:
        status, body = fetcher(url, HTTP_TIMEOUT_S)
    except (OSError, ValueError) as error:
        return CheckResult(name, FAIL, [f"{url}: {type(error).__name__}"])
    details = [f"{url}: HTTP {status}"]
    if status != 200:
        return CheckResult(name, FAIL, details)
    if "Rookwise" not in body:
        return CheckResult(name, FAIL, [*details, "body does not contain 'Rookwise'"])
    return CheckResult(name, PASS, details)


def check_video(url: str | None) -> list[CheckResult]:
    name = "video URL is a YouTube link"
    hand = CheckResult(
        "video length and public status",
        MANUAL,
        ["length and public status must be checked by hand"],
    )
    if not url:
        return [CheckResult(name, MANUAL, ["no --video-url given"]), hand]
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    ok = parsed.scheme in ("http", "https") and any(
        host == h or host.endswith("." + h) for h in YOUTUBE_HOSTS
    )
    return [CheckResult(name, PASS if ok else FAIL, [url]), hand]


def run_checks(
    root: Path,
    demo_url: str | None,
    video_url: str | None,
    runner: Runner = run_command,
    fetcher: Fetcher = fetch,
) -> list[CheckResult]:
    return [
        check_public_repo(REPO_URL, runner),
        check_license(root),
        *check_readme_topics(root),
        check_feedback(root),
        check_readme_markers(root),
        check_demo(demo_url, fetcher),
        *check_video(video_url),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo-url", help="deployed demo URL")
    parser.add_argument("--video-url", help="YouTube video URL")
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args(argv)
    results = run_checks(args.root.resolve(), args.demo_url, args.video_url)
    for result in results:
        print(f"{result.status:<6}  {result.name}")
        for detail in result.details:
            print(f"        {detail}")
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
