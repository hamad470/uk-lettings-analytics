"""Run with:  pytest -q   (rebuilds everything from raw data and checks the outputs)."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pipeline_runs_and_validates():
    # pipeline.py raises if any of its validation checks fail
    subprocess.run([sys.executable, str(ROOT / "src" / "pipeline.py")], check=True)
    data = json.loads((ROOT / "docs" / "data.json").read_text())
    assert all(t["passed"] for t in data["tests"])


def test_metrics_are_sane():
    data = json.loads((ROOT / "docs" / "data.json").read_text())
    for row in data["monthly"]:
        assert 0 <= row["pass_rate"] <= 1
        assert row["median_turnaround_h"] > 0
    funnel = [s["n"] for s in data["funnel"]]
    assert funnel == sorted(funnel, reverse=True)
    m = data["model"]
    assert 0.6 < m["auc"] < 0.95, "AUC outside plausible range - check for leakage or a broken model"
    assert m["train_period"] != m["test_period"]


def test_dashboard_builds():
    subprocess.run([sys.executable, str(ROOT / "src" / "build_dashboard.py")], check=True)
    html = (ROOT / "docs" / "index.html").read_text()
    assert "/*__DATA__*/null" not in html and "Lettings Pulse" in html
