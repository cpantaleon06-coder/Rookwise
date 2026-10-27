import json

import check_numbers as cn
import pytest
import results_json as rj
import verify_benchmark as vb
from bench_fixtures import write_results

# Synthetic test split: correct 2/0/1, coverage 0.900/0.200/0.700, cost 0.200/0.400/0.120.
ALL_NUMBERS = "2 of 3, 0 of 3, 1 of 3; coverage 0.900 0.200 0.700; cost 0.200 0.400 0.120"


@pytest.fixture
def results_file(tmp_path):
    root = write_results(tmp_path / "results")
    path = tmp_path / "results.json"
    path.write_text(json.dumps(rj.build(vb.load_runs(root / "runs"))), encoding="utf-8")
    return path


def repo(tmp_path, readme, landing):
    root = tmp_path / "repo"
    (root / "web" / "src" / "pages").mkdir(parents=True)
    (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "web" / "src" / "pages" / "Landing.tsx").write_text(landing, encoding="utf-8")
    return root


def test_expected_strings_test_split_only(results_file):
    results = json.loads(results_file.read_text(encoding="utf-8"))
    values = [e.value for e in cn.expected_strings(results)]
    assert values == [
        "2 of 3",
        "0 of 3",
        "1 of 3",
        "0.900",
        "0.200",
        "0.700",
        "0.200",
        "0.400",
        "0.120",
    ]


def test_all_found(tmp_path, results_file, capsys):
    root = repo(tmp_path, ALL_NUMBERS, f"<p>{ALL_NUMBERS}</p>")
    assert cn.main(["--results", str(results_file), "--root", str(root)]) == 0
    assert "all test-split numbers found" in capsys.readouterr().out


def test_missing_reported_and_files_unchanged(tmp_path, results_file, capsys):
    landing = "{ correct: 2 } <span>of 3 correct</span> 0.900 0.200 0.700 0.400 0.120"
    root = repo(tmp_path, "| (a) hierarchy | TBD |", landing)
    paths = [root / "README.md", root / "web" / "src" / "pages" / "Landing.tsx"]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
    assert cn.main(["--results", str(results_file), "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "web/src/pages/Landing.tsx: '2 of 3'" in out
    assert "README.md: '0.120'" in out
    assert "web/src/pages/Landing.tsx: '0.200'" not in out
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths] == before


def test_missing_target_file(tmp_path, results_file, capsys):
    root = repo(tmp_path, ALL_NUMBERS, "")
    (root / "web" / "src" / "pages" / "Landing.tsx").unlink()
    assert cn.main(["--results", str(results_file), "--root", str(root)]) == 1
    assert "note: web/src/pages/Landing.tsx not found" in capsys.readouterr().out


def test_missing_results_file(tmp_path):
    assert cn.main(["--results", str(tmp_path / "none.json"), "--root", str(tmp_path)]) == 1
