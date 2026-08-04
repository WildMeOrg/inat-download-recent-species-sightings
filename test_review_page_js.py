#!/usr/bin/env python3
"""Behavioural tests for the review page's JavaScript, run through Node.

The generated page is self-contained vanilla JS opened over file://. Node is a
test-only dependency: it loads the page's inline <script> in a vm context with a
stubbed DOM so the real functions can be called directly. Tests skip when node
is not installed rather than failing.
"""

import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).parent
HARNESS = REPO / "js_harness" / "run_page.js"

SPEC = importlib.util.spec_from_file_location(
    "inat_downloader", str(REPO / "inat-download-new-species-sightings.py")
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)


def build_page(tmp_path, n_photos=4, social_split=False, licenses=None, specs=None,
               missing_photos=None):
    """Generate a real review page and return its path.

    The simple call style is unchanged: `build_page(tmp_path, n_photos=4)`
    still builds exactly one synthetic observation (id 111), same as before.

    Pass `specs` -- a list of dicts, e.g.
        [{"id": 111, "n_photos": 4}, {"id": 222, "n_photos": 1, "licenses": ["cc-by"]}]
    -- to build several observations with differing photo counts and
    licences, e.g. to prove a split observation's rows stay adjacent after
    renderObservations() sorts by selection state (a single-observation page
    can't exercise that: the sort would be trivially stable). A spec's own
    "id"/"n_photos"/"licenses" win; a missing "id" falls back to 111 plus its
    position in the list, and missing "n_photos"/"licenses" fall back to this
    function's own n_photos/licenses arguments.

    Two further per-spec keys, both also accepted as plain arguments for the
    single-observation style:

    "annotations" -- raw iNaturalist annotation dicts, e.g.
        [{"controlled_attribute_id": 22, "controlled_value_id": 24}]
    for "Evidence of Presence: Organism", which suppresses initially_split even
    with the flag on. Without this a flag-mode test cannot tell splitState
    seeded from initially_split apart from splitState seeded from the flag.

    "missing_photos" -- 1-based photo numbers whose stub file is deliberately
    NOT written, simulating a failed download. write_html then records None at
    that index of all_photo_paths, which is what keeps previews aligned with
    exports; a test needs this to prove a split row previews the photo it
    exports rather than a later one.
    """
    if specs is None:
        specs = [{"id": 111, "n_photos": n_photos, "licenses": licenses,
                  "missing_photos": missing_photos}]

    obs_payloads = []
    photo_plan = []  # (obs_id, count, missing) -- used to write stub photo files
    for i, spec in enumerate(specs):
        obs_id = spec.get("id", 111 + i)
        obs_n_photos = spec.get("n_photos", n_photos)
        obs_licenses = spec.get("licenses", licenses)
        obs_missing = spec.get("missing_photos", missing_photos) or []
        photos = []
        for j in range(obs_n_photos):
            code = "cc-by" if obs_licenses is None else obs_licenses[j]
            photos.append({"url": "https://example.test/a/square.jpg", "license_code": code})
        payload = {
            "id": obs_id,
            "taxon": {"name": "Panthera onca", "preferred_common_name": "Jaguar"},
            "observed_on": "2026-07-01",
            "place_guess": "Pantanal",
            "photos": photos,
        }
        if spec.get("annotations"):
            payload["annotations"] = spec["annotations"]
        obs_payloads.append(payload)
        photo_plan.append((obs_id, obs_n_photos, obs_missing))

    d = mod.iNaturalistDownloader(
        output_dir=str(tmp_path), days_back=1, species_list=["Panthera onca"],
        social_split=social_split,
    )
    d.download_photo = lambda url, filename: True
    rows = d.process_observations(obs_payloads, "Panthera onca")
    for obs_id, count, missing in photo_plan:
        for i in range(1, count + 1):
            if i in missing:
                continue
            (tmp_path / "photos" / f"{obs_id}_{i}.jpg").write_bytes(b"x")
    d.write_html(rows, "review.html")
    return tmp_path / "review.html"


