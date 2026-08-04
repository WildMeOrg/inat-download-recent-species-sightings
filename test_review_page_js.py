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
        const before = selectionState.get(0);
        checkbox.checked = !before;
        checkbox.dispatch('change');
        console.log(JSON.stringify({ before: before, after: selectionState.get(0) }));
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
