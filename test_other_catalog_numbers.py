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


if __name__ == "__main__":
    test_process_observations_sets_other_catalog_numbers()
    test_csv_header_and_value()
    test_html_export_includes_column()
    print("OK")
