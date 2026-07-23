#!/usr/bin/env python3
"""Verify the Encounter.otherCatalogNumbers column carries iNaturalist:<id> in both export paths."""

import importlib.util
import tempfile
from pathlib import Path

# The module filename has hyphens, so load it by path.
SPEC = importlib.util.spec_from_file_location(
    "inat_downloader",
    str(Path(__file__).parent / "inat-download-new-species-sightings.py"),
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

FAKE_OBS = {
    "id": 12345678,
    "taxon": {"name": "Panthera onca", "preferred_common_name": "Jaguar"},
    "observed_on": "2026-07-01",
    "photos": [],  # no photos => no network download in process_observations
}


def _make_downloader(tmp):
    return mod.iNaturalistDownloader(
        output_dir=tmp, days_back=30, species_list=["Panthera onca"]
    )


def test_process_observations_sets_other_catalog_numbers():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_downloader(tmp)
        rows = d.process_observations([FAKE_OBS], "Panthera onca")
        assert rows, "expected at least one row"
        assert rows[0]["Encounter.otherCatalogNumbers"] == "iNaturalist:12345678"


def test_csv_header_and_value():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_downloader(tmp)
        rows = d.process_observations([FAKE_OBS], "Panthera onca")
        d.write_csv(rows, "out.csv")
        text = (Path(tmp) / "out.csv").read_text(encoding="utf-8")
        header = text.splitlines()[0]
        assert "Encounter.otherCatalogNumbers" in header, header
        assert "iNaturalist:12345678" in text


def test_html_export_includes_column():
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_downloader(tmp)
        rows = d.process_observations([FAKE_OBS], "Panthera onca")
        d.write_html(rows, "review.html")
        html = (Path(tmp) / "review.html").read_text(encoding="utf-8")
        assert "Encounter.otherCatalogNumbers" in html


def test_write_csv_strips_geoprivacy_fields_without_raising():
    """Regression test: process_observations rows carry four internal
    _-prefixed geoprivacy/accuracy fields (_coordinates_obscured, _geoprivacy,
    _taxon_geoprivacy, _public_positional_accuracy) that are not in the CSV
    fieldnames. write_csv must pop them before handing rows to
    csv.DictWriter, or DictWriter raises ValueError: dict contains fields
    not in fieldnames. If a future refactor drops that cleanup, this test
    should fail loudly instead of the crash only showing up incidentally."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _make_downloader(tmp)
        rows = d.process_observations([FAKE_OBS], "Panthera onca")
        assert rows, "expected at least one row"

        # Sanity-check the fixture actually reproduces the hazard: the raw
        # rows from process_observations must still carry the internal
        # underscore-prefixed fields that write_csv is responsible for
        # stripping.
        geoprivacy_fields = (
            "_coordinates_obscured",
            "_geoprivacy",
            "_taxon_geoprivacy",
            "_public_positional_accuracy",
        )
        for field in geoprivacy_fields:
            assert field in rows[0], f"fixture no longer exercises {field}"

        # This must not raise ValueError: dict contains fields not in fieldnames.
        d.write_csv(rows, "out.csv")

        out_path = Path(tmp) / "out.csv"
        assert out_path.exists(), "write_csv did not produce a CSV file"
        lines = out_path.read_text(encoding="utf-8").splitlines()
        assert lines, "CSV file was written but has no header line"
        header = lines[0]
        for field in geoprivacy_fields:
            assert field not in header, f"{field} leaked into CSV header"


if __name__ == "__main__":
    test_process_observations_sets_other_catalog_numbers()
    test_csv_header_and_value()
    test_html_export_includes_column()
    test_write_csv_strips_geoprivacy_fields_without_raising()
    print("OK")
