#!/usr/bin/env python3
"""Behavioural tests for the review page's JavaScript, run through Node.

The generated page is self-contained vanilla JS opened over file://. Node is a
test-only dependency: it loads the page's inline <script> in a vm context with a
stubbed DOM so the real functions can be called directly. Tests skip when node
is not installed rather than failing.
"""

import importlib.util
import json
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


def build_page(tmp_path, n_photos=4, social_split=False, licenses=None, specs=None):
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
    """
    if specs is None:
        specs = [{"id": 111, "n_photos": n_photos, "licenses": licenses}]

    obs_payloads = []
    photo_counts = []  # (obs_id, count) -- used below to write stub photo files
    for i, spec in enumerate(specs):
        obs_id = spec.get("id", 111 + i)
        obs_n_photos = spec.get("n_photos", n_photos)
        obs_licenses = spec.get("licenses", licenses)
        photos = []
        for j in range(obs_n_photos):
            code = "cc-by" if obs_licenses is None else obs_licenses[j]
            photos.append({"url": "https://example.test/a/square.jpg", "license_code": code})
        obs_payloads.append({
            "id": obs_id,
            "taxon": {"name": "Panthera onca", "preferred_common_name": "Jaguar"},
            "observed_on": "2026-07-01",
            "place_guess": "Pantanal",
            "photos": photos,
        })
        photo_counts.append((obs_id, obs_n_photos))

    d = mod.iNaturalistDownloader(
        output_dir=str(tmp_path), days_back=1, species_list=["Panthera onca"],
        social_split=social_split,
    )
    d.download_photo = lambda url, filename: True
    rows = d.process_observations(obs_payloads, "Panthera onca")
    for obs_id, count in photo_counts:
        for i in range(1, count + 1):
            (tmp_path / "photos" / f"{obs_id}_{i}.jpg").write_bytes(b"x")
    d.write_html(rows, "review.html")
    return tmp_path / "review.html"


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
    page = build_page(tmp_path, n_photos=1)
    out = run_js(page, """
        renderObservations();
        const labels = __created.filter(e => e.className.includes('btn-split')).map(e => e.textContent);
        console.log(JSON.stringify(labels));
    """)
    assert json.loads(out) == []
