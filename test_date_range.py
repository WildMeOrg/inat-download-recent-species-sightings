#!/usr/bin/env python3
"""Tests for explicit --start-date / --end-date windows.

`--days N` can only express a window ending *now*, so a backfill of a closed
historical range (say 2020-12-31 to 2025-06-20) was impossible: the nearest
approximation dragged in every observation between the intended end date and
today, with nothing in the review page to distinguish them.

iNaturalist's `d1`/`d2` parameters already take explicit dates, so these tests
pin the plumbing that exposes them, and pin that `--days` still behaves exactly
as before for every existing caller.
"""

import importlib.util
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "inat_downloader",
    str(Path(__file__).parent / "inat-download-new-species-sightings.py"),
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def _downloader(tmp, **kwargs):
    return mod.iNaturalistDownloader(
        output_dir=tmp, days_back=30, species_list=["Phycodurus eques"], **kwargs
    )


def test_explicit_range_is_used_verbatim():
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, start_date="2020-12-31", end_date="2025-06-20")
        assert d.get_date_range() == ("2020-12-31", "2025-06-20")


def test_days_back_still_ends_today_when_no_range_given():
    """Every existing caller must be unaffected."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp)
        start, end = d.get_date_range()
        today = datetime.now()
        assert end == today.strftime("%Y-%m-%d")
        assert start == (today - timedelta(days=30)).strftime("%Y-%m-%d")


def test_start_date_alone_ends_today():
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, start_date="2024-01-01")
        start, end = d.get_date_range()
        assert start == "2024-01-01"
        assert end == datetime.now().strftime("%Y-%m-%d")


def test_end_date_alone_still_spans_days_back_before_it():
    """An end date without a start must not silently become 'everything ever'."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, end_date="2025-06-20")
        start, end = d.get_date_range()
        assert end == "2025-06-20"
        expected = (datetime.strptime("2025-06-20", "%Y-%m-%d")
                    - timedelta(days=30)).strftime("%Y-%m-%d")
        assert start == expected, "start should be days_back before the end date"


def test_the_dates_reach_the_api_query():
    """d1/d2 are what actually bound the search; pin that they carry through."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, start_date="2020-12-31", end_date="2025-06-20")
        captured = {}

        def fake_get_json(url):
            captured["url"] = url
            return {"results": [], "total_results": 0}

        d._get_json = fake_get_json
        d.get_observations(49105)

        assert "d1=2020-12-31" in captured["url"], captured["url"]
        assert "d2=2025-06-20" in captured["url"], captured["url"]


@pytest.mark.parametrize("bad", ["2020-13-01", "31-12-2020", "2020/12/31", "yesterday", ""])
def test_malformed_dates_are_rejected_at_construction(bad):
    """Fail loudly at startup, not with an empty result set after a long run."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            _downloader(tmp, start_date=bad)


def test_inverted_range_is_rejected():
    """An end before the start silently returns nothing from the API."""
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(ValueError):
            _downloader(tmp, start_date="2025-06-20", end_date="2020-12-31")


def test_equal_start_and_end_is_allowed():
    """A single-day window is legitimate; d1 == d2 is inclusive at the API."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, start_date="2024-05-01", end_date="2024-05-01")
        assert d.get_date_range() == ("2024-05-01", "2024-05-01")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
