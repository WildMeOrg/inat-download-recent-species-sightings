#!/usr/bin/env python3
"""Regression tests for the CSV/HTML export paths.

Each test here pins down a bug that shipped once already:

1. run()'s cross-species deduplication keyed on observation_id alone, which
   silently collapsed every --social-split-observations row back into one.
2. write_csv leaked the internal _has_non_organism_evidence /
   _is_skulls_and_bones flags into the Wildbook import header.
3. write_csv destroyed its input rows (del row['_photo_list']), so a second
   export pass either crashed or produced a photo-less HTML page.
4. json.dumps output was interpolated raw into a <script> block, so a
   "</script>" anywhere in iNaturalist free text broke the review page.
5. The HTML page's maxPhotos was computed from unmerged rows, so merging a
   split observation back together dropped every photo past the first.
"""

import importlib.util
import json
import re
import tempfile
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "inat_downloader",
    str(Path(__file__).parent / "inat-download-new-species-sightings.py"),
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

INTERNAL_FIELDS = (
    "_photo_list",
    "_license_list",
    "_has_non_organism_evidence",
    "_is_skulls_and_bones",
    "_coordinates_obscured",
    "_geoprivacy",
    "_taxon_geoprivacy",
    "_public_positional_accuracy",
)


def _obs(obs_id=111, n_photos=0, place_guess=""):
    return {
        "id": obs_id,
        "taxon": {"name": "Panthera onca", "preferred_common_name": "Jaguar"},
        "observed_on": "2026-07-01",
        "place_guess": place_guess,
        "photos": [
            {"url": "https://example.test/a/square.jpg", "license_code": "cc-by"}
            for _ in range(n_photos)
        ],
    }


def _downloader(tmp, **kwargs):
    d = mod.iNaturalistDownloader(
        output_dir=tmp, days_back=30, species_list=["Panthera onca"], **kwargs
    )
    # Never touch the network; pretend every photo downloaded.
    d.download_photo = lambda url, filename: True
    return d


def test_dedup_runs_before_splitting_so_split_rows_cannot_collapse():
    """The 8c70595 bug, now structurally impossible: dedup only sees whole observations."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=4)], "Panthera onca")
        rows += d.process_observations([_obs(n_photos=4)], "jaguar")  # same taxon, twice
        assert len(rows) == 2

        deduped = d.deduplicate_rows(rows)
        assert len(deduped) == 1, "the same observation survived twice"

        split = mod.split_rows_by_photo(deduped)
        assert len(split) == 4, f"splitting after dedup gave {len(split)} rows, expected 4"
        assert len({r["photo_filenames"] for r in split}) == 4


def test_dedup_still_collapses_true_duplicates():
    """Two species names resolving to the same taxon must not double-emit."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp)
        rows = d.process_observations([_obs(n_photos=2)], "Panthera onca")
        rows += d.process_observations([_obs(n_photos=2)], "jaguar")
        assert len(rows) == 2

        deduped = d.deduplicate_rows(rows)
        assert len(deduped) == 1, (
            f"the same observation appeared twice and dedup kept {len(deduped)} rows"
        )


def test_csv_header_has_no_internal_fields():
    """The Wildbook import CSV must not carry our underscore-prefixed flags."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp)
        rows = d.process_observations([_obs()], "Panthera onca")
        d.write_csv(rows, "out.csv")
        header = (Path(tmp) / "out.csv").read_text(encoding="utf-8").splitlines()[0]
        for field in INTERNAL_FIELDS:
            assert field not in header, f"{field} leaked into the CSV header: {header}"


def test_write_csv_does_not_consume_its_input():
    """Exporting twice, or CSV-then-HTML, must not silently lose the photos."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=False)
        rows = d.process_observations([_obs(n_photos=3)], "Panthera onca")
        for i in range(1, 4):
            (Path(tmp) / "photos" / f"111_{i}.jpg").write_bytes(b"x")

        d.write_csv(rows, "first.csv")

        # Second pass must produce the same three media assets, not crash and
        # not come out empty.
        d.write_csv(rows, "second.csv")
        first = (Path(tmp) / "first.csv").read_text(encoding="utf-8")
        second = (Path(tmp) / "second.csv").read_text(encoding="utf-8")
        assert first == second, "write_csv is not idempotent"
        assert "Encounter.mediaAsset2" in first, "third photo column missing"

        d.write_html(rows, "review.html")
        html = (Path(tmp) / "review.html").read_text(encoding="utf-8")
        assert re.search(r"const maxPhotos = 3;", html), (
            "HTML export lost the photo lists after write_csv ran"
        )


