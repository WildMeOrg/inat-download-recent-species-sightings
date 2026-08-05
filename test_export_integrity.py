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

import ast
import copy
import csv
import importlib.util
import io
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
    "_sighting_id",
    "_split_eligible",
    "_gif_frames_extracted",
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


def test_dedup_keeps_the_row_with_every_photo_when_the_passes_disagree():
    """Two passes over one observation need not agree on its photo list.

    Two species names resolving to one taxon is the case deduplication exists
    for; one transient photo-download failure is all it takes for the two passes
    to see different media. A composite (observation_id, photos) key then treats
    them as different rows and BOTH survive, so Wildbook gets two Encounters
    with the same Encounter.otherCatalogNumbers, sharing photos that self-match
    -- a fabricated resight of one animal at one instant. With the split flag it
    is worse: 3 photos become 5 Encounters across 2 Sightings.

    Deduplication must therefore key on observation_id alone, and keep the
    complete row rather than whichever arrived first.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)

        # Pass 1: photo 2 fails to download. Pass 2: everything succeeds.
        d.download_photo = lambda url, filename: not filename.endswith("_2.jpg")
        rows = d.process_observations([_obs(n_photos=3)], "Panthera onca")
        d.download_photo = lambda url, filename: True
        rows += d.process_observations([_obs(n_photos=3)], "jaguar")

        assert [len(r["_photo_list"]) for r in rows] == [2, 3], "fixture setup sanity check"

        deduped = d.deduplicate_rows(rows)
        assert len(deduped) == 1, (
            f"observation 111 survived {len(deduped)} times, so Wildbook would get "
            "that many Encounters for one observation"
        )
        assert deduped[0]["_photo_list"] == ["111_1.jpg", "111_2.jpg", "111_3.jpg"], (
            "dedup kept the row that lost a photo to a failed download"
        )

        # The CSV consequence: one Encounter, and no photo attached twice.
        d.write_csv(deduped, "out.csv")
        with open(Path(tmp) / "out.csv", encoding="utf-8", newline="") as f:
            csv_rows = list(csv.reader(f))
        assert len(csv_rows) == 2, "more than one CSV row for a single observation"
        catalog = csv_rows[0].index("Encounter.otherCatalogNumbers")
        assert csv_rows[1][catalog] == "iNaturalist:111"

        # And with the flag: 3 photos, 3 Encounters, 1 Sighting -- not 5 and 2.
        split = mod.split_rows_by_photo(deduped)
        assert len(split) == 3
        assert len({r["Sighting.sightingID"] for r in split}) == 1
        assert sorted(r["photo_filenames"] for r in split) == [
            "111_1.jpg", "111_2.jpg", "111_3.jpg"
        ], "a photo was attached to more than one Encounter"


def test_download_photo_retries_a_transient_failure():
    """fetch_json retries; download_photo did not, so one blip dropped a photo.

    A dropped photo is not merely a missing image: it is what makes two passes
    over the same observation disagree about its media, which is the trigger for
    the duplicate-Encounter case above.
    """
    with tempfile.TemporaryDirectory() as tmp:
        # rate_limit=0 so the backoff sleep is instant.
        d = _downloader(tmp, rate_limit=0)
        del d.download_photo          # drop the stub; exercise the real method

        attempts = []

        def fake_urlopen(url, timeout=None):
            attempts.append(url)
            if len(attempts) == 1:
                raise OSError("connection reset by peer")
            # BytesIO is both a readable file object and a context manager,
            # which is all `with urlopen(...) as response` needs here.
            return io.BytesIO(b"jpeg-bytes")

        original = mod.urllib.request.urlopen
        mod.urllib.request.urlopen = fake_urlopen
        try:
            assert d.download_photo("https://example.test/p.jpg", "111_1.jpg") is True, (
                "a single transient failure still loses the photo"
            )
        finally:
            mod.urllib.request.urlopen = original

        assert len(attempts) == 2, f"expected one retry, made {len(attempts)} attempts"
        assert (Path(tmp) / "photos" / "111_1.jpg").exists()
        assert not list((Path(tmp) / "photos").glob("*.part")), "a .part file was left behind"


def test_gif_frames_are_not_split_into_one_encounter_each():
    """An animated GIF is ONE iNaturalist photo, however many files it becomes.

    extract_gif_frames turns it into N JPEGs inside photo_filenames, and both
    _split_eligible and the review page's Split button count files -- so a
    30-frame GIF would become 30 Encounters of the same animal in the same
    second, 29 of them guaranteed self-matches for Wildbook's ID pipeline.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        gif = _obs(n_photos=1)
        gif["photos"][0]["url"] = "https://example.test/a/square.gif"
        d.extract_gif_frames = lambda path: [
            f"{path.stem}_frame{i}.jpg" for i in range(3)
        ]

        rows = d.process_observations([gif], "Panthera onca")
        assert rows[0]["_photo_list"] == [
            "111_1_frame0.jpg", "111_1_frame1.jpg", "111_1_frame2.jpg"
        ], "fixture setup sanity check: one photo must have become three files"
        assert rows[0]["_gif_frames_extracted"] is True
        assert rows[0]["_split_eligible"] is False, (
            "frames of one GIF were offered up as separate individuals"
        )

        split = mod.split_rows_by_photo(rows)
        assert len(split) == 1, f"the GIF's frames became {len(split)} Encounters"
        assert split[0]["photo_count"] == 3, "the frames must stay on the one Encounter"

        # The review page must not offer the button either.
        d.write_html(rows, "review.html")
        entry = _payload((Path(tmp) / "review.html").read_text(encoding="utf-8"))[0]
        assert entry["can_split"] is False
        assert entry["initially_split"] is False

        # An ordinary multi-photo observation is unaffected.
        plain = d.process_observations([_obs(obs_id=222, n_photos=3)], "Panthera onca")
        assert plain[0]["_gif_frames_extracted"] is False
        assert plain[0]["_split_eligible"] is True
        d.write_html(plain, "plain.html")
        plain_entry = _payload((Path(tmp) / "plain.html").read_text(encoding="utf-8"))[0]
        assert plain_entry["can_split"] is True


