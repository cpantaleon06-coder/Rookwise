"""Pre-submission checks. Prints PASS or FAIL for each; the exit code is 1 if any FAIL.

(a) keys: no tracked file (`git ls-files`) other than .env.example holds a key-like string:
    an `sk-` key, a `tvly-` key, a `NEBIUS_API_KEY=` assignment with a value, or a long
    base64 token (40+ characters of one base64 alphabet, at least two each of upper case,
    lower case and digits, not hex, not a `sha256-`/`sha384-`/`sha512-` integrity hash).
    A hit is reported by file, line and pattern with its length only, never its text.
(b) license: LICENSE exists and is the MIT license text.
(c) readme markers: README.md contains no `TBD` and no `FILL` (case-sensitive).
(d) readme links: every http(s) link in README.md answers with a status below 400 (HEAD,
    then GET when HEAD is refused; redirects followed; timeout 10 s). A link that gives no
    status (timeout, DNS, connection error) is listed as not checked and does not fail.
    Links to model API hosts (the NEBIUS_BASE_URL host in .env.example and the hosts in
    MODEL_API_HOSTS) are skipped: this script never calls a model API.
(e) tests: `uv run --frozen python -m pytest -q` exits 0.

Nothing from .env is read.

Usage:
    python release/check_release.py
    python release/check_release.py --root PATH
"""

from __future__ import annotations

import argparse
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
TEST_COMMAND = ("uv", "run", "--frozen", "python", "-m", "pytest", "-q")
LINK_TIMEOUT_S = 10.0
USER_AGENT = "rookwise-release-check"
# Never requested, whatever README.md links to.
MODEL_API_HOSTS = (
    "tokenfactory.nebius.com",
    "api.studio.nebius.ai",
    "api.openai.com",
    "api.anthropic.com",
    "api.tavily.com",
)
KEY_ALLOWED = {".env.example"}

KEY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sk- key", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("tvly- key", re.compile(r"(?<![A-Za-z0-9])tvly-[A-Za-z0-9_-]{16,}")),
    (
        "NEBIUS_API_KEY= value",
        re.compile(r"NEBIUS_API_KEY\s*=\s*['\"]?(?![<${])[^\s'\"<>]{8,}"),
    ),
)
BASE64_STD = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")
# Not next to any base64 character, so a piece of a standard token is not matched again.
BASE64_URL = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9_-]{40,}(?![A-Za-z0-9+/=_-])")
INTEGRITY_PREFIX = re.compile(r"sha(?:256|384|512)-$")
INTEGRITY_TOKEN = re.compile(r"sha(?:256|384|512)-")
HEX = re.compile(r"[0-9a-fA-F]+")
LINK = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
MIT_MARKERS = (
    "MIT License",
    "Permission is hereby granted, free of charge",
    'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND',
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def looks_like_base64_token(token: str) -> bool:
    body = token.rstrip("=")
    if HEX.fullmatch(body):
        return False
    return all(len(re.findall(cls, body)) >= 2 for cls in ("[A-Z]", "[a-z]", "[0-9]"))


def key_hits(text: str) -> list[tuple[int, str, int]]:
    """(line, pattern name, match length) for every key-like string in `text`."""
    hits: list[tuple[int, str, int]] = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for name, pattern in KEY_PATTERNS:
        hits += [(line_of(m.start()), name, len(m.group())) for m in pattern.finditer(text)]
    for pattern in (BASE64_STD, BASE64_URL):
        for m in pattern.finditer(text):
            before = text[max(0, m.start() - 7) : m.start()]
            if INTEGRITY_PREFIX.search(before) or INTEGRITY_TOKEN.match(m.group()):
                continue
            if looks_like_base64_token(m.group()):
                hits.append((line_of(m.start()), "long base64 token", len(m.group())))
    return sorted(set(hits))


def check_keys(root: Path) -> CheckResult:
    result = CheckResult("(a) no key patterns in tracked files", True)
    for name in tracked_files(root):
        if name in KEY_ALLOWED:
            continue
        try:
            data = (root / name).read_bytes()
        except OSError:  # tracked but deleted in the working tree
            continue
        if b"\0" in data[:8192]:
            continue
        for line, pattern, length in key_hits(data.decode("utf-8", errors="replace")):
            result.passed = False
            result.details.append(f"{name}:{line}: {pattern} ({length} chars)")
    return result


def check_license(root: Path) -> CheckResult:
    path = root / "LICENSE"
    if not path.is_file():
        return CheckResult("(b) LICENSE exists and is MIT", False, ["LICENSE not found"])
    text = " ".join(path.read_text(encoding="utf-8", errors="replace").split())
    missing = [marker for marker in MIT_MARKERS if marker not in text]
    return CheckResult(
        "(b) LICENSE exists and is MIT",
        not missing,
        [f"missing MIT text: {marker!r}" for marker in missing],
    )


def check_readme_markers(root: Path) -> CheckResult:
    result = CheckResult("(c) README.md has no TBD or FILL", True)
    path = root / "README.md"
    if not path.is_file():
        return CheckResult(result.name, False, ["README.md not found"])
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for marker in ("TBD", "FILL"):
            if marker in line:
                result.passed = False
                result.details.append(f"README.md:{number}: {marker}: {line.strip()[:100]}")
    return result


def readme_links(text: str) -> list[str]:
    links = (m.group().rstrip(".,;:!?*_") for m in LINK.finditer(text))
    return list(dict.fromkeys(links))


def model_api_hosts(root: Path) -> set[str]:
    hosts = set(MODEL_API_HOSTS)
    example = root / ".env.example"
    if example.is_file():
        for line in example.read_text(encoding="utf-8").splitlines():
            if line.startswith("NEBIUS_BASE_URL="):
                host = urlparse(line.split("=", 1)[1].strip()).hostname
                if host:
                    hosts.add(host)
    return hosts


def is_model_api(url: str, hosts: set[str]) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == h or host.endswith("." + h) for h in hosts)