def _visible_header_cells(page, split_header_revealed):
    """How many <th> cells a reader actually sees, so a test can compare that
    against the <td> count the JS produced and catch a head/body mismatch.

    The Split <th> ships with display:none and is revealed at runtime by
    initializeSplitColumn(), so the caller passes what it observed happening.
    """
    html = page.read_text(encoding="utf-8")
    # Scoped to the table head: the inline script's comments mention <th> too.
    head = re.search(r"<thead>(.*?)</thead>", html, re.S)
    assert head, "no <thead> in the generated page"
    cells = re.findall(r"<th\b[^>]*>", head.group(1))
    assert len(cells) == 12, f"expected 12 <th> in the table head, found {len(cells)}"
    hidden = [c for c in cells if "display: none" in c]
    assert len(hidden) == 1 and "split-header" in hidden[0], (
        f"expected exactly the Split header to ship hidden, got {hidden}"
    )
    return len(cells) - (0 if split_header_revealed else 1)


def run_js(page, assertions):
    """Run an assertion snippet against the page's JS; return stdout."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(assertions)
        assertions_path = fh.name
    try:
        result = subprocess.run(
            ["node", str(HARNESS), str(page), assertions_path],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"harness failed:\n{result.stderr}"
        return result.stdout
    finally:
        Path(assertions_path).unlink(missing_ok=True)


def test_harness_can_load_the_page_and_see_the_data(tmp_path):
    page = build_page(tmp_path, n_photos=4)
    out = run_js(page, """
        console.log(JSON.stringify({
            observations: observations.length,
            photos: observations[0].photo_count,
            initiallySplit: observations[0].initially_split,
            hasSightingId: Boolean(observations[0].sighting_id),
        }));
    """)
    assert json.loads(out) == {
        "observations": 1, "photos": 4, "initiallySplit": False, "hasSightingId": True,
    }


def test_build_page_supports_multiple_observations_with_distinct_photo_counts(tmp_path):
    """Fixture self-test: `specs` must yield one payload entry per spec, each
    with its own photo count, so later tests (e.g. proving split rows from
    different sightings stay adjacent after a sort) can rely on it."""
    page = build_page(tmp_path, specs=[
        {"id": 111, "n_photos": 4},
        {"id": 222, "n_photos": 2, "licenses": ["cc-by", None]},
    ])
    out = run_js(page, """
        console.log(JSON.stringify(observations.map(o => ({
            id: o.observation_id, photos: o.photo_count,
        }))));
    """)
    assert json.loads(out) == [
        {"id": 111, "photos": 4},
        {"id": 222, "photos": 2},
    ]


def test_checkbox_change_event_updates_selection_state(tmp_path):
    """Proves the DOM stub's addEventListener/dispatch actually wire through:
    toggling a rendered checkbox and firing 'change' must update the same
    selectionState the exported CSV is built from. This is the exact failure
    mode a no-op addEventListener stub would hide -- a test that looks like
    it simulates a click but silently does nothing."""
    page = build_page(tmp_path, n_photos=1)
    out = run_js(page, """
        renderObservations();
        const checkbox = __created.find(el => el.className === 'obs-checkbox');
        if (!checkbox) throw new Error('no checkbox was rendered');
        // Selection is keyed by rowKey(), not by the row's position.
        const key = rowKey(observations[0], null);
        const before = selectionState.get(key);
        checkbox.checked = !before;
        checkbox.dispatch('change');
        console.log(JSON.stringify({ before: before, after: selectionState.get(key) }));
    """)
    result = json.loads(out)
    assert result["after"] == (not result["before"])


def test_dom_stub_supports_interaction_primitives(tmp_path):
    """Direct check of the harness's stub itself (not the page's business
    logic): events fire via dispatch(), attributes round-trip through
    setAttribute/getAttribute/removeAttribute, querySelectorAll actually
    finds matching elements by class and by tag, and a non-empty innerHTML
    assignment fails loudly instead of being silently swallowed."""
    page = build_page(tmp_path, n_photos=1)
    out = run_js(page, """
        const el = document.createElement('div');
        el.className = 'widget';
        el.setAttribute('data-foo', '42');

        let firedWithSelf = false;
        el.addEventListener('click', (e) => { firedWithSelf = e.target === el; });
        el.dispatch('click');

        const foundByClass = document.querySelectorAll('.widget').includes(el);
        const foundByTag = document.querySelectorAll('div').includes(el);

        const attrBeforeRemove = el.getAttribute('data-foo');
        el.removeAttribute('data-foo');
        const attrAfterRemove = el.getAttribute('data-foo');

        let innerHtmlThrew = false;
        try { el.innerHTML = '<span>x</span>'; } catch (e) { innerHtmlThrew = true; }
        el.innerHTML = '';  // clearing must still work

        console.log(JSON.stringify({
            firedWithSelf, foundByClass, foundByTag,
            attrBeforeRemove, attrAfterRemove, innerHtmlThrew,
        }));
    """)
    assert json.loads(out) == {
        "firedWithSelf": True,
        "foundByClass": True,
        "foundByTag": True,
        "attrBeforeRemove": "42",
        "attrAfterRemove": None,
        "innerHtmlThrew": True,
    }


def test_split_expands_into_one_row_per_photo(tmp_path):
    page = build_page(tmp_path, n_photos=4)
    out = run_js(page, """
        const before = displayRows().length;
        toggleSplit(111);
        const after = displayRows().length;
        toggleSplit(111);
        console.log(JSON.stringify({before, after, back: displayRows().length}));
    """)
    assert json.loads(out) == {"before": 1, "after": 4, "back": 1}


def test_flag_mode_starts_split(tmp_path):
    page = build_page(tmp_path, n_photos=4, social_split=True)
    out = run_js(page, "console.log(displayRows().length);")
    assert out.strip() == "4"


def test_selection_survives_a_split_unsplit_resplit_round_trip(tmp_path):
    page = build_page(tmp_path, n_photos=4)
    out = run_js(page, """
        toggleSplit(111);
        const obs = observations[0];
        selectionState.set(rowKey(obs, 2), false);      // drop photo C
        toggleSplit(111);                              // unsplit
        toggleSplit(111);                              // and back
        console.log(JSON.stringify(displayRows().map(r => isSelected(r.obs, r.photoIndex))));
    """)
    assert json.loads(out) == [True, True, False, True]


def test_deselecting_one_photo_drops_only_that_row_from_the_csv(tmp_path):
    page = build_page(tmp_path, n_photos=4)
    out = run_js(page, """
        toggleSplit(111);
        selectionState.set(rowKey(observations[0], 2), false);
        const csv = generateCSV(getSelectedObservations());
        const lines = csv.split('\\n');
        const header = lines[0].split(',');
        const idx = header.indexOf('Sighting.sightingID');
        console.log(JSON.stringify({
            dataRows: lines.length - 1,
            sightingIds: [...new Set(lines.slice(1).map(l => l.split(',')[idx]))],
            assetCols: header.filter(h => /^Encounter\\.mediaAsset\\d+$/.test(h)).length,
            photoC: csv.includes('111_3.jpg'),
        }));
    """)
    result = json.loads(out)
    assert result["dataRows"] == 3
    assert len(result["sightingIds"]) == 1 and result["sightingIds"][0]
    assert result["assetCols"] == 1, "all-split export should not carry empty columns"
    assert result["photoC"] is False, "the deselected photo leaked into the CSV"


def test_merged_row_sighting_id_depends_on_the_flag(tmp_path):
    for social_split, expect_id in ((False, False), (True, True)):
        page = build_page(tmp_path / f"m{social_split}", n_photos=4, social_split=social_split)
        out = run_js(page, """
            observations.forEach(o => splitState.set(o.observation_id, false));
            const csv = generateCSV(getSelectedObservations());
            const header = csv.split('\\n')[0].split(',');
            const idx = header.indexOf('Sighting.sightingID');
            const value = csv.split('\\n')[1].split(',')[idx];
            console.log(JSON.stringify({hasId: Boolean(value)}));
        """)
        assert json.loads(out)["hasId"] is expect_id


def test_split_rows_stay_adjacent_after_sorting(tmp_path):
    """Needs MORE THAN ONE observation, or it proves nothing.

    Sorting ranks observations and then expands their photos. With a single
    observation every row trivially belongs to it, so the assertion cannot fail
    however broken the sort is. Two observations, one split and one not, with the
    split one's first photo deselected so the sort actually has work to do, is
    the smallest fixture that can detect scattering.
    """
    page = build_page(tmp_path, specs=[
        {"id": 111, "n_photos": 3},
        {"id": 222, "n_photos": 2},
    ])
    out = run_js(page, """
        toggleSplit(111);
        // Deselect one photo of 111 so selected-first sorting has a reason to move rows.
        selectionState.set(rowKey(observations.find(o => o.observation_id === 111), 0), false);
        renderObservations();
        console.log(JSON.stringify(displayRows().map(r => r.obs.observation_id)));
    """)
    ids = json.loads(out)

    # Every run of a given id must be contiguous: no id may reappear after a
    # different id has intervened.
    runs = [ids[0]]
    for observation_id in ids[1:]:
        if observation_id != runs[-1]:
            runs.append(observation_id)
    assert len(runs) == len(set(runs)), (
        f"an observation's rows were scattered by sorting: {ids}"
    )
    # And the split observation really did expand, so the fixture is exercising it.
    assert ids.count(111) == 3, ids
    assert ids.count(222) == 1, ids


def test_split_row_is_selected_on_its_own_licence(tmp_path):
    """The middle photo is unlicensed: merged is all-or-nothing, split is per-photo."""
    page = build_page(tmp_path, n_photos=3, licenses=["cc-by", "", "cc-by"])
    out = run_js(page, """
        const merged = isSelected(observations[0], null);
        toggleSplit(111);
        const split = displayRows().map(r => isSelected(r.obs, r.photoIndex));
        console.log(JSON.stringify({merged, split}));
    """)
    assert json.loads(out) == {"merged": False, "split": [True, False, True]}


def test_single_photo_observation_has_no_split_button(tmp_path):
    """Negative test, so it also proves a row was rendered at all -- otherwise
    an empty table would satisfy it and it would pass however broken the
    control is (it passed before the feature existed)."""
    page = build_page(tmp_path, n_photos=1)
    out = run_js(page, """
        initializeSplitColumn();
        renderObservations();
        const rows = __byId['observations-body'].children;
        console.log(JSON.stringify({
            labels: __created.filter(e => e.className.includes('btn-split')).map(e => e.textContent),
            renderedRows: rows.length,
            cellCounts: [...new Set(rows.map(tr => tr.children.length))],
            headerRevealed: __byId['split-header'].style.display === '',
        }));
    """)
    result = json.loads(out)
    assert result["labels"] == []
    assert result["renderedRows"] == 1, "nothing was rendered, so the test is vacuous"
    # Nothing on this page can be split, so the Split column does not exist:
    # its <th> stays hidden AND no <td> is appended, or the body would carry one
    # more cell than the head shows.
    assert result["headerRevealed"] is False
    assert result["cellCounts"] == [11] == [_visible_header_cells(page, False)]


def test_split_button_renders_and_clicking_it_splits_the_observation(tmp_path):
    """The control itself, not just the model underneath it.

    Every one of these passed the model-only suite: wiring onclick to
    sighting_id instead of observation_id, never appending the cell, never
    revealing the header, never relabelling to Unsplit, dropping the group
    striping. So this test asserts the button exists, says 'Split', that
    invoking its real handler splits the observation, and that the re-rendered
    rows are relabelled, striped, and have the right cell count.
    """
    page = build_page(tmp_path, n_photos=4)
    out = run_js(page, """
        initializeSplitColumn();
        renderObservations();
        const buttons = () => __created.filter(e => e.className.includes('btn-split'));
        const before = buttons();
        if (before.length !== 1) throw new Error('expected 1 Split button, got ' + before.length);
        const labelBefore = before[0].textContent;

        before[0].onclick();   // the handler a real click would run

        const after = buttons().slice(before.length);   // buttons from the re-render
        const rows = __byId['observations-body'].children;
        console.log(JSON.stringify({
            labelBefore: labelBefore,
            rowsAfter: displayRows().length,
            renderedRowsAfter: rows.length,
            labelsAfter: [...new Set(after.map(e => e.textContent))],
            classesAfter: [...new Set(after.map(e => e.className))],
            headerDisplay: __byId['split-header'].style.display,
            cellCounts: [...new Set(rows.map(tr => tr.children.length))],
            allStriped: rows.every(tr => tr.classList.contains('obs-group-even')
                                      || tr.classList.contains('obs-group-odd')),
        }));
    """)
    result = json.loads(out)
    assert result["labelBefore"] == "Split"
    assert result["rowsAfter"] == 4, "the button's handler did not split the observation"
    assert result["renderedRowsAfter"] == 4, "the split rows were not rendered"
    assert result["labelsAfter"] == ["Unsplit"]
    assert result["classesAfter"] == ["btn-split split"]
    assert result["headerDisplay"] == "", "the Split column header was never revealed"
    assert result["allStriped"] is True, "split rows lost their group striping"
    assert result["cellCounts"] == [12] == [_visible_header_cells(page, True)]


def test_bulk_deselect_survives_a_later_split(tmp_path):
    """"Deselect All" then Split must not silently re-arm the excluded rows.

    setAllSelected only ever saw the rows on screen, so the other side of the
    toggle stayed unkeyed and defaultSelected() re-seeded it to true.
    """
    page = build_page(tmp_path, n_photos=3)
    out = run_js(page, """
        renderObservations();
        deselectAll();
        const afterDeselect = getSelectedObservations().length;
        toggleSplit(111);
        const afterSplit = getSelectedObservations().length;
        selectAll();
        const afterSelectAll = getSelectedObservations().length;
        toggleSplit(111);                       // back to merged
        console.log(JSON.stringify({
            afterDeselect, afterSplit, afterSelectAll,
            mergedAfterSelectAll: getSelectedObservations().length,
        }));
    """)
    assert json.loads(out) == {
        "afterDeselect": 0,
        "afterSplit": 0,          # was 3: every split row re-seeded to selected
        "afterSelectAll": 3,
        "mergedAfterSelectAll": 1,
    }


def test_splitting_the_narrower_observation_uses_its_own_photo_count(tmp_path):
    """photos/licenses are padded to max_photos with nulls, so a split must be
    driven by photo_count, never by photos.length.

    Every earlier fixture splits the widest observation, where the two are equal
    and the padding is invisible. Here the narrower one is split: iterating
    photos.length would give observation 222 four rows instead of two, the extra
    ones exporting null mediaAssets.

    Note the total row count is the WRONG thing to assert here: 3 is correct
    (1 merged + 2 split) and the padding bug produces 5 (1 merged + 4 padded),
    so a test written around "5" would enshrine the bug. Assert 222's own
    contribution instead.
    """
    page = build_page(tmp_path, specs=[
        {"id": 111, "n_photos": 4},
        {"id": 222, "n_photos": 2},
    ])
    out = run_js(page, """
        const obs222 = observations.find(o => o.observation_id === 222);
        const fields = (line) => line.split(',');
        const csvFor = (id) => {
            const csv = generateCSV(getSelectedObservations()).split('\\n');
            const header = fields(csv[0]);
            return {
                header: header,
                rows: csv.slice(1).map(fields).filter(r => r[0] === String(id)),
            };
        };

        // (a) merged: the padding must not leak into the narrower row's export.
        const merged = csvFor(222);
        const mergedRow = merged.rows[0];
        const mergedPhotoCount = mergedRow[merged.header.indexOf('photo_count')];
        const mergedFilenames = mergedRow[merged.header.indexOf('photo_filenames')];

        // (b) split the narrower observation.
        toggleSplit(222);
        renderObservations();
        const split = csvFor(222);

        console.log(JSON.stringify({
            paddedPhotosLength: obs222.photos.length,
            realPhotoCount: obs222.photo_count,
            mergedPhotoCount: mergedPhotoCount,
            mergedFilenames: mergedFilenames,
            totalRows: displayRows().length,
            rowsFor222: displayRows().filter(r => r.obs.observation_id === 222).length,
            renderedRows: __byId['observations-body'].children.length,
            csvRowsFor222: split.rows.length,
        }));
    """)
    result = json.loads(out)
    # The fixture really does pad, so the mutation would be observable.
    assert result["paddedPhotosLength"] == 4 and result["realPhotoCount"] == 2
    assert result["mergedPhotoCount"] == "2"
    assert result["mergedFilenames"] == "222_1.jpg; 222_2.jpg"
    assert result["totalRows"] == 3, "1 merged row for 111 plus 2 split rows for 222"
    assert result["rowsFor222"] == 2, "the padded nulls became phantom display rows"
    assert result["renderedRows"] == 3, "the padded nulls became phantom table rows"
    assert result["csvRowsFor222"] == 2, "phantom rows reached the CSV"


def test_no_selection_keys_are_seeded_beyond_a_photo_count(tmp_path):
    """State hygiene for the same padding invariant, one layer deeper.

    anySelected() probes each photo of a split observation to rank it. Driving
    that probe from photos.length instead of photo_count returns the same answer
    today -- the padded photo_licensed entries are False, so the extra probes are
    always false -- but isSelected() *seeds* a key for every index it is asked
    about, leaving phantom entries like "222:2" on a 2-photo observation. They
    are inert only because nothing currently reads past photo_count; the moment
    anything does (the exact mutation family this suite keeps catching) those
    pre-seeded False keys would silently deselect real split rows instead of
    letting them default to their own licence.

    The probe short-circuits on the first selected photo, so 222's real photos
    are deselected here to force anySelected all the way through.
    """
    page = build_page(tmp_path, specs=[
        {"id": 111, "n_photos": 4},
        {"id": 222, "n_photos": 2},
    ])
    out = run_js(page, """
        const obs222 = observations.find(o => o.observation_id === 222);
        toggleSplit(222);
        for (let i = 0; i < obs222.photo_count; i++) {
            selectionState.set(rowKey(obs222, i), false);
        }
        renderObservations();   // sorts, so anySelected() probes every photo
        const limits = new Map(observations.map(o => [String(o.observation_id), o.photo_count]));
        console.log(JSON.stringify({
            phantom: [...selectionState.keys()].filter(k => {
                const parts = k.split(':');
                return parts[1] !== 'all' && Number(parts[1]) >= limits.get(parts[0]);
            }),
            paddedWidth: obs222.photos.length,
            realWidth: obs222.photo_count,
        }));
    """)
    result = json.loads(out)
    assert result["paddedWidth"] > result["realWidth"], "the fixture must actually pad"
    assert result["phantom"] == [], (
        f"selection keys were seeded past photo_count: {result['phantom']}"
    )


def test_export_columns_are_sized_by_the_widest_row_written(tmp_path):
    """Splits the WIDEST observation while a narrower one stays merged.

    csvColumnCount must be driven by the rows actually emitted. Every other
    fixture splits the narrowest (or the only) observation, so the one merged row
    left is also the widest and its photo_count equals its padded photos.length
    -- which makes a mutation to photos.length invisible. Here 111 becomes four
    1-photo rows and 222 stays merged with 2 real photos inside a 4-wide padded
    array: the correct column count is 2, and reading photos.length emits 4,
    putting two empty mediaAsset column pairs in the file handed to Wildbook.
    """
    page = build_page(tmp_path, specs=[
        {"id": 111, "n_photos": 4},
        {"id": 222, "n_photos": 2},
    ])
    out = run_js(page, """
        toggleSplit(111);                       // split the WIDEST one
        const csv = generateCSV(getSelectedObservations()).split('\\n');
        const header = csv[0].split(',');
        const firstAsset = header.indexOf('Encounter.mediaAsset0');
        const rows = csv.slice(1).map(l => l.split(','));
        console.log(JSON.stringify({
            assetColumns: header.slice(firstAsset),
            raggedRows: rows.filter(r => r.length !== header.length).length,
            // observation id plus the row's mediaAsset tail
            tails: rows.map(r => [r[0]].concat(r.slice(firstAsset))),
        }));
    """)
    result = json.loads(out)
    # Two column pairs: the widest row written is 222's merged row, with 2 photos.
    assert result["assetColumns"] == [
        "Encounter.mediaAsset0", "Encounter.mediaAsset0.license",
        "Encounter.mediaAsset1", "Encounter.mediaAsset1.license",
    ], "column count was not sized from the widest row actually written"
    assert result["raggedRows"] == 0
    assert result["tails"] == [
        # The split rows carry one photo each and one empty pair, because a wider
        # merged row shares the export -- not because of the padded array.
        ["111", "111_1.jpg", "cc-by", "", ""],
        ["111", "111_2.jpg", "cc-by", "", ""],
        ["111", "111_3.jpg", "cc-by", "", ""],
        ["111", "111_4.jpg", "cc-by", "", ""],
        ["222", "222_1.jpg", "cc-by", "222_2.jpg", "cc-by"],
    ]


def test_split_row_previews_the_photo_it_exports(tmp_path):
    """all_photo_paths must stay index-aligned with photos.

    Python used to append only paths whose file exists, while photos/licenses
    stayed aligned to the full photo list. With 111_2.jpg missing, row 2 then
    previewed 111_3 and exported 111_2 -- showing the reviewer a different photo
    from the one they are deciding about, in a feature whose whole purpose is
    deciding per photo.
    """
    page = build_page(tmp_path, n_photos=4, missing_photos=[2])
    out = run_js(page, """
        const obs = observations[0];
        toggleSplit(111);
        renderObservations();

        // Preview shown in each row, in row order (cell 1 is the photo cell).
        const previews = __byId['observations-body'].children.map(tr => {
            const cell = tr.children[1].children[0];
            return cell.className === 'photo-preview' ? cell.src : null;
        });

        const csv = generateCSV(displayRows()).split('\\n');
        const assetIdx = csv[0].split(',').indexOf('Encounter.mediaAsset0');
        const exports = csv.slice(1).map(l => l.split(',')[assetIdx]);

        // The modal must land on the photo the row previews, despite the gaps --
        // asserted by firing each row's REAL rendered handler, not by calling
        // galleryFor directly. The mapping is worth nothing if renderRow does not
        // route through it, and a directly-called helper cannot detect that.
        const opened = __byId['observations-body'].children.map(tr => {
            const cell = tr.children[1].children[0];
            if (cell.className !== 'photo-preview') return null;
            currentGallery = [];
            currentImageIndex = -1;
            cell.onclick();
            return {
                gallery: currentGallery,
                index: currentImageIndex,
                landedOn: currentGallery[currentImageIndex],
            };
        });

        console.log(JSON.stringify({
            aligned: obs.all_photo_paths.length === obs.photo_count,
            paths: obs.all_photo_paths,
            previews: previews,
            exports: exports,
            opened: opened,
        }));
    """)
    result = json.loads(out)
    assert result["aligned"] is True, "all_photo_paths is not index-aligned with photos"
    assert result["paths"] == [
        "photos/111_1.jpg", None, "photos/111_3.jpg", "photos/111_4.jpg"
    ]
    # Every row exports all four photos in order...
    assert result["exports"] == ["111_1.jpg", "111_2.jpg", "111_3.jpg", "111_4.jpg"]
    # ...and previews either that same photo or nothing -- never a different one.
    assert result["previews"] == [
        "photos/111_1.jpg", None, "photos/111_3.jpg", "photos/111_4.jpg"
    ]
    for preview, exported in zip(result["previews"], result["exports"]):
        assert preview in (None, f"photos/{exported}"), (
            f"row previews {preview} but exports {exported}"
        )
    # And clicking a preview really opens the gallery on that same photo: the
    # gallery is compacted (no nulls, which the modal cannot display) and the
    # start index is mapped into it, never the raw photo index.
    compacted = ["photos/111_1.jpg", "photos/111_3.jpg", "photos/111_4.jpg"]
    assert [o["index"] if o else None for o in result["opened"]] == [0, None, 1, 2], (
        "the row's photo index reached openModal unmapped"
    )
    for preview, opened in zip(result["previews"], result["opened"]):
        if preview is None:
            assert opened is None, "a row with no preview still wired a click handler"
            continue
        assert opened["gallery"] == compacted, (
            f"modal was handed {opened['gallery']}, which the viewer cannot display"
        )
        assert opened["landedOn"] == preview, (
            f"gallery opened on {opened['landedOn']}, row shows {preview}"
        )


def test_flag_mode_respects_the_organism_evidence_suppression(tmp_path):
    """splitState must be seeded from initially_split, not from the flag.

    Seeding it from socialSplitMode passes every other flag-mode test, and
    silently discards the "Evidence of Presence: Organism" suppression that is
    the only reason Python computes initially_split at all.
    """
    page = build_page(tmp_path, social_split=True, specs=[
        {"id": 111, "n_photos": 3},
        {"id": 222, "n_photos": 3,
         "annotations": [{"controlled_attribute_id": 22, "controlled_value_id": 24}]},
    ])
    out = run_js(page, """
        console.log(JSON.stringify({
            seeded: observations.map(o => ({
                id: o.observation_id, initially: o.initially_split, split: isSplit(o),
            })),
            rows: displayRows().length,
        }));
    """)
    result = json.loads(out)
    assert result["seeded"] == [
        {"id": 111, "initially": True, "split": True},
        {"id": 222, "initially": False, "split": False},
    ], "the organism-evidence observation was split anyway"
    assert result["rows"] == 4, "3 rows for the split one plus 1 merged"