def test_csv_neutralises_spreadsheet_formulas_in_free_text():
    """iNaturalist free text lands in a file biologists open in Excel.

    Both browser exporters have prefixed an apostrophe to formula-leading values
    since before this branch; neither Python writer did, so the same locality
    exported as `-Somewhere odd` from the direct CSV and `'-Somewhere odd` from
    the review page. Genuine negative numbers -- southern latitudes, western
    longitudes -- must stay untouched.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp)
        hostile = _obs(place_guess="-Somewhere odd")
        hostile["location"] = "-16.5,-56.2"
        hostile["taxon"]["preferred_common_name"] = "=HYPERLINK(\"http://evil\")"
        hostile["user"] = {"login": "@someone"}
        rows = d.process_observations([hostile], "Panthera onca")
        d.write_csv(rows, "out.csv")

        with open(Path(tmp) / "out.csv", encoding="utf-8", newline="") as f:
            record = dict(zip(*list(csv.reader(f))[:2]))

        assert record["Encounter.verbatimLocality"] == "'-Somewhere odd"
        assert record["common_name"] == "'=HYPERLINK(\"http://evil\")"
        assert record["observer"] == "'@someone"
        # Real coordinates are numbers, not text.
        assert record["Encounter.decimalLatitude"] == "-16.5"
        assert record["Encounter.decimalLongitude"] == "-56.2"
        # And a benign value gains nothing.
        assert record["scientific_name"] == "Panthera onca"
        assert record["observation_id"] == "111"


def test_neutralize_formula_matches_the_browser_rule():
    """The rule is written out four times (two Python, two JavaScript).

    Pinning the boundary cases here means the Python copies cannot drift from
    the documented rule silently -- particularly the numeric exemption, which is
    the only thing keeping every southern latitude out of quotes.
    """
    for value in ("=1+1", "+1", "-Somewhere odd", "@user", "\tlead", "\rlead", "-16.5."):
        assert mod.neutralize_formula(value) == "'" + value, value
    for value in ("-16.5", "-56", "0", "3.14", ".5", "-.5", "Pantanal", "", "cc-by"):
        assert mod.neutralize_formula(value) == value, value
    # Non-strings come back untouched, so benign output is byte-identical.
    assert mod.neutralize_formula(None) is None
    assert mod.neutralize_formula(-16.5) == -16.5
    assert mod.neutralize_formula(111) == 111


def _mcp_download_handler():
    """The MCP server's own copy of run()'s orchestration, as an AST.

    Parsed rather than imported: the `mcp` package is not a test dependency, and
    server.py imports it at module scope. ast.parse needs neither.
    """
    source = (Path(__file__).parent / "inat-mcp-server" / "server.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "write_csv"
                and "inat_observations_" in ast.dump(node)
            ):
                return node
    raise AssertionError("no MCP handler writing the iNaturalist CSV was found")


def test_the_mcp_server_applies_the_same_post_processing_as_the_cli():
    """server.py duplicates run()'s orchestration and must not fall behind it.

    Splitting used to happen inside process_observations, so the MCP tool got it
    for free. Moving splitting to a separate pass on the direct-CSV path left
    the MCP tool advertising a social_split argument that did nothing at all --
    a silently disabled feature, which is worse than a missing one. The same
    copy also never deduplicated, so two species names resolving to one taxon
    produced duplicate Encounters there while the CLI dropped them.
    """
    handler = _mcp_download_handler()

    called = {
        node.func.id
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "deduplicate_rows" in called, (
        "the MCP download tool never deduplicates, so one observation reached "
        "Wildbook once per species alias that resolved to it"
    )
    assert "split_rows_by_photo" in called, (
        "the MCP download tool's social_split argument is a no-op: splitting is "
        "no longer done by process_observations and nothing else applies it"
    )

    # And the split is conditional, not unconditional: it must be gated on the
    # tool's social_split argument exactly as run() gates it on self.social_split.
    guarded = any(
        "social_split" in ast.dump(branch.test)
        and "split_rows_by_photo" in ast.dump(ast.Module(body=branch.body, type_ignores=[]))
        for branch in ast.walk(handler)
        if isinstance(branch, ast.If)
    )
    assert guarded, "split_rows_by_photo is applied without checking social_split"


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
    """Single-photo rows, and organism-evidence rows, are not expanded into
    multiple rows -- but split_rows_by_photo only ever runs when social_split
    is on, so they still get their Sighting.sightingID promoted, same as an
    eligible row would (see the lone-row regression test below)."""

    def _same_except_sighting_id(actual, original):
        keys = [k for k in original if k != "Sighting.sightingID"]
        return {k: actual[k] for k in keys} == {k: original[k] for k in keys}

    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        single = d.process_observations([_obs(n_photos=1)], "Panthera onca")
        split_single = mod.split_rows_by_photo(single)
        assert len(split_single) == 1
        assert split_single[0]["Sighting.sightingID"] == single[0]["_sighting_id"]
        assert _same_except_sighting_id(split_single[0], single[0])

        organism = _obs(n_photos=4)
        organism["annotations"] = [{"controlled_attribute_id": 22, "controlled_value_id": 24}]
        rows = d.process_observations([organism], "Panthera onca")
        assert rows[0]["_split_eligible"] is False
        split_organism = mod.split_rows_by_photo(rows)
        assert len(split_organism) == 1
        assert split_organism[0]["Sighting.sightingID"] == rows[0]["_sighting_id"]
        assert _same_except_sighting_id(split_organism[0], rows[0])


def test_split_rows_by_photo_promotes_sighting_id_for_lone_row():
    """Regression test: a lone row in a --social-split-observations run must
    keep its Sighting.sightingID.

    split_rows_by_photo is only called when social_split is on, so a row that
    has nothing to split (one photo, or organism evidence) must still come out
    with a promoted, non-empty sighting ID -- otherwise a single-photo
    observation that used to produce a one-encounter Sighting in Wildbook
    would silently lose it the moment --social-split-observations is passed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=1)], "Panthera onca")
        split = mod.split_rows_by_photo(rows)

        assert len(split) == 1
        assert split[0]["Sighting.sightingID"] == rows[0]["_sighting_id"]
        assert split[0]["Sighting.sightingID"], "sighting ID must not be empty"

        d.write_csv(split, "out.csv")
        with open(Path(tmp) / "out.csv", encoding="utf-8", newline="") as f:
            csv_rows = list(csv.reader(f))
        header, data_row = csv_rows[0], csv_rows[1]
        idx = header.index("Sighting.sightingID")
        assert data_row[idx] == rows[0]["_sighting_id"], (
            "CSV shows an empty cell instead of the promoted sighting ID"
        )


