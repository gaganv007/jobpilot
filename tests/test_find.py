"""The one-command job finder."""
from pathlib import Path

from jobpilot import find


def test_render_html_has_jobs_and_apply_links():
    jobs = [
        {"title": "Machine Learning Engineer", "company": "Acme", "location": "Boston",
         "fit": 92, "track": "AI/ML Engineer", "apply_url": "https://acme/apply/1"},
        {"title": "Data Scientist", "company": "Globex", "location": "Remote",
         "fit": 40, "track": "Data Scientist / Analyst", "url": "https://globex/2"},
    ]
    doc = find.render_html(jobs, "machine learning", "Boston", total_found=50)
    assert "Machine Learning Engineer" in doc
    assert "https://acme/apply/1" in doc          # apply link present
    assert "https://globex/2" in doc              # falls back to url
    assert doc.count('class="apply"') == 2
    assert "never applies for you" in doc


def test_render_html_empty():
    doc = find.render_html([], "nonsense role", "", total_found=0)
    assert "No matching full-time roles" in doc


def test_find_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(find, "gather", lambda q, loc, lim, sen: (
        [{"title": "ML Engineer", "company": "Acme", "location": "Boston",
          "fit": 88, "track": "AI/ML Engineer", "apply_url": "https://a/1"}], 12))
    out = tmp_path / "matches.html"
    path, shown, total = find.find("ml", out_path=out)
    assert path == out and out.exists()
    assert shown == 1 and total == 12
    assert "ML Engineer" in out.read_text(encoding="utf-8")