def test_html_survives_script_tag_in_inaturalist_text():
    """A "</script>" in observer-supplied text must not break out of the block."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp)
        hostile = "beach </script><script>alert(1)</script>"
        rows = d.process_observations([_obs(place_guess=hostile)], "Panthera onca")
        d.write_html(rows, "review.html")
        html = (Path(tmp) / "review.html").read_text(encoding="utf-8")

        assert "</script><script>alert(1)</script>" not in html, (
            "raw </script> from iNaturalist text reached the page verbatim"
        )
        # Exactly one script block, and the data still round-trips.
        assert html.count("</script>") == 1, "the data block closed <script> early"
        payload = re.search(r"const observations = (\[.*?\]);\n", html, re.S).group(1)
        assert json.loads(payload)[0]["location"] == hostile, (
            "escaping mangled the value instead of just neutralising the tag"
        )


def test_merged_export_column_count_covers_recombined_photos():
    """Merging split rows back together must keep a column for every photo."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=4)], "Panthera onca")
        for i in range(1, 5):
            (Path(tmp) / "photos" / f"111_{i}.jpg").write_bytes(b"x")
        d.write_html(rows, "review.html")
        html = (Path(tmp) / "review.html").read_text(encoding="utf-8")

        # The browser-side CSV builder must size its mediaAsset columns from the
        # merged photo count, not from the per-row maximum baked in at export.
        assert "function csvColumnCount" in html, (
            "generateCSV still uses the static maxPhotos for its column count, "
            "so merging 4 split rows would drop 3 photos"
        )


def test_both_export_paths_emit_the_same_columns():
    """The CSV and HTML exports must not drift apart.

    They are two independent column lists — one in Python, one in the generated
    JavaScript — and they have already diverged once: write_csv shipped
    _has_non_organism_evidence and _is_skulls_and_bones while the browser export
    did not. Any new column has to be added in both places.
    """
    source = Path(mod.__file__).read_text(encoding="utf-8")
    block = re.search(r"const headers = \[(.*?)\];", source, re.S)
    assert block, "browser-side header list not found"
    browser_columns = re.findall(r"'([^']+)'", block.group(1))

    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp)
        d.write_csv(d.process_observations([_obs()], "Panthera onca"), "out.csv")
        python_columns = (
            (Path(tmp) / "out.csv").read_text(encoding="utf-8").splitlines()[0].split(",")
        )

    assert python_columns == browser_columns, (
        "CSV and HTML exports disagree:\n"
        f"  only in CSV:  {[c for c in python_columns if c not in browser_columns]}\n"
        f"  only in HTML: {[c for c in browser_columns if c not in python_columns]}"
    )


def test_process_observations_always_returns_one_row_per_observation():
    """Splitting is no longer process_observations' job, in either flag mode."""
    for social_split in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            d = _downloader(tmp, social_split=social_split)
            rows = d.process_observations([_obs(n_photos=4)], "Panthera onca")
            assert len(rows) == 1, f"social_split={social_split} gave {len(rows)} rows"
            assert len(rows[0]["_photo_list"]) == 4
            # The column stays empty; the UUID rides along internally until promoted.
            assert rows[0]["Sighting.sightingID"] is None
            assert rows[0]["_sighting_id"]


def test_split_rows_by_photo_expands_eligible_rows():
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=4)], "Panthera onca")
        split = mod.split_rows_by_photo(rows)

        assert len(split) == 4
        assert [len(r["_photo_list"]) for r in split] == [1, 1, 1, 1]
        assert [r["photo_count"] for r in split] == [1, 1, 1, 1]
        # All four are one sighting.
        ids = {r["Sighting.sightingID"] for r in split}
        assert len(ids) == 1 and ids != {None}
        assert ids == {rows[0]["_sighting_id"]}
        # Each row names exactly its own photo.
        assert [r["photo_filenames"] for r in split] == [p for p in rows[0]["_photo_list"]]
        # Unrelated fields survive.
        assert all(r["Encounter.otherCatalogNumbers"] == "iNaturalist:111" for r in split)


def test_split_rows_by_photo_leaves_ineligible_rows_alone():
    """Single-photo rows, and organism-evidence rows, pass straight through."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        single = d.process_observations([_obs(n_photos=1)], "Panthera onca")
        assert mod.split_rows_by_photo(single) == single

        organism = _obs(n_photos=4)
        organism["annotations"] = [{"controlled_attribute_id": 22, "controlled_value_id": 24}]
        rows = d.process_observations([organism], "Panthera onca")
        assert rows[0]["_split_eligible"] is False
        assert mod.split_rows_by_photo(rows) == rows


def test_split_rows_by_photo_is_pure():
    """It must not mutate its input; run() relies on that for the HTML path."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=3)], "Panthera onca")
        before = [dict(r) for r in rows]
        mod.split_rows_by_photo(rows)
        assert rows == before


if __name__ == "__main__":
    import sys

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    print("OK" if not failures else f"{failures} failure(s)")
    sys.exit(1 if failures else 0)
