import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_reading_screen_records_exposure_without_changing_accuracy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LECTURA_DATA_DIR", str(tmp_path / "data"))
    os.environ["LECTURA_DATA_DIR"] = str(tmp_path / "data")
    from app import app

    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Lectura" in page.text
        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert "Mostrar / Sin evaluar" in script.text
        assert "✓ Correcta" in script.text

        started = client.post("/api/sessions", json={"kind": "next"})
        assert started.status_code == 200, started.text
        session = started.json()
        assert session["words"]
        assert len(session["words"]) == 5
        word = session["words"][0]
        recorded = client.post(
            f"/api/sessions/{session['session_id']}/present",
            json={"word_id": word["id"], "set_id": session["set_id"], "result": "exposure", "complete": False},
        )
        assert recorded.status_code == 200, recorded.text

        progress = client.get("/api/progress")
        assert progress.status_code == 200
        summary = progress.json()["summary"]
        assert summary["neutral_exposures"] == 1
        assert summary["correct_readings"] == 0
        assert summary["incorrect_readings"] == 0
        assert summary["total_presentations"] == 1

        today = client.get("/api/today")
        assert today.status_code == 200
        body = today.json()
        assert body["programme_day"] == 1
        assert body["sets"][0]["name"].startswith("Familia")
