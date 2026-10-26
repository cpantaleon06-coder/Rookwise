import shutil
from pathlib import Path

import feedback_stats

FIXTURES = Path(__file__).parent / "fixtures" / "feedback_runs"


def runs_copy(tmp_path: Path) -> Path:
    runs = tmp_path / "runs"
    shutil.copytree(FIXTURES, runs)
    return runs


def test_counts_per_model():
    stats = feedback_stats.collect(feedback_stats.find_call_files(FIXTURES))
    ultra = stats.by_model["synthetic-ultra"]
    assert (ultra.calls, ultra.attempts, ultra.retries) == (2, 3, 1)
    assert ultra.statuses == {429: 1, 200: 2}
    assert (ultra.length, ultra.repair_calls) == (1, 1)

    lightning = stats.by_model["synthetic-lightning"]
    assert (lightning.calls, lightning.without_attempt_log) == (5, 2)
    assert (lightning.attempts, lightning.retries, lightning.length) == (5, 2, 1)
    assert lightning.statuses == {529: 1, 503: 1, 200: 1, 422: 1, None: 1}
    assert lightning.raised_statuses == {529: 1}

    sup = stats.by_model["synthetic-super"]
    assert (sup.calls, sup.reused, sup.attempts) == (1, 1, 1)


def test_skip_reused_leaves_out_cassette_hits():
    stats = feedback_stats.collect(feedback_stats.find_call_files(FIXTURES), skip_reused=True)
    assert "synthetic-super" not in stats.by_model
    assert stats.skipped_reused == 1


def test_identical_copies_are_read_once(tmp_path):
    runs = runs_copy(tmp_path)
    shutil.copytree(runs / "incidents/inc-x/record", runs / "incidents/inc-x/record.copy")
    stats = feedback_stats.collect(feedback_stats.find_call_files(runs))
    assert len(stats.files) == 2
    assert [c.parent.name for c, _ in stats.copies] == ["record.copy"]
    assert stats.by_model["synthetic-ultra"].calls == 2


def test_runs_glob_selects_folders():
    files = feedback_stats.find_call_files(FIXTURES, "record.run*")
    assert [f.parent.name for f in files] == ["record.run1"]


def test_render_table_and_missing_field_notes():
    stats = feedback_stats.collect(feedback_stats.find_call_files(FIXTURES))
    text = feedback_stats.render(stats, FIXTURES.parent)
    header = "| " + " | ".join(feedback_stats.COLUMNS) + " |"
    assert header in text
    assert (
        "| synthetic-lightning | 5 | 0 | 2 | 5 | 2 | 1 | 0 | 1 | 1 "
        "| 200: 1, 422: 1, 503: 1, 529: 1, none: 1 | 1 | 0 |"
    ) in text
    assert "| **total** | 8 | 1 | 2 | 9 | 3 | 1 | 1 | 1 | 1 |" in text
    assert "`attempt_log` is missing in 2 of 8 calls." in text
    assert "No repair field exists in calls.json" in text
    assert "synthetic-lightning HTTP 529 x1" in text


def test_main_without_files(tmp_path, capsys):
    assert feedback_stats.main(["--runs-dir", str(tmp_path)]) == 1
    assert "no calls.json" in capsys.readouterr().out
