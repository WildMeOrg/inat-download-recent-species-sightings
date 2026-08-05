#!/usr/bin/env python3
"""Tests for the Flickr export path. No API key and no network required.

Bugs pinned down here:

1. write_csv was a `pass` stub, yet run() returned its path in output_files and
   the MCP server reported it as a produced deliverable. Requesting
   html_review=false downloaded hundreds of photos and produced no CSV at all.
2. resolve_species stripped location keywords by plain substring, turning
   "Indian elephant" into "n elephant".
3. An unparsable Flickr datetaken (including its "0000-00-00 00:00:00"
   sentinel) was replaced with today's date, fabricating sightings.
4. float() on Flickr's coordinate strings raised on an empty value, aborting a
   whole batch and discarding every observation already processed.
"""

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "inat-mcp-server"))

import flickr_tools  # noqa: E402
from flickr_tools import FlickrDownloader, _safe_float  # noqa: E402


def _downloader(tmp_path, **kwargs):
    return FlickrDownloader(
        output_dir=str(tmp_path),
        days_back=30,
        species_list=["Panthera onca"],
        api_key="test-key-not-used",
        **kwargs,
    )


def _row(photo_id="123", **overrides):
    row = {
        "observation_id": f"flickr_{photo_id}",
        "observed_on": "2026-07-01",
        "Encounter.year": 2026,
        "Encounter.month": 7,
        "Encounter.day": 1,
        "scientific_name": "Panthera onca",
        "Encounter.genus": "Panthera",
        "Encounter.specificEpithet": "onca",
        "common_name": "Jaguar",
        "Encounter.decimalLatitude": -16.5,
        "Encounter.decimalLongitude": -56.2,
        "Encounter.verbatimLocality": "Poconé, Mato Grosso",
        "Encounter.sightingRemarks": "seen from a boat",
        "Encounter.locationID": "Mato Grosso",
        "Encounter.livingStatus": "alive",
        "Encounter.submitterID": "public",
        "Encounter.project0.researchProjectName": "Flickr-panthera-onca",
        "Encounter.project0.ownerUsername": None,
        "Sighting.sightingID": f"flickr_sighting_{photo_id}",
        "observer": "someone",
        "quality_grade": "community",
        "url": f"https://www.flickr.com/photos/x/{photo_id}",
        "Encounter.researcherComments": "Source: Flickr",
        "_photo_list": [f"flickr_{photo_id}.jpg"],
        "_license_list": ["CC BY (Attribution)"],
    }
    row.update(overrides)
    return row


