#!/usr/bin/env python3
"""Deterministic tests for the YouTube scoring and date-extraction helpers.

These need no API key and no network. Each one pins down a bug that silently
distorted the exported dataset:

1. Keyword lists were matched with plain substring `in`, so "ai" hit "thai" and
   "mar" hit "marine". A genuine Koh Tao whale-shark dive took the -60
   AI-generated-content penalty and dropped below the >90 inclusion gate.
2. Date regexes were unanchored and unvalidated, so "1080-30-60fps" became
   Encounter.year=1080 / month=30 / day=60 in the Wildbook CSV.
3. "dec" was missing from the month alternations, so December sightings never
   hit the fast path.
4. Untrusted video text was interpolated into the HTML report unescaped.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "inat-mcp-server"))

import youtube_tools as yt  # noqa: E402


def _video(title, description="", published_at="2025-11-08T00:21:50Z", **extra):
    video = {
        "video_id": "abc123XYZ_-",
        "title": title,
        "description": description,
        "channel_title": "Some Channel",
        "published_at": published_at,
    }
    video.update(extra)
    return video


# --- keyword matching -------------------------------------------------------

def test_thai_is_not_matched_as_ai():
    assert not yt._matches_any_word("whale shark thai diving koh tao similan", ["ai"])


def test_genuine_ai_mention_is_matched():
    assert yt._matches_any_word("Made with AI tools", ["ai"])


def test_marine_is_not_matched_as_mar():
    assert not yt._matches_any_word("marine life at the reef", ["mar"])


def test_month_abbreviation_still_matches():
    assert yt._matches_any_word("filmed in Mar 2025", ["mar"])


def test_thailand_dive_video_survives_the_confidence_gate():
    """The regression this all existed for: a real Thai dive must not read as AI."""
    video = _video(
        "Thai diving trip - whale shark encounter at Koh Tao",
        "We went scuba diving in Thailand and saw a whale shark on the reef.",
    )
    result = yt.evaluate_wild_sighting_likelihood(video)
    assert "AI-generated or staged content" not in result["reasons"], result["reasons"]
    assert result["score"] > 90, f"score {result['score']} would exclude a real sighting"


# --- date extraction --------------------------------------------------------

def test_frame_rate_is_not_read_as_a_date():
    assert yt.extract_observation_date(_video("filmed at 1080-30-60fps whale shark")) == ""


def test_implausible_month_is_rejected():
    assert yt.extract_observation_date(_video("gopro hero 2023-45 whale shark")) == ""


def test_real_iso_date_is_extracted():
    assert yt.extract_observation_date(_video("Whale shark on 2025-11-07")) == "2025-11-07"


def test_real_year_month_is_extracted():
    assert yt.extract_observation_date(_video("Whale sharks in 2025-10")) == "2025-10"


def test_plausibility_guard():
    assert yt._is_plausible_date("2025", "11", "07")
    assert yt._is_plausible_date("2025", "10")
    assert not yt._is_plausible_date("1080", "30", "60")
    assert not yt._is_plausible_date("2023", "45")
    assert not yt._is_plausible_date("2025", "02", "30")  # Feb 30 does not exist
    assert not yt._is_plausible_date("abcd", "11", "07")


def test_december_is_in_the_month_alternation():
    """'dec' was missing while every other abbreviation was present."""
    import re
    months = [
        line for line in Path(yt.__file__).read_text(encoding="utf-8").splitlines()
        if "jan|feb|mar" in line
    ]
    assert months, "month alternation patterns not found"
    for line in months:
        assert re.search(r"\bdec\b\|", line) or "|dec|" in line, line


# --- HTML report escaping ---------------------------------------------------

def test_report_escapes_untrusted_video_text(tmp_path):
    hostile = _video(
        'Whale shark scuba diving at Ningaloo reef <img src=x onerror="alert(1)">'
        " </script><script>alert(2)</script>",
        "whale shark while scuba diving on the reef in Australia"
        " </script><script>alert(3)</script>",
        channel_title="Evil <script>alert(4)</script>",
        url="javascript:alert(5)",
    )
    # Confirm the fixture actually reaches the report rather than being filtered.
    assert yt.evaluate_wild_sighting_likelihood(hostile)["score"] > 90

    path = yt.generate_html_report([hostile], str(tmp_path / "report.html"),
                                   {"species": "whale shark"})
    page = Path(path).read_text(encoding="utf-8")

    assert 'class="video-card"' in page, "the fixture video was filtered out"
    for payload in ("<script>alert(2)", "<script>alert(3)", "<script>alert(4)",
                    'onerror="alert(1)"'):
        assert payload not in page, f"{payload} reached the page unescaped"
    assert "&lt;img src=x" in page, "title was not HTML-escaped"

    # A javascript: URL must not become a live href.
    import re
    hrefs = re.findall(r'<strong>URL:</strong> <a href="([^"]*)"', page)
    assert hrefs and all(not h.startswith("javascript:") for h in hrefs), hrefs


def test_video_id_is_validated_before_reaching_the_iframe(tmp_path):
    hostile = _video(
        "Whale shark scuba diving at Ningaloo reef",
        "whale shark while scuba diving on the reef in Australia",
        video_id='" onload="alert(1)',
    )
    path = yt.generate_html_report([hostile], str(tmp_path / "report.html"),
                                  {"species": "whale shark"})
    page = Path(path).read_text(encoding="utf-8")
    # The id is dropped rather than escaped, so it cannot break out of the
    # src attribute; the embed is left empty.
    assert 'onload="alert(1)' not in page
    assert 'src="https://www.youtube.com/embed/"' in page


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