def http_status(url: str, timeout: float) -> int:
    """The final status of `url` (HEAD, then GET when HEAD is refused). Raises OSError
    (URLError, timeouts) when there is no status."""
    status = 0
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        if status not in (403, 405, 501):
            break
    return status


def check_readme_links(
    root: Path,
    timeout: float = LINK_TIMEOUT_S,
    status_of: Callable[[str, float], int] = http_status,
) -> CheckResult:
    result = CheckResult("(d) README.md links answer below 400", True)
    path = root / "README.md"
    if not path.is_file():
        return CheckResult(result.name, False, ["README.md not found"])
    hosts = model_api_hosts(root)
    links = readme_links(path.read_text(encoding="utf-8"))
    checked = 0
    for url in links:
        if is_model_api(url, hosts):
            result.details.append(f"skipped (model API host): {url}")
            continue
        try:
            status = status_of(url, timeout)
        except (OSError, ValueError) as error:
            result.details.append(f"could not check: {url} ({type(error).__name__})")
            continue
        checked += 1
        if status >= 400:
            result.passed = False
            result.details.append(f"HTTP {status}: {url}")
    result.details.insert(0, f"{len(links)} links, {checked} checked")
    return result


def check_tests(root: Path, command: Sequence[str] = TEST_COMMAND) -> CheckResult:
    name = f"(e) `{' '.join(command)}` passes"
    try:
        done = subprocess.run(list(command), cwd=root, capture_output=True, text=True)
    except OSError as error:
        return CheckResult(name, False, [f"could not start: {type(error).__name__}"])
    lines = [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    return CheckResult(name, done.returncode == 0, [f"exit {done.returncode}", *lines[-3:]])


def run_checks(root: Path) -> list[CheckResult]:
    return [
        check_keys(root),
        check_license(root),
        check_readme_markers(root),
        check_readme_links(root),
        check_tests(root),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    args = parser.parse_args(argv)
    results = run_checks(args.root.resolve())
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'}  {result.name}")
        for detail in result.details:
            print(f"      {detail}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