def test_split_rows_by_photo_preserves_per_photo_license_alignment():
    """Each split row must carry only its own photo's licence, not e.g. the first.

    Regression guard for an off-by-one in the license_list[photo_index] lookup:
    uses three distinct licence codes so a misalignment can't hide behind
    identical values.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        obs = _obs(n_photos=3)
        licenses = ["cc-by", "cc-by-nc", "cc0"]
        for photo, license_code in zip(obs["photos"], licenses):
            photo["license_code"] = license_code

        rows = d.process_observations([obs], "Panthera onca")
        assert rows[0]["_license_list"] == licenses, "fixture setup sanity check"

        split = mod.split_rows_by_photo(rows)
        assert len(split) == 3
        assert [r["_license_list"] for r in split] == [[lic] for lic in licenses], (
            "split rows did not preserve per-photo licence order"
        )
        # And it survives all the way into the exported CSV column. The three
        # distinct licences also land in Encounter.researcherComments
        # (comma-joined), so this field genuinely needs comma-aware CSV
        # parsing rather than a naive split(",").
        d.write_csv(split, "out.csv")
        with open(Path(tmp) / "out.csv", encoding="utf-8", newline="") as f:
            csv_rows = list(csv.reader(f))
        header, data_rows = csv_rows[0], csv_rows[1:]
        idx = header.index("Encounter.mediaAsset0.license")
        assert [row[idx] for row in data_rows] == licenses


def _payload(html):
    """Pull the observations array out of a generated review page."""
    match = re.search(r"const observations = (\[.*?\]);\n", html, re.S)
    assert match, "observations payload not found"
    return json.loads(match.group(1))


def test_payload_carries_split_state_and_per_photo_licences():
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        obs = _obs(n_photos=3)
        obs["photos"][1]["license_code"] = ""          # middle photo unlicensed
        rows = d.process_observations([obs], "Panthera onca")
        for i in range(1, 4):
            (Path(tmp) / "photos" / f"111_{i}.jpg").write_bytes(b"x")
        d.write_html(rows, "review.html")

        entry = _payload((Path(tmp) / "review.html").read_text(encoding="utf-8"))[0]

        assert entry["sighting_id"] == rows[0]["_sighting_id"], (
            "browser has no sighting id to promote"
        )
        assert entry["initially_split"] is True
        assert entry["photo_licensed"] == [True, False, True]
        # The all-or-nothing flag stays for merged rows.
        assert entry["all_media_licensed"] is False


def test_payload_split_state_is_false_without_the_flag():
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=False)
        rows = d.process_observations([_obs(n_photos=3)], "Panthera onca")
        d.write_html(rows, "review.html")
        entry = _payload((Path(tmp) / "review.html").read_text(encoding="utf-8"))[0]
        assert entry["initially_split"] is False
        assert entry["sighting_id"] == rows[0]["_sighting_id"], (
            "a sighting id is still needed for manual splits"
        )


def test_payload_split_state_is_false_for_a_single_photo_even_with_the_flag():
    """Literal requirement: single photo + --social-split-observations on must
    still report initially_split is False -- correct by construction via the
    len(photo_list) > 1 guard, but nothing exercised it against write_html's
    actual output until now."""
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=1)], "Panthera onca")
        d.write_html(rows, "review.html")
        entry = _payload((Path(tmp) / "review.html").read_text(encoding="utf-8"))[0]
        assert entry["initially_split"] is False
        assert entry["sighting_id"] == rows[0]["_sighting_id"]


def test_payload_photo_licensed_is_padded_to_max_photos_across_observations():
    """photo_licensed must be padded per-observation to the run's max_photos,
    not to that observation's own photo count -- a later task pairs
    photo_licensed with photos/licenses by index, so a short array would
    silently shift which photo is considered licensed.

    Two observations with different photo counts force max_photos (4) above
    the smaller observation's own count (2), so padding is the only thing
    that can make the arrays line up.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=False)
        obs_a = _obs(obs_id=111, n_photos=4)
        obs_b = _obs(obs_id=222, n_photos=2)
        rows = d.process_observations([obs_a], "Panthera onca")
        rows += d.process_observations([obs_b], "Panthera onca")
        d.write_html(rows, "review.html")

        entries = _payload((Path(tmp) / "review.html").read_text(encoding="utf-8"))
        entry_b = next(e for e in entries if e["observation_id"] == 222)

        assert len(entry_b["photo_licensed"]) == 4, (
            "photo_licensed was padded to this observation's own photo count "
            "(2), not the run's max_photos (4)"
        )
        assert entry_b["photo_licensed"][2:] == [False, False], (
            "padding tail is not all False"
        )
        assert (
            len(entry_b["photo_licensed"])
            == len(entry_b["photos"])
            == len(entry_b["licenses"])
        ), "photo_licensed, photos and licenses must stay index-aligned"


def test_split_rows_by_photo_is_pure():
    """It must not mutate its input; run() relies on that for the HTML path.

    The snapshot is a deep copy, not a shallow one: a shallow `dict(r)` would
    share nested lists like _photo_list with `rows`, so an in-place mutation
    (`.append()`, `.clear()`, etc.) would silently be reflected in `before`
    too and the equality check below would never catch it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = _downloader(tmp, social_split=True)
        rows = d.process_observations([_obs(n_photos=3)], "Panthera onca")
        before = copy.deepcopy(rows)
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
