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


def build_page(tmp_path, n_photos=4, social_split=False, licenses=None):
    """Generate a real review page and return its path."""
    photos = []
    for i in range(n_photos):
        code = "cc-by" if licenses is None else licenses[i]
        photos.append({"url": "https://example.test/a/square.jpg", "license_code": code})
    observation = {
        "id": 111,
        "taxon": {"name": "Panthera onca", "preferred_common_name": "Jaguar"},
        "observed_on": "2026-07-01",
        "place_guess": "Pantanal",
        "photos": photos,
    }
    d = mod.iNaturalistDownloader(
        output_dir=str(tmp_path), days_back=1, species_list=["Panthera onca"],
        social_split=social_split,
    )
    d.download_photo = lambda url, filename: True
    rows = d.process_observations([observation], "Panthera onca")
    for i in range(1, n_photos + 1):
        (tmp_path / "photos" / f"111_{i}.jpg").write_bytes(b"x")
    d.write_html(rows, "review.html")
    return tmp_path / "review.html"


def run_js(page, assertions):
    """Run an assertion snippet against the page's JS; return stdout."""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(assertions)
        assertions_path = fh.name
    result = subprocess.run(
        ["node", str(HARNESS), str(page), assertions_path],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"harness failed:\n{result.stderr}"
    return result.stdout


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
