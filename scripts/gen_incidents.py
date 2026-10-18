"""Generate the SYNTHETIC incident corpus in benchmarks/incidents/ (docs/ARCHITECTURE.md,
"Benchmark design"): the single source of test data for the benchmark, the live runs and
later experiments.

Six fictional incidents, three dev and three test. Each incident directory holds:

- logs/: two or three services, plain text (`.log`) and JSON lines (`.jsonl`), 5,000 to
  20,000 lines in total, with healthy traffic, routine warnings, background errors, planted
  evidence and at least two decoys (alarming errors unrelated to the cause);
- metrics.csv (one row per minute), deploy.diff, runbook.md and ticket.md (the alert that
  starts the investigation);
- ground_truth.json: the root cause, its category, essential and supporting evidence refs
  (source id, 1-based lines, exact quote), acceptable remediations, decoys, split,
  difficulty and `keyword_free_evidence`.

Everything is fictional and says SYNTHETIC on its first line (or in its fields). Hosts use
reserved example domains, addresses come from RFC 5737, and no key or person appears.

Deterministic: the same seed writes the same bytes (CPython's `random`, with only
`random()`, `randrange()` and `getrandbits()`). Run from anywhere:

    python scripts/gen_incidents.py            # write benchmarks/incidents/ and manifest.json
    python scripts/gen_incidents.py --check    # rebuild in memory, compare with the manifest
    python scripts/gen_incidents.py --out DIR  # write the corpus somewhere else

The logs are gitignored; the small files and manifest.json (sha256 of every file) are
committed. Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "benchmarks" / "incidents"
GENERATOR = "scripts/gen_incidents.py"
SEED = 20261017
MINUTES = 360  # every incident covers six hours from 00:00 UTC
CATEGORIES = (
    "bad_config",
    "code_regression",
    "resource_leak",
    "certificate_expiry",
    "capacity_exhaustion",
    "dependency_latency",
    "disk_exhaustion",
    "network_failure",
)
KEYWORDS = re.compile(r"ERROR|WARN|FATAL", re.IGNORECASE)
FICTION = "Fictional: every host, address, key, person and event is made up."
DOC_NETS = ("192.0.2", "198.51.100", "203.0.113")  # RFC 5737 documentation ranges


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def at(day: datetime, hhmm: str, seconds: float = 0.0) -> datetime:
    hours, minutes = (int(part) for part in hhmm.split(":"))
    return day + timedelta(hours=hours, minutes=minutes, milliseconds=round(seconds * 1000))


def jitter(rng: random.Random, low: float, high: float) -> float:
    return low + (high - low) * rng.random()


def duration(rng: random.Random, base: int, spread: int) -> int:
    return base + int(spread * rng.random() ** 3)


def req_id(rng: random.Random) -> str:
    return f"{rng.getrandbits(32):08x}"


def spread(rng: random.Random, start: datetime, per_minute: float) -> list[datetime]:
    count = int(per_minute * MINUTES)
    return [start + timedelta(milliseconds=rng.randrange(MINUTES * 60_000)) for _ in range(count)]


# -- building blocks ------------------------------------------------------------------------


@dataclass
class Mark:
    """A planted line or range and the exact quote it must contain."""

    source: str
    quote: str
    note: str
    line: int = 0
    line_end: int = 0

    def ref(self) -> dict[str, object]:
        return {
            "source_id": self.source,
            "line_start": self.line,
            "line_end": self.line_end or self.line,
            "quote": self.quote,
            "note": self.note,
        }


class Log:
    def __init__(self, incident_id: str, name: str, service: str, hosts: list[str]) -> None:
        self.source = f"logs/{name}"
        self.service = service
        self.hosts = hosts
        self.jsonl = name.endswith(".jsonl")
        self.header_note = (
            f"SYNTHETIC log of {service} for Rookwise benchmark incident {incident_id}, "
            f"written by {GENERATOR} (seed {SEED}). {FICTION}"
        )
        self._items: list[tuple[datetime, int, str, Mark | None]] = []

    def emit(
        self,
        ts: datetime,
        level: str,
        component: str,
        msg: str,
        *,
        host: str,
        note: str | None = None,
        **fields: object,
    ) -> Mark | None:
        if self.jsonl:
            record = {
                "ts": iso(ts),
                "level": level.lower(),
                "service": self.service,
                "host": host,
                "component": component,
                "msg": msg,
                **fields,
            }
            text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        else:
            pairs = "".join(f" {k}={v}" for k, v in fields.items())
            text = f"{iso(ts)} {level:<5} {self.service}[{host}] {component}: {msg}{pairs}"
        mark = Mark(self.source, text, note) if note is not None else None
        self._items.append((ts, len(self._items), text, mark))
        return mark

    def render(self) -> list[str]:
        if self.jsonl:
            lines = [json.dumps({"synthetic": True, "note": self.header_note}, ensure_ascii=False)]
        else:
            lines = [f"# {self.header_note}"]
        for _, _, text, mark in sorted(self._items, key=lambda item: (item[0], item[1])):
            lines.append(text)
            if mark is not None:
                mark.line = len(lines)
        return lines


class Metrics:
    """One row per minute. Line 1 is the SYNTHETIC note, line 2 the header, and minute m is
    line m + 3."""

    def __init__(self, incident_id: str, columns: list[str]) -> None:
        self.source = "metrics.csv"
        self.note = (
            f"# SYNTHETIC metrics for Rookwise benchmark incident {incident_id}, one row per "
            f"minute, written by {GENERATOR} (seed {SEED}). {FICTION}"
        )
        self.columns = columns
        self.rows: list[str] = []

    def add(self, ts: datetime, values: list[str]) -> None:
        self.rows.append(",".join([ts.strftime("%Y-%m-%dT%H:%MZ"), *values]))

    def mark(self, first: int, last: int, note: str, quote_minute: int | None = None) -> Mark:
        quote = self.rows[first if quote_minute is None else quote_minute]
        return Mark(self.source, quote, note, first + 3, last + 3)

    def render(self) -> list[str]:
        return [self.note, ",".join(["ts", *self.columns]), *self.rows]


class Diff:
    def __init__(self, incident_id: str) -> None:
        self.source = "deploy.diff"
        self.lines = [
            f"# SYNTHETIC deploy diff for Rookwise benchmark incident {incident_id}, written by "
            f"{GENERATOR} (seed {SEED}). {FICTION}",
            "# Fictional repository; the code and the configuration below are made up.",
        ]

    def add(self, *lines: str) -> None:
        self.lines.extend(lines)

    def mark(self, text: str, note: str) -> Mark:
        self.lines.append(text)
        return Mark(self.source, text, note, len(self.lines))


@dataclass
class Incident:
    incident_id: str
    split: str
    difficulty: str
    category: str
    day: datetime
    root_cause: str
    remediations: list[str]
    keyword_free: bool
    misleading_first_hypothesis: str | None
    logs: list[Log] = field(default_factory=list)
    metrics: Metrics | None = None
    diff: Diff | None = None
    runbook: str = ""
    ticket: str = ""
    essential: list[Mark] = field(default_factory=list)
    supporting: list[Mark] = field(default_factory=list)
    decoys: list[Mark] = field(default_factory=list)

    def header(self, kind: str) -> str:
        return (
            f"SYNTHETIC {kind} for Rookwise benchmark incident {self.incident_id}, written by "
            f"{GENERATOR} (seed {SEED}). {FICTION}"
        )


def keep(marks: list[Mark], mark: Mark | None) -> None:
    assert mark is not None
    marks.append(mark)


# -- background traffic ---------------------------------------------------------------------

SCHEDULED_JOBS = ["session-cleanup", "sitemap-refresh", "stats-rollup", "token-prune"]
WORKER_FAILURES = ["timeout", "lock_busy", "upstream_429"]


def text_background(
    log: Log,
    rng: random.Random,
    start: datetime,
    *,
    heap_mb: Callable[[datetime, str], int] | None = None,
) -> None:
    """Health checks, GC lines, routine warnings and background errors on a text service."""
    for host in log.hosts:
        for minute in range(0, MINUTES, 2):
            ts = start + timedelta(minutes=minute, milliseconds=rng.randrange(60_000))
            log.emit(ts, "INFO", "health", "check ok", host=host, dur_ms=duration(rng, 1, 6))
        for minute in range(0, MINUTES, 5):
            ts = start + timedelta(minutes=minute, milliseconds=rng.randrange(60_000))
            heap = heap_mb(ts, host) if heap_mb else int(jitter(rng, 380, 430))
            log.emit(
                ts,
                "INFO",
                "runtime",
                "gc cycle",
                host=host,
                pause_ms=duration(rng, 2, 14),
                heap_mb=heap,
            )
    for ts in spread(rng, start, 1 / 12):
        log.emit(
            ts,
            "WARN",
            "db",
            "slow query",
            host=rng.choice(log.hosts),
            dur_ms=duration(rng, 520, 900),
            table=rng.choice(["sessions", "audit_log", "settings"]),
        )
    for ts in spread(rng, start, 1 / 20):
        log.emit(
            ts,
            "ERROR",
            "http",
            "client closed connection before response",
            host=rng.choice(log.hosts),
            req=req_id(rng),
        )
    for ts in spread(rng, start, 1 / 15):
        log.emit(
            ts,
            "INFO",
            "scheduler",
            "job finished",
            host=rng.choice(log.hosts),
            name=rng.choice(SCHEDULED_JOBS),
            dur_ms=duration(rng, 40, 900),
        )


def worker_background(
    log: Log,
    rng: random.Random,
    start: datetime,
    *,
    jobs: list[str],
    per_minute: float,
    override: Callable[[datetime, str], tuple[str, str, dict[str, object]] | None] | None = None,
) -> None:
    """Job lines on a JSON-lines worker: mostly done, some retries, rare failures."""
    for host in log.hosts:
        for minute in range(0, MINUTES, 5):
            ts = start + timedelta(minutes=minute, milliseconds=rng.randrange(60_000))
            log.emit(ts, "INFO", "worker", "heartbeat", host=host, queue_depth=rng.randrange(0, 6))
    for ts in spread(rng, start, per_minute):
        job = rng.choice(jobs)
        host = rng.choice(log.hosts)
        result = override(ts, job) if override else None
        roll = rng.random()
        if result is not None:
            level, msg, fields = result
        elif roll < 0.015:
            level, msg, fields = (
                "WARN",
                "retrying job",
                {"job": job, "attempt": 2, "reason": "timeout"},
            )
        elif roll < 0.018:
            level, msg = "ERROR", "job failed, will retry"
            fields = {"job": job, "reason": rng.choice(WORKER_FAILURES)}
        else:
            level, msg = "INFO", "job done"
            fields = {"job": job, "id": req_id(rng), "dur_ms": duration(rng, 30, 700)}
        log.emit(ts, level, "jobs", msg, host=host, **fields)


Override = Callable[[datetime, str, str], tuple[int, int] | None]


def http_traffic(
    log: Log,
    rng: random.Random,
    start: datetime,
    *,
    routes: list[tuple[str, str]],
    per_minute: float,
    component: str = "http",
    upstreams: dict[str, str] | None = None,
    override: Override | None = None,
) -> None:
    """Access lines (INFO, whatever the status) on an API service or a proxy."""
    clients = ["web-spa", "ios-app", "android-app", "partner-feed"]
    for ts in spread(rng, start, per_minute):
        method, template = rng.choice(routes)
        path = template.format(n=rng.randrange(10_000, 99_999))
        result = override(ts, method, template) if override else None
        if result is None:
            roll = rng.random()
            status = (
                404 if roll < 0.01 else 304 if roll < 0.04 else 201 if method == "POST" else 200
            )
            result = (status, duration(rng, 12, 260))
        status, dur_ms = result
        fields: dict[str, object] = {"status": status, "dur_ms": dur_ms}
        if upstreams is not None:
            fields["upstream"] = upstreams[template]
        fields["req"] = req_id(rng)
        if upstreams is None:
            fields["client"] = rng.choice(clients)
        else:
            fields["ip"] = f"{rng.choice(DOC_NETS)}.{rng.randrange(1, 255)}"
        log.emit(ts, "INFO", component, f"{method} {path}", host=rng.choice(log.hosts), **fields)


def runbook(incident: Incident, title: str, steps: list[str]) -> str:
    lines = [f"> {incident.header('runbook')}", "", f"# Runbook: {title}", ""]
    lines += [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    return "\n".join(lines) + "\n"


def ticket(incident: Incident, title: str, body: list[str], sources: list[str]) -> str:
    lines = [f"> {incident.header('ticket')}", "", f"# {title}", "", *body, ""]
    lines.append(
        "Window to investigate: 00:00 to 06:00 UTC on " + incident.day.strftime("%Y-%m-%d") + "."
    )
    lines.append("Sources: " + ", ".join(sources) + ".")
    return "\n".join(lines) + "\n"


def metrics_rows(
    incident: Incident,
    columns: list[str],
    row: Callable[[int, random.Random], list[str]],
    rng: random.Random,
) -> Metrics:
    metrics = Metrics(incident.incident_id, columns)
    for minute in range(MINUTES):
        metrics.add(incident.day + timedelta(minutes=minute), row(minute, rng))
    return metrics


# -- the six incidents ----------------------------------------------------------------------


def inc_01(rng: random.Random) -> Incident:
    """Expired client certificate toward a payment gateway (dev, easy)."""
    day = datetime(2026, 5, 4, tzinfo=UTC)
    inc = Incident(
        "inc-01",
        "dev",
        "easy",
        "certificate_expiry",
        day,
        "The client certificate that billing-api presents to the payment gateway "
        "(pay-gw.example.net) expired at 03:40 UTC. The renewal job had skipped it (approval "
        "pending), so every TLS handshake to the gateway failed from 03:40 and invoice payments "
        "returned 502.",
        [
            "Renew or reissue the pay-gw-client certificate and reload billing-api",
            "Approve the pending renewal so the cert-renew job rotates the certificate",
            "Alert on client certificates that expire within 14 days",
        ],
        keyword_free=False,
        misleading_first_hypothesis=None,
    )
    expiry = at(day, "03:40")
    edge = Log(inc.incident_id, "edge-proxy.log", "edge-proxy", ["edge-1", "edge-2"])
    billing = Log(
        inc.incident_id, "billing-api.log", "billing-api", ["billing-1", "billing-2", "billing-3"]
    )
    worker = Log(
        inc.incident_id, "invoice-worker.jsonl", "invoice-worker", ["worker-1", "worker-2"]
    )
    inc.logs = [edge, billing, worker]

    routes = [
        ("GET", "/v1/invoices/{n}"),
        ("GET", "/v1/invoices?page=2"),
        ("POST", "/v1/invoices/pay"),
        ("GET", "/v1/customers/{n}"),
        ("GET", "/v1/plans"),
    ]
    upstreams = {template: "billing-api" for _, template in routes}

    def edge_override(ts: datetime, method: str, template: str) -> tuple[int, int] | None:
        if template == "/v1/invoices/pay" and ts >= expiry:
            return 502, duration(rng, 18, 40)
        return None

    http_traffic(
        edge,
        rng,
        day,
        routes=routes,
        per_minute=9,
        component="proxy",
        upstreams=upstreams,
        override=edge_override,
    )
    text_background(edge, rng, day)
    http_traffic(billing, rng, day, routes=routes, per_minute=6)
    text_background(billing, rng, day)
    for ts in spread(rng, day, 2):
        host = rng.choice(billing.hosts)
        if ts < expiry:
            billing.emit(
                ts,
                "INFO",
                "payments",
                "charge ok",
                host=host,
                upstream="pay-gw.example.net",
                dur_ms=duration(rng, 150, 140),
            )
        else:
            billing.emit(
                ts,
                "ERROR",
                "payments",
                "charge failed",
                host=host,
                upstream="pay-gw.example.net",
                status=502,
                reason="tls_handshake_failed",
            )

    def worker_override(ts: datetime, job: str) -> tuple[str, str, dict[str, object]] | None:
        if job == "collect-payment" and ts >= expiry:
            return (
                "ERROR",
                "charge failed",
                {
                    "job": job,
                    "invoice": f"inv-{rng.randrange(10**5, 10**6)}",
                    "reason": "billing-api 502",
                },
            )
        return None

    worker_background(
        worker,
        rng,
        day,
        jobs=["send-invoice", "collect-payment", "render-pdf"],
        per_minute=4,
        override=worker_override,
    )

    keep(
        inc.essential,
        billing.emit(
            at(day, "00:43", 30.836),
            "WARN",
            "tls",
            "client certificate expires soon",
            host="billing-1",
            note="the gateway client certificate expires at 03:40",
            peer="pay-gw.example.net",
            cert="pay-gw-client",
            not_after="2026-05-04T03:40:00Z",
            hours_left="2.9",
        ),
    )
    keep(
        inc.supporting,
        billing.emit(
            at(day, "01:10", 40.6),
            "INFO",
            "scheduler",
            "job finished",
            host="billing-2",
            note="the renewal job skipped this certificate",
            name="cert-renew",
            renewed=0,
            skipped=1,
            cert="pay-gw-client",
            reason="approval_pending",
        ),
    )
    keep(
        inc.essential,
        billing.emit(
            at(day, "03:40", 2.114),
            "ERROR",
            "tls",
            "handshake failed",
            host="billing-3",
            note="first handshake failure: the certificate has expired",
            peer="pay-gw.example.net",
            reason="certificate_expired",
            not_after="2026-05-04T03:40:00Z",
        ),
    )
    keep(
        inc.supporting,
        edge.emit(
            at(day, "03:40", 31.507),
            "INFO",
            "proxy",
            "POST /v1/invoices/pay",
            host="edge-2",
            note="user-facing payment failure",
            status=502,
            dur_ms=21,
            upstream="billing-api",
            req="5a0c11e7",
        ),
    )
    keep(
        inc.supporting,
        worker.emit(
            at(day, "03:41", 12.34),
            "ERROR",
            "jobs",
            "charge failed",
            host="worker-1",
            note="the invoice worker sees the 502s",
            job="collect-payment",
            invoice="inv-402117",
            reason="billing-api 502",
        ),
    )
    keep(
        inc.decoys,
        edge.emit(
            at(day, "02:57", 13.08),
            "ERROR",
            "geoip",
            "database update failed",
            host="edge-1",
            note="GeoIP update failure; payments do not use GeoIP",
            source="geoip-updates.example.org",
            status=404,
        ),
    )
    keep(
        inc.decoys,
        worker.emit(
            at(day, "03:31", 52.602),
            "FATAL",
            "pdf",
            "renderer crashed, restarting",
            host="worker-2",
            note="PDF renderer crash before the incident; it restarts and does not charge",
            exit_code=139,
            signal="SIGSEGV",
        ),
    )
    keep(
        inc.decoys,
        billing.emit(
            at(day, "04:09", 32.92),
            "ERROR",
            "db",
            "replica lag high",
            host="billing-1",
            note="the reporting replica lags; payments use the primary",
            replica="reporting-1",
            lag_s=48,
            used_by="reports",
        ),
    )

    def row(minute: int, rng: random.Random) -> list[str]:
        failing = minute >= 220
        return [
            f"{jitter(rng, 9.2, 11.8) if failing else jitter(rng, 0.1, 0.4):.1f}",
            f"{jitter(rng, 30, 60) if failing else jitter(rng, 180, 260):.0f}",
            f"{jitter(rng, 20, 35):.1f}",
            f"{(minute - 219) * 3 + rng.randrange(0, 4) if failing else rng.randrange(0, 6)}",
        ]

    inc.metrics = metrics_rows(
        inc, ["edge_5xx_pct", "pay_p95_ms", "billing_cpu_pct", "invoice_queue_depth"], row, rng
    )
    keep(inc.supporting, inc.metrics.mark(218, 224, "5xx jumps at 03:40", quote_minute=220))

    inc.diff = Diff(inc.incident_id)
    inc.diff.add(
        "commit 4f1c2a9e (deploy billing-api 2026.05.04-1, 01:30 UTC)",
        "diff --git a/config/billing.yaml b/config/billing.yaml",
        "--- a/config/billing.yaml",
        "+++ b/config/billing.yaml",
        "@@ -12,4 +12,4 @@ invoices:",
        "   pdf:",
        '-    font: "Inter"',
        '+    font: "Source Sans"',
        "     paper: A4",
        '   footer_text: "Thank you for your business"',
    )
    inc.runbook = runbook(
        inc,
        "invoice payments failing",
        [
            "Check the edge-proxy 5xx rate for POST /v1/invoices/pay in metrics.csv.",
            "Check billing-api for failed calls to the payment gateway and their reason.",
            "Check recent deploys of billing-api (deploy.diff).",
            "Check the invoice-worker queue for collect-payment failures.",
            "Escalate to the payment gateway's support if their side is down.",
        ],
    )
    inc.ticket = ticket(
        inc,
        "Alert: invoice payments failing",
        [
            "Fired at 03:52 UTC by edge-proxy: 5xx rate on POST /v1/invoices/pay above 5% "
            "for 10 minutes.",
            'Support reports customers see "Payment could not be completed" when paying '
            "invoices, since about 03:45 UTC.",
        ],
        [log.source for log in inc.logs] + ["metrics.csv", "deploy.diff", "runbook.md"],
    )
    return inc


def inc_02(rng: random.Random) -> Incident:
    """Memory growth after a dependency upgrade, OOM restarts (test, easy)."""
    day = datetime(2026, 6, 9, tzinfo=UTC)
    inc = Incident(
        "inc-02",
        "test",
        "easy",
        "resource_leak",
        day,
        "The 01:00 deploy of catalog-api upgraded imgcodec-sim from 3.1.0 to 3.2.0. After it, "
        "memory on every catalog-api worker grew by about 13 MB a minute until the 2,048 MB "
        "limit, and the supervisor killed and restarted each worker (exit code 137).",
        [
            "Roll back catalog-api to the previous version (imgcodec-sim 3.1.0)",
            "Pin imgcodec-sim to 3.1.0 and redeploy",
            "Raise the memory limit only as a stopgap while the leak is fixed",
        ],
        keyword_free=False,
        misleading_first_hypothesis=None,
    )
    catalog = Log(
        inc.incident_id, "catalog-api.log", "catalog-api", ["catalog-1", "catalog-2", "catalog-3"]
    )
    indexer = Log(inc.incident_id, "search-indexer.jsonl", "search-indexer", ["indexer-1"])
    edge = Log(inc.incident_id, "edge-proxy.log", "edge-proxy", ["edge-1", "edge-2"])
    inc.logs = [catalog, indexer, edge]

    rollout = {
        "catalog-1": at(day, "01:00", 40.2),
        "catalog-2": at(day, "01:08", 12.9),
        "catalog-3": at(day, "01:15", 3.3),
    }
    to_limit = timedelta(minutes=(2048 - 402) / 13)  # 13 MB a minute from 402 MB
    kills = {host: [start + to_limit, start + 2 * to_limit] for host, start in rollout.items()}

    def rss(ts: datetime, host: str) -> int:
        if ts < rollout[host]:
            return 400 + (ts.minute % 7) * 4
        restart = max([rollout[host], *(k for k in kills[host] if k <= ts)])
        return min(2048, 402 + int((ts - restart).total_seconds() / 60 * 13))

    routes = [
        ("GET", "/v2/catalog/items/{n}"),
        ("GET", "/v2/catalog/search?q=lamp"),
        ("GET", "/v2/catalog/categories"),
    ]
    restart_windows = [(k, k + timedelta(seconds=40)) for ks in kills.values() for k in ks]

    def during_restart(ts: datetime) -> bool:
        return any(begin <= ts < end for begin, end in restart_windows)

    def edge_override(ts: datetime, method: str, template: str) -> tuple[int, int] | None:
        return (503, duration(rng, 2, 10)) if during_restart(ts) else None

    http_traffic(catalog, rng, day, routes=routes, per_minute=8)
    text_background(catalog, rng, day, heap_mb=rss)
    http_traffic(
        edge,
        rng,
        day,
        routes=routes,
        per_minute=7,
        component="proxy",
        upstreams={t: "catalog-api" for _, t in routes},
        override=edge_override,
    )
    text_background(edge, rng, day)
    worker_background(
        indexer, rng, day, jobs=["index-delta", "reindex-category", "prune-deleted"], per_minute=3
    )

    for host, start in rollout.items():
        note = "the new version starts with imgcodec-sim 3.2.0" if host == "catalog-1" else None
        mark = catalog.emit(
            start + timedelta(seconds=0.8),
            "INFO",
            "app",
            "started",
            host=host,
            note=note,
            version="2026.06.09-1",
            imgcodec_sim="3.2.0",
            rss_mb=402,
        )
        if mark is not None:
            inc.supporting.append(mark)
    for host, times in kills.items():
        for index, ts in enumerate(times):
            note = "first OOM kill and restart" if (host, index) == ("catalog-1", 0) else None
            mark = catalog.emit(
                ts,
                "WARN",
                "supervisor",
                "worker killed by OOM, restarting",
                host=host,
                note=note,
                exit_code=137,
                rss_mb=2048,
                limit_mb=2048,
            )
            if mark is not None:
                inc.essential.append(mark)
    keep(
        inc.decoys,
        indexer.emit(
            at(day, "02:21", 9.5),
            "ERROR",
            "jobs",
            "shard rebalance failed, will retry",
            host="indexer-1",
            note="search shard rebalance; catalog-api memory is unrelated",
            shard=7,
            cluster="search-a",
        ),
    )
    keep(
        inc.decoys,
        edge.emit(
            at(day, "01:47", 3.2),
            "ERROR",
            "tls",
            "OCSP refresh failed",
            host="edge-2",
            note="OCSP stapling refresh for static assets; the old staple stays valid",
            domain="static.example.com",
            responder="ocsp.example.net",
        ),
    )
    keep(
        inc.decoys,
        catalog.emit(
            at(day, "04:40", 17.71),
            "ERROR",
            "cache",
            "redis command timeout",
            host="catalog-2",
            note="a single cache timeout",
            cmd="GET",
            key="price:1093",
            dur_ms=1003,
        ),
    )

    hosts = list(kills)

    def row(minute: int, rng: random.Random) -> list[str]:
        ts = day + timedelta(minutes=minute, seconds=30)
        average = sum(rss(ts, h) for h in hosts) / len(hosts) + jitter(rng, -6, 6)
        restarts = sum(1 for h in hosts for k in kills[h] if k <= ts)
        growth = average > 900
        restarting = any(
            day + timedelta(minutes=minute) <= k < day + timedelta(minutes=minute + 1)
            for ks in kills.values()
            for k in ks
        )
        return [
            f"{average:.0f}",
            str(restarts),
            f"{jitter(rng, 120, 170) if growth else jitter(rng, 80, 105):.0f}",
            f"{jitter(rng, 4.0, 7.5) if restarting else jitter(rng, 0.1, 0.3):.1f}",
        ]

    inc.metrics = metrics_rows(
        inc,
        ["catalog_rss_mb", "catalog_restarts_total", "catalog_p95_ms", "edge_5xx_pct"],
        row,
        rng,
    )
    keep(
        inc.essential,
        inc.metrics.mark(80, 95, "memory climbs steadily after the 01:00 deploy", quote_minute=90),
    )

    inc.diff = Diff(inc.incident_id)
    inc.diff.add(
        "commit 9d03be17 (deploy catalog-api 2026.06.09-1, 01:00 UTC)",
        "diff --git a/requirements.lock b/requirements.lock",
        "--- a/requirements.lock",
        "+++ b/requirements.lock",
        "@@ -21,4 +21,4 @@",
        " httpkit-sim==5.4.2",
        "-imgcodec-sim==3.1.0",
    )
    keep(
        inc.essential,
        inc.diff.mark("+imgcodec-sim==3.2.0", "the dependency upgrade shipped at 01:00"),
    )
    inc.diff.add(" orjson-sim==3.9.1", " pydantic-sim==2.7.4")
    inc.runbook = runbook(
        inc,
        "catalog-api restarts or slow responses",
        [
            "Check catalog_restarts_total and catalog_rss_mb in metrics.csv.",
            "Check catalog-api for supervisor restarts and their exit codes.",
            "Check recent deploys of catalog-api (deploy.diff), including dependency changes.",
            "Check edge-proxy for 5xx on /v2/catalog during restarts.",
            "Roll back if a deploy correlates with the problem.",
        ],
    )
    inc.ticket = ticket(
        inc,
        "Alert: catalog-api restarting",
        [
            "Fired at 03:22 UTC: catalog-api restarted 3 times in 20 minutes.",
            "edge-proxy shows short bursts of 503 on /v2/catalog.",
        ],
        [log.source for log in inc.logs] + ["metrics.csv", "deploy.diff", "runbook.md"],
    )
    return inc


def inc_03(rng: random.Random) -> Incident:
    """A config value shipped in a deploy: a 30 ms client timeout (dev, medium, keyword-free)."""
    day = datetime(2026, 5, 20, tzinfo=UTC)
    inc = Incident(
        "inc-03",
        "dev",
        "medium",
        "bad_config",
        day,
        "The 02:10 deploy of storefront-api changed cart_client.timeout_ms from 3000 to 30 in "
        "config/storefront.yaml. cart-svc answers in 40 to 60 ms, so storefront-api gave up on "
        "almost every cart call after 30 ms and returned 503.",
        [
            "Roll back storefront-api to 2026.05.20-2",
            "Set cart_client.timeout_ms back to 3000 and redeploy",
            "Add a config check that rejects client timeouts below the downstream p95",
        ],
        keyword_free=True,
        misleading_first_hypothesis=None,
    )
    deploy = at(day, "02:10", 50)
    shop = Log(
        inc.incident_id, "storefront-api.log", "storefront-api", ["shop-1", "shop-2", "shop-3"]
    )
    cart = Log(inc.incident_id, "cart-svc.jsonl", "cart-svc", ["cart-1", "cart-2"])
    inc.logs = [shop, cart]

    routes = [
        ("GET", "/api/v2/products/{n}"),
        ("GET", "/api/v2/cart"),
        ("POST", "/api/v2/cart/items"),
        ("GET", "/api/v2/search?q=chair"),
        ("GET", "/api/v2/users/me"),
    ]
    cart_routes = {"/api/v2/cart", "/api/v2/cart/items"}

    def shop_override(ts: datetime, method: str, template: str) -> tuple[int, int] | None:
        if template in cart_routes and ts >= deploy and rng.random() < 0.96:
            return 503, 30 + rng.randrange(0, 3)
        return None

    http_traffic(shop, rng, day, routes=routes, per_minute=11, override=shop_override)
    text_background(shop, rng, day)

    def cart_override(ts: datetime, job: str) -> tuple[str, str, dict[str, object]] | None:
        dur_ms = duration(rng, 38, 30)
        if ts >= deploy and rng.random() < 0.9:
            return "INFO", "client went away before response", {"path": job, "dur_ms": dur_ms}
        return "INFO", "request finished", {"path": job, "status": 200, "dur_ms": dur_ms}

    worker_background(
        cart,
        rng,
        day,
        jobs=["/v1/cart/items", "/v1/cart", "/v1/cart/totals"],
        per_minute=6,
        override=cart_override,
    )

    keep(
        inc.essential,
        shop.emit(
            at(day, "02:10", 52.48),
            "INFO",
            "config",
            "loaded",
            host="shop-1",
            note="the new config is live: the cart client gives up after 30 ms",
            file="storefront.yaml",
            version="2026.05.20-3",
            **{"cart_client.timeout_ms": 30, "cart_client.retries": 0},
        ),
    )
    keep(
        inc.essential,
        shop.emit(
            at(day, "02:11", 3.117),
            "INFO",
            "http",
            "POST /api/v2/cart/items",
            host="shop-2",
            note="first cart call cut at 30 ms and answered 503",
            status=503,
            dur_ms=31,
            upstream="cart-svc",
            req="c0ffee03",
        ),
    )
    keep(
        inc.supporting,
        cart.emit(
            at(day, "02:11", 3.09),
            "INFO",
            "jobs",
            "client went away before response",
            host="cart-1",
            note="cart-svc answered in 44 ms, after storefront-api had given up",
            path="/v1/cart/items",
            dur_ms=44,
        ),
    )
    keep(
        inc.decoys,
        shop.emit(
            at(day, "01:12", 44.0),
            "ERROR",
            "payments",
            "webhook signature mismatch",
            host="shop-3",
            note="a refund webhook from a test sender; carts are unrelated",
            source="hooks.example.com",
            event="refund.created",
        ),
    )
    keep(
        inc.decoys,
        cart.emit(
            at(day, "03:05", 21.9),
            "FATAL",
            "metrics",
            "exporter crashed, restarting",
            host="cart-2",
            note="the metrics exporter sidecar; cart requests keep being served",
            exit_code=139,
        ),
    )
    keep(
        inc.decoys,
        shop.emit(
            at(day, "04:31", 7.25),
            "ERROR",
            "images",
            "upload to CDN failed",
            host="shop-1",
            note="an oversized product image",
            cdn="cdn.example.net",
            status=413,
            file_mb=31,
        ),
    )

    def row(minute: int, rng: random.Random) -> list[str]:
        broken = minute >= 131
        return [
            f"{jitter(rng, 33, 38) if broken else jitter(rng, 0.1, 0.5):.1f}",
            f"{jitter(rng, 140, 190) if broken else jitter(rng, 160, 230):.0f}",
            f"{jitter(rng, 44, 61):.0f}",
            f"{jitter(rng, 70, 82):.0f}",
        ]

    inc.metrics = metrics_rows(
        inc, ["storefront_5xx_pct", "storefront_p95_ms", "cart_p95_ms", "cart_rps"], row, rng
    )
    keep(
        inc.supporting,
        inc.metrics.mark(
            129, 135, "5xx jumps after the deploy while cart-svc stays fast", quote_minute=131
        ),
    )

    inc.diff = Diff(inc.incident_id)
    inc.diff.add(
        "commit 1b7e44c0 (deploy storefront-api 2026.05.20-3, 02:10 UTC)",
        "diff --git a/config/storefront.yaml b/config/storefront.yaml",
        "--- a/config/storefront.yaml",
        "+++ b/config/storefront.yaml",
        "@@ -30,6 +30,6 @@ cart_client:",
        "   base_url: http://cart-svc.example",
        "-  timeout_ms: 3000",
    )
    keep(
        inc.essential, inc.diff.mark("+  timeout_ms: 30", "the timeout drops from 3000 ms to 30 ms")
    )
    inc.diff.add(
        "   retries: 0",
        " search_client:",
        "-  page_size: 20",
        "+  page_size: 24",
        "   timeout_ms: 800",
    )
    inc.runbook = runbook(
        inc,
        "storefront-api 5xx",
        [
            "Check storefront_5xx_pct in metrics.csv and which routes fail in storefront-api.",
            "Check whether the failing calls wait on cart-svc and how long cart-svc takes.",
            "Check recent deploys of storefront-api, including config files (deploy.diff).",
            "Roll back if a deploy correlates with the errors.",
        ],
    )
    inc.ticket = ticket(
        inc,
        "Alert: storefront-api 5xx",
        [
            "Fired at 02:21 UTC: storefront-api 5xx rate above 5% for 10 minutes.",
            "Customers report that adding items to the cart fails.",
        ],
        [log.source for log in inc.logs] + ["metrics.csv", "deploy.diff", "runbook.md"],
    )
    return inc


def inc_04(rng: random.Random) -> Incident:
    """A slow external dependency while the app is the obvious suspect (test, hard,
    keyword-free)."""
    day = datetime(2026, 7, 2, tzinfo=UTC)
    inc = Incident(
        "inc-04",
        "test",
        "hard",
        "dependency_latency",
        day,
        "The external address-verification API (addr.example.net) slowed down at 03:05, from "
        "about 130 ms to about 4.8 s per call. checkout-api waits for it on every order, so its "
        "worker pool filled and edge-proxy returned 504 after its 5 s timeout. The 02:40 "
        "checkout-api deploy, a logging refactor, is unrelated.",
        [
            "Call the address-verification provider with a short timeout and a fallback",
            "Skip address verification while the provider is slow and flag those orders for review",
            "Contact the address-verification provider and check its status page",
        ],
        keyword_free=True,
        misleading_first_hypothesis="The 02:40 checkout-api deploy (a regression in the app)",
    )
    slow = at(day, "03:05")
    checkout = Log(
        inc.incident_id,
        "checkout-api.log",
        "checkout-api",
        ["checkout-1", "checkout-2", "checkout-3"],
    )
    edge = Log(inc.incident_id, "edge-proxy.log", "edge-proxy", ["edge-1", "edge-2"])
    fraud = Log(inc.incident_id, "fraud-worker.jsonl", "fraud-worker", ["fraud-1"])
    inc.logs = [checkout, edge, fraud]

    routes = [
        ("GET", "/v1/cart/summary"),
        ("POST", "/v1/checkout"),
        ("GET", "/v1/shipping/options"),
        ("GET", "/v1/orders/{n}"),
    ]

    def checkout_override(ts: datetime, method: str, template: str) -> tuple[int, int] | None:
        if template == "/v1/checkout" and ts >= slow:
            return (200, duration(rng, 4700, 400)) if rng.random() < 0.8 else (504, 5000)
        return None

    def edge_override(ts: datetime, method: str, template: str) -> tuple[int, int] | None:
        if template == "/v1/checkout" and ts >= slow + timedelta(minutes=2) and rng.random() < 0.3:
            return 504, 5001
        return None

    http_traffic(checkout, rng, day, routes=routes, per_minute=8, override=checkout_override)
    text_background(checkout, rng, day)
    http_traffic(
        edge,
        rng,
        day,
        routes=routes,
        per_minute=8,
        component="proxy",
        upstreams={t: "checkout-api" for _, t in routes},
        override=edge_override,
    )
    text_background(edge, rng, day)
    worker_background(fraud, rng, day, jobs=["score-order", "refresh-rules"], per_minute=3)
    for ts in spread(rng, day, 2.5):
        dur_ms = duration(rng, 4600, 350) if ts >= slow else duration(rng, 95, 70)
        checkout.emit(
            ts,
            "INFO",
            "addr_client",
            "verify done",
            host=rng.choice(checkout.hosts),
            upstream="addr.example.net",
            dur_ms=dur_ms,
            status=200,
        )

    keep(
        inc.supporting,
        checkout.emit(
            at(day, "02:40", 18.2),
            "INFO",
            "deploy",
            "rollout finished",
            host="checkout-1",
            note="the deploy finished 25 minutes before the latency rose",
            version="2026.07.02-1",
            healthy="3/3",
        ),
    )
    keep(
        inc.essential,
        checkout.emit(
            at(day, "03:05", 7.431),
            "INFO",
            "addr_client",
            "verify done",
            host="checkout-2",
            note="first slow call to the address-verification API",
            upstream="addr.example.net",
            dur_ms=4730,
            status=200,
        ),
    )
    keep(
        inc.supporting,
        checkout.emit(
            at(day, "03:09", 44.05),
            "WARN",
            "http",
            "worker pool full",
            host="checkout-3",
            note="workers are all waiting on the slow calls",
            active=64,
            max=64,
            queued=37,
        ),
    )
    keep(
        inc.supporting,
        edge.emit(
            at(day, "03:07", 12.66),
            "INFO",
            "proxy",
            "POST /v1/checkout",
            host="edge-1",
            note="first 504 at the edge",
            status=504,
            dur_ms=5001,
            upstream="checkout-api",
            req="d15ea5e0",
        ),
    )
    keep(
        inc.decoys,
        fraud.emit(
            at(day, "03:12", 2.8),
            "ERROR",
            "model",
            "model file checksum mismatch, keeping previous model",
            host="fraud-1",
            note="the fraud model update failed; scoring continues on the old model",
            model="fraud-v19",
        ),
    )
    keep(
        inc.decoys,
        edge.emit(
            at(day, "02:51", 30.3),
            "FATAL",
            "waf",
            "rule set reload failed, keeping previous rules",
            host="edge-2",
            note="a WAF rule reload; traffic keeps flowing on the old rules",
            ruleset="r-2026-07-01",
        ),
    )
    keep(
        inc.decoys,
        checkout.emit(
            at(day, "01:33", 8.12),
            "ERROR",
            "coupons",
            "legacy endpoint called",
            host="checkout-1",
            note="a partner still calls a deprecated endpoint",
            client="partner-feed",
            path="/v1/coupons/apply-legacy",
        ),
    )

    def row(minute: int, rng: random.Random) -> list[str]:
        degraded = minute >= 185
        return [
            f"{jitter(rng, 4800, 5000) if degraded else jitter(rng, 260, 340):.0f}",
            f"{jitter(rng, 24, 36):.1f}",
            f"{jitter(rng, 4600, 4950) if degraded else jitter(rng, 110, 150):.0f}",
            f"{jitter(rng, 5.5, 9.0) if minute >= 187 else 0.0:.1f}",
        ]

    inc.metrics = metrics_rows(
        inc, ["checkout_p95_ms", "checkout_cpu_pct", "addr_verify_p95_ms", "edge_504_pct"], row, rng
    )
    keep(
        inc.essential,
        inc.metrics.mark(
            183,
            188,
            "address-verification latency jumps at 03:05 while CPU stays flat",
            quote_minute=185,
        ),
    )
    keep(
        inc.supporting,
        inc.metrics.mark(158, 164, "nothing changes around the 02:40 deploy", quote_minute=160),
    )

    inc.diff = Diff(inc.incident_id)
    inc.diff.add(
        "commit 6ac9f203 (deploy checkout-api 2026.07.02-1, 02:40 UTC)",
        "diff --git a/app/handlers/checkout.py b/app/handlers/checkout.py",
        "--- a/app/handlers/checkout.py",
        "+++ b/app/handlers/checkout.py",
        "@@ -41,5 +41,6 @@ from app.clients import addr_client, payments",
        "-def submit_order(req):",
        '-    log.info("checkout submit", order=req.order_id)',
        "+def submit_checkout(req):",
        '+    log.info("checkout submit order=%s items=%d", req.order_id, len(req.items))',
        '+    span = tracing.start_span("checkout.submit")',
        "     address = addr_client.verify(req.address)",
        "     charge = payments.charge(req.total, req.card_token_ref)",
        "     return save_order(req, address, charge)",
    )
    inc.runbook = runbook(
        inc,
        "slow checkout",
        [
            "Check checkout_p95_ms and checkout_cpu_pct in metrics.csv.",
            "Check recent deploys of checkout-api (deploy.diff) and when they finished.",
            "Check how long checkout-api's calls to its dependencies take.",
            "Check edge-proxy for 504 on POST /v1/checkout.",
            "Roll back only if the timing of a deploy matches the slowdown.",
        ],
    )
    inc.ticket = ticket(
        inc,
        "Alert: slow checkout",
        [
            "Fired at 03:18 UTC by edge-proxy: p95 latency on POST /v1/checkout above 3 s; "
            "some checkouts time out (504).",
            "A checkout-api deploy went out at 02:40 UTC.",
        ],
        [log.source for log in inc.logs] + ["metrics.csv", "deploy.diff", "runbook.md"],
    )
    return inc


def inc_05(rng: random.Random) -> Incident:
    """Connection pool exhaustion after a traffic spike; the database looks guilty (dev, hard)."""
    day = datetime(2026, 6, 23, tzinfo=UTC)
    inc = Incident(
        "inc-05",
        "dev",
        "hard",
        "capacity_exhaustion",
        day,
        "A traffic spike at 03:00 (about 3.3 times normal) made the autoscaler grow orders-api "
        "from 4 to 12 replicas. Each replica opens up to 25 database connections, 300 in total, "
        "but pg-proxy accepts 200 client connections, so the new replicas waited for connections "
        "and requests timed out. The database itself stayed healthy (CPU about 50%).",
        [
            "Lower the per-replica pool size so that replicas times pool size stays under "
            "pg-proxy's max_client_conn",
            "Raise pg-proxy max_client_conn if the database can take the connections",
            "Cap the autoscaler's maximum replicas to what the connection budget allows",
        ],
        keyword_free=False,
        misleading_first_hypothesis="The database (or pg-proxy) is down",
    )
    spike = at(day, "03:00")
    exhausted = at(day, "03:04", 41.25)
    base_hosts = ["orders-1", "orders-2", "orders-3", "orders-4"]
    new_hosts = [f"orders-{n}" for n in range(5, 13)]
    orders = Log(inc.incident_id, "orders-api.log", "orders-api", base_hosts)
    proxy = Log(inc.incident_id, "pg-proxy.log", "pg-proxy", ["pgproxy-1"])
    notify = Log(inc.incident_id, "notify-worker.jsonl", "notify-worker", ["notify-1"])
    inc.logs = [orders, proxy, notify]

    routes = [("GET", "/v1/orders/{n}"), ("POST", "/v1/orders"), ("GET", "/v1/orders?status=open")]
    scaled = at(day, "03:03")
    for ts in spread(rng, day, 4):  # a sample of the access log: 4 lines a minute before the spike
        host = rng.choice(base_hosts + new_hosts if ts >= scaled else base_hosts)
        method, template = rng.choice(routes)
        status, dur_ms = (200, duration(rng, 30, 180))
        if ts >= exhausted and rng.random() < 0.35:
            status, dur_ms = 503, 5000
        orders.emit(
            ts,
            "INFO",
            "http",
            f"{method} {template.format(n=rng.randrange(10**4, 10**5))}",
            host=host,
            status=status,
            dur_ms=dur_ms,
            req=req_id(rng),
        )
    for ts in spread(rng, day, 9 * MINUTES / (MINUTES - 180)):  # 9 more a minute from 03:00
        if ts < spike:
            continue
        host = rng.choice(base_hosts + new_hosts if ts >= scaled else base_hosts)
        method, template = rng.choice(routes)
        status, dur_ms = (200, duration(rng, 30, 400))
        if ts >= exhausted and rng.random() < 0.5:
            status, dur_ms = 503, 5000
        orders.emit(
            ts,
            "INFO",
            "http",
            f"{method} {template.format(n=rng.randrange(10**4, 10**5))}",
            host=host,
            status=status,
            dur_ms=dur_ms,
            req=req_id(rng),
        )
    for ts in spread(rng, day, 0.6):
        if ts >= exhausted:
            orders.emit(
                ts,
                "ERROR",
                "db",
                "could not get a connection",
                host=rng.choice(new_hosts),
                waited_ms=5000,
                pool="orders",
                active=25,
                max=25,
            )
    text_background(orders, rng, day)
    text_background(proxy, rng, day)
    for ts in spread(rng, day, 1):
        clients = 200 if ts >= exhausted else rng.randrange(92, 108)
        proxy.emit(
            ts,
            "INFO",
            "stats",
            "pool stats",
            host="pgproxy-1",
            cl_active=clients,
            sv_active=rng.randrange(40, 60),
            max_client_conn=200,
        )
    worker_background(
        notify, rng, day, jobs=["order-confirmation", "shipping-update"], per_minute=4
    )

    keep(
        inc.essential,
        orders.emit(
            at(day, "03:02", 16.4),
            "INFO",
            "autoscaler",
            "scaled deployment",
            host="orders-1",
            note="the autoscaler triples the replicas after the spike",
            deployment="orders-api",
            replicas_from=4,
            replicas_to=12,
            reason="cpu_target",
        ),
    )
    keep(
        inc.essential,
        proxy.emit(
            exhausted,
            "WARN",
            "pool",
            "client connections at limit, new clients wait",
            host="pgproxy-1",
            note="pg-proxy reaches its client connection limit",
            current=200,
            max_client_conn=200,
        ),
    )
    keep(
        inc.supporting,
        orders.emit(
            at(day, "03:05", 2.07),
            "ERROR",
            "db",
            "could not get a connection",
            host="orders-9",
            note="a new replica cannot get a connection",
            waited_ms=5000,
            pool="orders",
            active=25,
            max=25,
        ),
    )
    keep(
        inc.decoys,
        proxy.emit(
            at(day, "02:48", 11.6),
            "ERROR",
            "replication",
            "standby lag high",
            host="pgproxy-1",
            note="the reporting standby lags; orders-api uses the primary",
            standby="pg-standby-2",
            lag_s=95,
        ),
    )
    keep(
        inc.decoys,
        orders.emit(
            at(day, "03:11", 27.3),
            "ERROR",
            "db",
            "deadlock detected, retrying transaction",
            host="orders-2",
            note="a one-off deadlock on the audit table, retried",
            table="audit_log",
        ),
    )
    keep(
        inc.decoys,
        notify.emit(
            at(day, "03:25", 40.0),
            "FATAL",
            "templates",
            "template cache corrupted, rebuilding",
            host="notify-1",
            note="the email template cache rebuilds; orders are unaffected",
            cache="email-templates",
        ),
    )

    def row(minute: int, rng: random.Random) -> list[str]:
        hot = minute >= 180
        replicas = 12 if minute >= 183 else 4
        clients = (
            200
            if minute >= 184
            else int(jitter(rng, 92, 108))
            if not hot
            else min(200, 100 + (minute - 180) * 30)
        )
        return [
            f"{jitter(rng, 380, 420) if hot else jitter(rng, 110, 130):.0f}",
            str(replicas),
            str(clients),
            f"{jitter(rng, 4000, 5200) if minute >= 185 else jitter(rng, 120, 160):.0f}",
            f"{jitter(rng, 45, 55) if hot else jitter(rng, 30, 40):.1f}",
        ]

    inc.metrics = metrics_rows(
        inc,
        ["orders_rps", "orders_replicas", "pg_client_conns", "orders_p95_ms", "db_cpu_pct"],
        row,
        rng,
    )
    keep(
        inc.essential,
        inc.metrics.mark(
            179,
            186,
            "traffic triples at 03:00, replicas go to 12, client connections hit 200",
            quote_minute=180,
        ),
    )

    inc.diff = Diff(inc.incident_id)
    inc.diff.add(
        "commit e2504d81 (deploy notify-worker 2026.06.22-4, yesterday 18:20 UTC)",
        "diff --git a/templates/shipping_update.txt b/templates/shipping_update.txt",
        "--- a/templates/shipping_update.txt",
        "+++ b/templates/shipping_update.txt",
        "@@ -1,2 +1,2 @@",
        "-Your order {order_id} has shipped.",
        "+Good news: your order {order_id} is on its way.",
        " Track it at https://track.example.com/{tracking_id}",
    )
    inc.runbook = runbook(
        inc,
        "orders-api slow or failing",
        [
            "Check orders_p95_ms and orders_rps in metrics.csv.",
            "Check orders-api for database connection errors.",
            "Check pg-proxy for its connection counts and the database for load.",
            "Check recent deploys (deploy.diff) and autoscaler activity.",
            "Escalate to the database owner if the database is unhealthy.",
        ],
    )
    inc.ticket = ticket(
        inc,
        "Alert: orders-api slow, database errors",
        [
            "Fired at 03:15 UTC: orders-api p95 latency above 4 s for 10 minutes.",
            'orders-api logs "could not get a connection". Is the database down?',
        ],
        [log.source for log in inc.logs] + ["metrics.csv", "deploy.diff", "runbook.md"],
    )
    return inc


def inc_06(rng: random.Random) -> Incident:
    """Disk filling because a log rotation rule changed (test, medium, keyword-free)."""
    day = datetime(2026, 7, 15, tzinfo=UTC)
    inc = Incident(
        "inc-06",
        "test",
        "medium",
        "disk_exhaustion",
        day,
        "The 00:30 deploy changed the logrotate rule for media-api's app.log from size 500M to "
        "size 50G. The hourly rotation stopped from 01:00, app.log grew by about 35 MB a minute on "
        "the 20 GB /data volume it shares with the upload temp files, and the volume filled at "
        "04:41; after that every write failed with ENOSPC and uploads failed.",
        [
            "Restore the logrotate rule to size 500M and rotate app.log now",
            "Free space on /data (compress or move the current app.log)",
            "Alert on /data usage above 80%",
        ],
        keyword_free=True,
        misleading_first_hypothesis=None,
    )
    full_minute = 281  # 52.0% + 0.171% a minute reaches 100% after 281 minutes
    full = day + timedelta(minutes=full_minute)
    media = Log(inc.incident_id, "media-api.log", "media-api", ["media-1", "media-2"])
    upload = Log(inc.incident_id, "upload-worker.jsonl", "upload-worker", ["upload-1", "upload-2"])
    inc.logs = [media, upload]

    def used_pct(minute: int) -> float:
        return min(100.0, 52.0 + 0.171 * minute)

    routes = [("POST", "/v1/uploads"), ("GET", "/v1/media/{n}"), ("GET", "/v1/media/{n}/thumb")]

    def media_override(ts: datetime, method: str, template: str) -> tuple[int, int] | None:
        if template == "/v1/uploads" and ts >= full:
            return 507, duration(rng, 5, 30)
        return None

    http_traffic(media, rng, day, routes=routes, per_minute=10, override=media_override)
    text_background(media, rng, day)

    def upload_override(ts: datetime, job: str) -> tuple[str, str, dict[str, object]] | None:
        if ts >= full and job == "store-original":
            return "ERROR", "store failed", {"job": job, "reason": "no_space", "path": "/data/tmp"}
        return None

    worker_background(
        upload,
        rng,
        day,
        jobs=["store-original", "make-thumbnail", "scan"],
        per_minute=5,
        override=upload_override,
    )
    for minute in range(0, MINUTES, 10):
        for host in media.hosts:
            ts = day + timedelta(minutes=minute, seconds=rng.randrange(5, 50))
            pct = used_pct(minute)
            media.emit(
                ts,
                "INFO",
                "disk",
                "usage",
                host=host,
                mount="/data",
                used_pct=f"{pct:.0f}",
                free_gb=f"{20 * (100 - pct) / 100:.1f}",
            )
    media.emit(
        at(day, "00:00", 1.2),
        "INFO",
        "logrotate",
        "rotated /data/log/media-api/app.log",
        host="media-1",
        size_mb=2112,
        kept=5,
        compressed="true",
    )
    media.emit(
        at(day, "00:00", 1.9),
        "INFO",
        "logrotate",
        "rotated /data/log/media-api/app.log",
        host="media-2",
        size_mb=2098,
        kept=5,
        compressed="true",
    )
    media.emit(
        at(day, "00:30", 4.4),
        "INFO",
        "deploy",
        "config applied",
        host="media-1",
        version="ops-2026.07.15-1",
        files="logrotate.d/media-api",
    )
    for hour in range(1, 6):
        for host in media.hosts:
            ts = day + timedelta(hours=hour, seconds=1 + rng.random())
            note = (
                "the hourly rotation does not run: the new threshold is 50 GB"
                if (hour, host) == (1, "media-1")
                else None
            )
            mark = media.emit(
                ts,
                "INFO",
                "logrotate",
                "/data/log/media-api/app.log not rotated",
                host=host,
                note=note,
                size_mb=35 * 60 * hour + rng.randrange(0, 40),
                threshold_mb=51200,
            )
            if mark is not None:
                inc.essential.append(mark)
    for ts in spread(rng, day, 0.5):
        if ts >= full:
            media.emit(
                ts,
                "ERROR",
                "storage",
                "write failed",
                host=rng.choice(media.hosts),
                path="/data/log/media-api/app.log",
                errno="ENOSPC",
            )
    keep(
        inc.supporting,
        media.emit(
            full + timedelta(seconds=3.5),
            "ERROR",
            "storage",
            "write failed",
            host="media-2",
            note="the volume is full: the first failed write",
            path="/data/log/media-api/app.log",
            errno="ENOSPC",
        ),
    )
    keep(
        inc.decoys,
        media.emit(
            at(day, "02:14", 50.5),
            "ERROR",
            "transcoder",
            "unsupported codec",
            host="media-1",
            note="one user uploaded a file in an unsupported codec",
            upload="u-58213",
            codec="xvid-sim",
        ),
    )
    keep(
        inc.decoys,
        upload.emit(
            at(day, "03:37", 11.1),
            "ERROR",
            "scan",
            "virus scan service unavailable, will retry",
            host="upload-2",
            note="a short scanner outage; scans retry and pass",
            scanner="scan.example.org",
        ),
    )
    keep(
        inc.decoys,
        upload.emit(
            at(day, "04:20", 33.33),
            "FATAL",
            "thumbs",
            "thumbnail cache corrupted, rebuilding",
            host="upload-1",
            note="the thumbnail cache rebuilds before the disk fills",
            cache="thumbs-l1",
        ),
    )

    def row(minute: int, rng: random.Random) -> list[str]:
        ok = minute < full_minute
        return [
            f"{used_pct(minute):.1f}",
            str(35 * minute + rng.randrange(0, 20)),
            f"{jitter(rng, 8, 12) if ok else 0.0:.1f}",
            f"{0.0 if ok else jitter(rng, 8, 12):.1f}",
        ]

    inc.metrics = metrics_rows(
        inc, ["data_used_pct", "app_log_mb", "upload_ok_rps", "upload_fail_rps"], row, rng
    )
    keep(
        inc.essential,
        inc.metrics.mark(
            58,
            64,
            "no drop at 01:00: app.log keeps growing past the hourly rotation",
            quote_minute=61,
        ),
    )
    keep(
        inc.supporting,
        inc.metrics.mark(
            279, 283, "/data reaches 100% at 04:41 and uploads fail", quote_minute=281
        ),
    )

    inc.diff = Diff(inc.incident_id)
    inc.diff.add(
        "commit 70cd1e95 (deploy ops config ops-2026.07.15-1, 00:30 UTC)",
        "diff --git a/logrotate.d/media-api b/logrotate.d/media-api",
        "--- a/logrotate.d/media-api",
        "+++ b/logrotate.d/media-api",
        "@@ -1,7 +1,7 @@",
        " /data/log/media-api/app.log {",
        "     hourly",
        "-    size 500M",
    )
    keep(
        inc.essential,
        inc.diff.mark("+    size 50G", "the rotation threshold goes from 500 MB to 50 GB"),
    )
    inc.diff.add("     rotate 5", "     compress", "     missingok", " }")
    inc.runbook = runbook(
        inc,
        "media uploads failing",
        [
            "Check upload_fail_rps in metrics.csv and the failures in upload-worker.",
            "Check media-api for storage errors and the /data volume usage.",
            "Check logrotate activity on the media-api hosts.",
            "Check recent deploys, including ops config (deploy.diff).",
        ],
    )
    inc.ticket = ticket(
        inc,
        "Alert: media uploads failing",
        [
            "Fired at 04:52 UTC: upload failure rate above 50% for 10 minutes.",
            "upload-worker reports store failures; media-api answers 507 on POST /v1/uploads.",
        ],
        [log.source for log in inc.logs] + ["metrics.csv", "deploy.diff", "runbook.md"],
    )
    return inc


BUILDERS: dict[str, Callable[[random.Random], Incident]] = {
    "inc-01": inc_01,
    "inc-02": inc_02,
    "inc-03": inc_03,
    "inc-04": inc_04,
    "inc-05": inc_05,
    "inc-06": inc_06,
}


# -- rendering --------------------------------------------------------------------------------


def _text(lines: list[str]) -> str:
    return "\n".join(lines) + "\n"


def _lines_of(files: dict[str, str], ref: dict[str, object]) -> list[str]:
    lines = files[str(ref["source_id"])].split("\n")
    return lines[int(ref["line_start"]) - 1 : int(ref["line_end"])]


def build_incident(incident_id: str) -> dict[str, str]:
    """Every file of one incident, relative path -> text."""
    rng = random.Random(f"{SEED}:{incident_id}")
    inc = BUILDERS[incident_id](rng)
    assert inc.category in CATEGORIES and inc.metrics is not None and inc.diff is not None
    files: dict[str, str] = {}
    for log in inc.logs:
        files[log.source] = _text(log.render())
    files["metrics.csv"] = _text(inc.metrics.render())
    files["deploy.diff"] = _text(inc.diff.lines)
    files["runbook.md"] = inc.runbook
    files["ticket.md"] = inc.ticket

    essential = [m.ref() for m in inc.essential]
    keyword_free = not any(
        KEYWORDS.search(line) for ref in essential for line in _lines_of(files, ref)
    )
    if keyword_free != inc.keyword_free:
        raise AssertionError(
            f"{incident_id}: keyword_free_evidence is {keyword_free}, not {inc.keyword_free}"
        )
    log_lines = sum(files[log.source].count("\n") for log in inc.logs)
    if not 5_000 <= log_lines <= 20_000:
        raise AssertionError(f"{incident_id}: {log_lines} log lines, outside 5,000 to 20,000")
    truth = {
        "synthetic": True,
        "note": inc.header("ground truth"),
        "incident_id": incident_id,
        "split": inc.split,
        "difficulty": inc.difficulty,
        "root_cause": inc.root_cause,
        "root_cause_category": inc.category,
        "categories": list(CATEGORIES),
        "essential_evidence": essential,
        "supporting_evidence": [m.ref() for m in inc.supporting],
        "decoys": [m.ref() for m in inc.decoys],
        "acceptable_remediations": inc.remediations,
        "keyword_free_evidence": keyword_free,
        "cause_in_deploy_diff": any(r["source_id"] == "deploy.diff" for r in essential),
        "misleading_first_hypothesis": inc.misleading_first_hypothesis,
        "sources": {
            path: {"lines": text.count("\n"), "committed": not path.startswith("logs/")}
            for path, text in sorted(files.items())
        },
        "log_lines": log_lines,
        "seed": SEED,
    }
    files["ground_truth.json"] = json.dumps(truth, indent=2, ensure_ascii=False) + "\n"
    return files


def build_corpus() -> dict[str, str]:
    """The whole corpus: path under benchmarks/incidents/ -> text, manifest.json included."""
    corpus: dict[str, str] = {}
    for incident_id in BUILDERS:
        for path, text in build_incident(incident_id).items():
            corpus[f"{incident_id}/{path}"] = text
    manifest = {
        "synthetic": True,
        "note": f"SYNTHETIC corpus written by {GENERATOR} (seed {SEED}). {FICTION}",
        "seed": SEED,
        "files": {
            path: {
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "bytes": len(text.encode("utf-8")),
                "lines": text.count("\n"),
                "committed": "/logs/" not in path,
            }
            for path, text in sorted(corpus.items())
        },
    }
    corpus["manifest.json"] = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    return corpus


def write(out_dir: Path, corpus: dict[str, str]) -> None:
    for path, text in corpus.items():
        target = out_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")


def check(out_dir: Path, corpus: dict[str, str]) -> list[str]:
    """Paths whose committed copy or manifest entry differs from a fresh build."""
    problems = []
    manifest_path = out_dir / "manifest.json"
    if (
        not manifest_path.exists()
        or manifest_path.read_text(encoding="utf-8") != corpus["manifest.json"]
    ):
        problems.append("manifest.json")
    for path, text in corpus.items():
        target = out_dir / path
        if "/logs/" in path and not target.exists():
            continue  # gitignored; the manifest comparison covers it
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            problems.append(path)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="compare a fresh build with the files")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    args = parser.parse_args()
    corpus = build_corpus()
    if args.check:
        problems = check(args.out, corpus)
        print(f"differs: {problems}" if problems else f"{len(corpus)} files match the manifest")
        return 1 if problems else 0
    write(args.out, corpus)
    print(f"wrote {len(corpus)} files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