def test_write_csv_actually_writes_a_usable_file(tmp_path):
    d = _downloader(tmp_path)
    d.write_csv([_row("123"), _row("456")], "out.csv")

    csv_path = tmp_path / "out.csv"
    assert csv_path.exists(), "write_csv produced no file (it used to be a stub)"

    with open(csv_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 2
    assert rows[0]["observation_id"] == "flickr_123"
    assert rows[0]["Encounter.mediaAsset0"] == "flickr_123.jpg"
    assert rows[0]["Encounter.mediaAsset0.license"] == "CC BY (Attribution)"
    # Wildbook requires new encounters to arrive unapproved; the Flickr export
    # omitted this column entirely while the iNaturalist one emitted it.
    assert rows[0]["Encounter.state"] == "unapproved"


def test_write_csv_omits_internal_fields(tmp_path):
    d = _downloader(tmp_path)
    d.write_csv([_row()], "out.csv")
    header = (tmp_path / "out.csv").read_text(encoding="utf-8").splitlines()[0]
    for field in ("_photo_list", "_license_list"):
        assert field not in header, f"{field} leaked into the CSV header"


def test_write_csv_pads_rows_with_differing_photo_counts(tmp_path):
    d = _downloader(tmp_path)
    two_photos = _row("789", _photo_list=["a.jpg", "b.jpg"],
                      _license_list=["CC0 (Public Domain)", "CC BY (Attribution)"])
    d.write_csv([_row("123"), two_photos], "out.csv")

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    assert rows[0]["Encounter.mediaAsset1"] == ""     # single-photo row padded
    assert rows[1]["Encounter.mediaAsset1"] == "b.jpg"


def test_write_csv_neutralises_spreadsheet_formulas(tmp_path):
    """The browser export has always guarded formulas; write_csv did not.

    Flickr titles and descriptions are user text and reach this CSV verbatim, so
    a value beginning "=", "+", "-", "@", TAB or CR is a live formula the moment
    a biologist opens the file. The guard must leave genuine negative numbers
    alone -- every southern latitude in the file starts with "-".
    """
    d = _downloader(tmp_path)
    d.write_csv([_row(
        "123",
        **{
            "Encounter.verbatimLocality": "-Somewhere odd",
            "Encounter.sightingRemarks": '=HYPERLINK("http://evil")',
            "observer": "@someone",
        },
    )], "out.csv")

    with open(tmp_path / "out.csv", newline="", encoding="utf-8") as fh:
        row = next(csv.DictReader(fh))

    assert row["Encounter.verbatimLocality"] == "'-Somewhere odd"
    assert row["Encounter.sightingRemarks"] == '\'=HYPERLINK("http://evil")'
    assert row["observer"] == "'@someone"
    # Real coordinates stay numeric, and benign values are untouched.
    assert row["Encounter.decimalLatitude"] == "-16.5"
    assert row["Encounter.decimalLongitude"] == "-56.2"
    assert row["scientific_name"] == "Panthera onca"
    assert row["Encounter.mediaAsset0"] == "flickr_123.jpg"


def test_neutralize_formula_matches_the_browser_rule():
    """This module's copy of the rule must not drift from the other four.

    The last two groups are the cases where a plausible Python regex diverges
    from JavaScript while every ASCII case still passes: Python's \\d matches
    all Unicode decimal digits (so re.ASCII is required), and Python's $ also
    matches before a trailing newline (so the pattern must end in \\Z). Either
    omission makes the same cell export one way here and another in the browser.
    """
    for value in ("=1+1", "+1", "-Somewhere odd", "@user", "\tlead", "\rlead", "-16.5."):
        assert flickr_tools.neutralize_formula(value) == "'" + value, value
    for value in ("-16.5", "-56", "0", "3.14", ".5", "-.5", "Poconé", "", "CC0"):
        assert flickr_tools.neutralize_formula(value) == value, value

    for value in ("-٣", "-۳", "-१", "+٣.٤"):
        assert flickr_tools.neutralize_formula(value) == "'" + value, (
            f"{value!r} was treated as a number; re.ASCII is missing, so this "
            "value exports differently here and in the browser"
        )
    for value in ("-16.5\n", "-16.5\n\n"):
        assert flickr_tools.neutralize_formula(value) == "'" + value, (
            f"{value!r} was treated as a number; the pattern ends in $ rather "
            "than \\Z, so this value exports differently here and in the browser"
        )

    assert flickr_tools.neutralize_formula(None) is None
    assert flickr_tools.neutralize_formula(-16.5) == -16.5


def test_safe_float_never_raises_on_api_junk():
    assert _safe_float("-16.5") == -16.5
    assert _safe_float(0) == 0.0
    assert _safe_float("") is None
    assert _safe_float(None) is None
    assert _safe_float("not a number") is None


def test_location_stripping_uses_whole_words():
    """"Indian elephant" must not become "n elephant"."""
    source = Path(flickr_tools.__file__).read_text(encoding="utf-8")
    match = re.search(r"location_keywords = \[(.*?)\]", source, re.S)
    assert match, "location_keywords list not found"
    keywords = re.findall(r"'([a-z]+)'", match.group(1))
    assert "india" in keywords, "fixture no longer exercises the overlap"

    # Reproduce the stripping the way resolve_species now does it.
    query = "indian elephant"
    for keyword in keywords:
        query = re.sub(rf"\b{re.escape(keyword)}\b", "", query)
    assert re.sub(r"\s+", " ", query).strip() == "indian elephant"

    # A genuine trailing place name still gets removed.
    query = "leopard tanzania"
    for keyword in keywords:
        query = re.sub(rf"\b{re.escape(keyword)}\b", "", query)
    assert re.sub(r"\s+", " ", query).strip() == "leopard"


def test_unparsable_datetaken_leaves_the_date_blank():
    """Flickr's "0000-00-00 00:00:00" must not become today."""
    from datetime import datetime

    source = Path(flickr_tools.__file__).read_text(encoding="utf-8")
    date_block = source[source.index("date_taken = photo.get('datetaken')"):]
    date_block = date_block[:date_block.index("# Extract GPS coordinates")]
    assert "datetime.now()" not in date_block, (
        "an unparsable capture date is still being replaced with the current date"
    )

    # And the sentinel really is unparsable, so the branch is reachable.
    try:
        datetime.strptime("0000-00-00 00:00:00", "%Y-%m-%d %H:%M:%S")
        raise AssertionError("expected the sentinel to fail parsing")
    except ValueError:
        pass


def test_both_export_paths_emit_the_same_columns():
    """The Python CSV and the browser CSV must agree, column for column.

    They diverged once already: the browser export omitted Encounter.state,
    which Wildbook needs on every new encounter.
    """
    source = Path(flickr_tools.__file__).read_text(encoding="utf-8")
    header_block = re.search(r"let csv = 'observation_id.*?\\\\n';", source, re.S)
    assert header_block, "browser-side CSV header not found"

    browser_columns = [
        column
        for column in "".join(re.findall(r"'([^']*)'", header_block.group(0)))
        .replace("\\n", "")
        .split(",")
        if column and not column.startswith("Encounter.mediaAsset")
    ]

    assert FlickrDownloader.CSV_FIELDNAMES == browser_columns, (
        "Python and browser Flickr exports disagree:\n"
        f"  only in Python:  {[c for c in FlickrDownloader.CSV_FIELDNAMES if c not in browser_columns]}\n"
        f"  only in browser: {[c for c in browser_columns if c not in FlickrDownloader.CSV_FIELDNAMES]}"
    )


def test_browser_csv_header_and_row_are_aligned():
    """A column added to the header without a matching value shifts every field."""
    source = Path(flickr_tools.__file__).read_text(encoding="utf-8")

    header_block = re.search(r"let csv = 'observation_id.*?\\\\n';", source, re.S).group(0)
    headers = [
        c for c in "".join(re.findall(r"'([^']*)'", header_block)).replace("\\n", "").split(",") if c
    ]

    row_block = re.search(r"const row = \[(.*?)\];", source, re.S).group(1)
    values = [line.strip().rstrip(",") for line in row_block.strip().splitlines() if line.strip()]

    assert len(headers) == len(values), (
        f"{len(headers)} header columns but {len(values)} row values -- "
        "every field after the mismatch lands in the wrong column"
    )
    # Spot-check the column that was missing, by position.
    assert headers[15] == "Encounter.state"
    assert "'unapproved'" in values[15]


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
