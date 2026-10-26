import datetime as dt
import hashlib
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import backup_runs
import pytest

SCRIPT_PS1 = Path(__file__).resolve().parent.parent / "backup_runs.ps1"
NOW = dt.datetime(2026, 10, 25, 9, 7)


def make_root(tmp_path: Path) -> Path:
    (tmp_path / "runs" / "sub").mkdir(parents=True)
    (tmp_path / "runs" / "a.json").write_text('{"synthetic": true}\n', encoding="utf-8")
    (tmp_path / "runs" / "sub" / "b.txt").write_bytes(b"synthetic\n" * 100)
    return tmp_path


def test_backup_writes_zip_and_sha256(tmp_path):
    root = make_root(tmp_path)
    archive, checksum, digest = backup_runs.backup(root, root / "backups", NOW)
    assert archive == root / "backups" / "runs-20261025-0907.zip"
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["runs/a.json", "runs/sub/b.txt"]
        assert zf.read("runs/sub/b.txt") == b"synthetic\n" * 100
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert checksum.read_bytes() == f"{digest}  runs-20261025-0907.zip\n".encode("ascii")
    assert not list((root / "backups").glob("*.partial"))


def test_backup_never_overwrites(tmp_path):
    root = make_root(tmp_path)
    backup_runs.backup(root, root / "backups", NOW)
    with pytest.raises(FileExistsError):
        backup_runs.backup(root, root / "backups", NOW)


def test_main_without_runs(tmp_path, capsys):
    assert backup_runs.main(["--root", str(tmp_path)]) == 1
    assert "no runs/ folder" in capsys.readouterr().out
    assert not (tmp_path / "backups").exists()


@pytest.mark.skipif(shutil.which("powershell") is None, reason="needs Windows PowerShell")
def test_powershell_script_matches(tmp_path):
    root = make_root(tmp_path)
    done = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT_PS1),
            "-Root",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    archive = Path(re.search(r"archive: (.+)", done.stdout).group(1).strip())
    digest = re.search(r"sha256:\s+([0-9a-f]{64})", done.stdout).group(1)
    assert archive.parent == root / "backups"
    assert re.fullmatch(r"runs-\d{8}-\d{4}\.zip", archive.name)
    with zipfile.ZipFile(archive) as zf:
        assert sorted(zf.namelist()) == ["runs/a.json", "runs/sub/b.txt"]
    assert digest == hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = archive.with_name(archive.name + ".sha256")
    assert checksum.read_bytes() == f"{digest}  {archive.name}\n".encode("ascii")
