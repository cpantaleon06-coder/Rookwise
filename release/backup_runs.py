"""Zip the gitignored runs/ folder into backups/runs-YYYYMMDD-HHMM.zip.

The archive keeps paths relative to the repository root (`runs/...`, forward slashes).
Its SHA-256 goes beside it in `runs-YYYYMMDD-HHMM.zip.sha256`, in the `sha256sum` format
(`<hex>  <file name>`), so `sha256sum -c` can verify it from inside backups/. Both paths
and the hash are printed. An archive that already exists is never overwritten.

runs/ holds cassettes with prompt text. The backup is local only: backups/ is not in
.gitignore yet, so add it there before running `git add -A`.

Usage:
    python release/backup_runs.py
    python release/backup_runs.py --root PATH --out-dir PATH
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 1024 * 1024


def archive_name(now: dt.datetime) -> str:
    return f"runs-{now:%Y%m%d-%H%M}.zip"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def backup(root: Path, out_dir: Path, now: dt.datetime) -> tuple[Path, Path, str]:
    """Write the archive and its .sha256 file; return (archive, sha256 file, hex digest)."""
    runs = root / "runs"
    if not runs.is_dir():
        raise FileNotFoundError(f"no runs/ folder under {root}")
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / archive_name(now)
    if archive.exists():
        raise FileExistsError(f"{archive} already exists; nothing was written")
    partial = archive.with_name(archive.name + ".partial")
    files = sorted(p for p in runs.rglob("*") if p.is_file())
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, path.relative_to(root).as_posix())
    partial.replace(archive)
    digest = sha256_of(archive)
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="ascii", newline="\n")
    return archive, checksum, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root")
    parser.add_argument("--out-dir", type=Path, help="default: <root>/backups")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    out_dir = (args.out_dir or root / "backups").resolve()
    try:
        archive, checksum, digest = backup(root, out_dir, dt.datetime.now())
    except (FileNotFoundError, FileExistsError) as error:
        print(error)
        return 1
    print(f"archive: {archive}")
    print(f"sha256:  {digest}")
    print(f"sha256 file: {checksum}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
