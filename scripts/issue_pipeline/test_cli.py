import json
from pathlib import Path

from scripts.issue_pipeline.cli import main


def test_prepare_rejects_a_cycle_without_writing_state(tmp_path: Path, capsys):
    queue = tmp_path / "queue.txt"
    queue.write_text("1\n2\n", encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        json.dumps(
            {
                "issues": [
                    {"number": 1, "title": "a", "body": "Depends on #2"},
                    {"number": 2, "title": "b", "body": "Depends on #1"},
                ]
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    code = main(
        [
            "--state",
            str(state),
            "prepare",
            "--queue-file",
            str(queue),
            "--snapshot",
            str(snapshot),
        ]
    )
    assert code == 2
    assert not state.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "cyclic" in payload["message"]


def test_prepare_next_and_resume_round_trip(tmp_path: Path, capsys):
    queue = tmp_path / "queue.txt"
    queue.write_text("Concurrency: 1\n625\n626\n", encoding="utf-8")
    snapshot = tmp_path / "snap.json"
    snapshot.write_text(
        json.dumps(
            {
                "issues": [
                    {"number": 625, "title": "First", "body": ""},
                    {"number": 626, "title": "Second", "body": "Depends on #625"},
                ]
            }
        ),
        encoding="utf-8",
    )
    state = tmp_path / "state.json"
    assert (
        main(
            [
                "--state",
                str(state),
                "prepare",
                "--queue-file",
                str(queue),
                "--snapshot",
                str(snapshot),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--state", str(state), "next"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["concurrency"] == 1
    assert [item["issue"] for item in payload["actions"]] == ["625"]
    assert main(["--state", str(state), "claim", "--issue", "625", "--action", "implement"]) == 0
    capsys.readouterr()
    assert main(["--state", str(state), "resume"]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert any("625" in note for note in resumed["notes"])
    assert main(["--state", str(state), "next"]) == 0
    again = json.loads(capsys.readouterr().out)
    assert [item["issue"] for item in again["actions"]] == ["625"]
    assert again["actions"][0]["action"] == "implement"
