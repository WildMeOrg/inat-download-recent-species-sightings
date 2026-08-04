# Per-observation Split/Unsplit Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a reviewer press Split on any multi-photo observation in the generated HTML review page to expand it into one independently-selectable row per photo, and Unsplit to collapse it back.

**Architecture:** Splitting moves out of `process_observations()` into a pure `split_rows_by_photo()` function applied only on the direct-CSV path. `process_observations()` then always emits one row per observation, so the browser receives a uniform payload and owns all grouping via a `splitState` map seeded from Python. The existing Merge machinery is replaced, not duplicated.

**Tech Stack:** Python 3 standard library only (no new runtime deps). Browser: inline vanilla JavaScript. Tests: pytest, plus Node's `vm` module for exercising the generated page's JavaScript.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-04-html-review-split-control-design.md`
- **The generated page stays self-contained:** inline vanilla JS, opened over `file://`, no build step, no npm, no ES modules, no external requests. Node is a test-harness dependency only.
- **No new runtime dependencies.** `node` is a soft test dependency — tests that need it call `pytest.skip()` when `shutil.which("node")` is None.
- **The file being modified is `inat-download-new-species-sightings.py`** (~2280 lines). Its HTML template is one giant Python f-string, so **every literal `{` or `}` in JavaScript must be doubled as `{{` / `}}`**. Forgetting this is the single most common way to break this file.
- **Do not use `\/` in the f-string** — Python emits a SyntaxWarning for the invalid escape. Use `startsWith()` instead of a regex when matching URL schemes.
- **`Sighting.sightingID` emission rule is `socialSplitMode || isSplit(obs)`** and is deliberately mode-dependent. It must carry a comment saying so, or a future reader will "simplify" it and change customers' Wildbook imports.
- **Existing behavior that must not change:** a run without `--social-split-observations` and with no manual splits must produce a byte-identical CSV to today, including an empty `Sighting.sightingID` column.
- Run the full suite with `python3 -m pytest -q` after every task. It is currently **34 passing**.

---

### Task 1: Extract splitting into a pure function

Currently `process_observations()` (line 396) branches at line 577 on `self.social_split` and contains **two nearly identical 34-key row literals**. This task removes the split branch and moves the behavior into a standalone function, with no net change to what `run()` writes.

**Files:**
- Modify: `inat-download-new-species-sightings.py:577-620` (delete the split branch), `:621-623` (sighting id), `:2155-2161` (`run()` dispatch)
- Test: `test_export_integrity.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `split_rows_by_photo(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]` — module-level function. One input row with N photos and `_split_eligible` True becomes N output rows, each with one photo, sharing the input row's `_sighting_id` in the `Sighting.sightingID` column. Rows that are not eligible pass through unchanged.
  - Every row from `process_observations()` now carries `_sighting_id: str` (always a UUID) and `_split_eligible: bool`.
  - `Sighting.sightingID` from `process_observations()` is now always `None`.

- [ ] **Step 1: Write the failing tests**

Add to `test_export_integrity.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test_export_integrity.py -q -k "process_observations_always or split_rows_by_photo"`
Expected: FAIL — `AttributeError: module 'inat_downloader' has no attribute 'split_rows_by_photo'`, and the `always_returns_one_row` test fails with `social_split=True gave 4 rows`.

- [ ] **Step 3: Delete the split branch from `process_observations`**

Replace lines 577-623 — the whole `if self.social_split ... else:` construct and its two row literals — so only one row literal remains, built unconditionally. Change the sighting-id line and add the two new internal fields. Concretely: delete from `if self.social_split and len(photo_filenames) > 1 and not has_organism_evidence:` through the `else:` and its two comment lines, then replace

```python
                sighting_id = str(uuid.uuid4()) if self.social_split and len(photo_filenames) >= 1 else None
```

with

```python
            # Every observation gets a sighting ID, but it stays internal until a
            # split actually needs it -- either split_rows_by_photo() on the CSV
            # path, or the reviewer's Split button on the HTML path. Promoting it
            # unconditionally would populate a column that is empty today.
            sighting_id = None
            split_eligible = (
                self.social_split
                and len(photo_filenames) > 1
                and not has_organism_evidence
            )
```

Dedent the remaining `row = {` literal to one level inside the `for` loop, and add these three entries to it (keep `'Sighting.sightingID': sighting_id`):

```python
                '_sighting_id': str(uuid.uuid4()),  # Promoted to the column only when split
                '_split_eligible': split_eligible,  # Whether the flag would split this one
```

- [ ] **Step 4: Add the `split_rows_by_photo` function**

Insert at module level, immediately after the `fetch_json()` function (before `class iNaturalistDownloader:`):

```python
def split_rows_by_photo(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Expand each split-eligible row into one row per photo.

    Rows sharing an observation become one Wildbook Sighting: they all carry the
    observation's pre-generated _sighting_id in Sighting.sightingID.

    This runs *after* deduplication, which is deliberate. When splitting happened
    inside process_observations(), deduplicate_rows() saw the split rows and
    collapsed them back to one -- silently turning --social-split-observations
    into a no-op. Keeping the split downstream makes that impossible.

    Args:
        rows: Processed observation rows, one per observation

    Returns:
        A new list; the input rows are not modified
    """
    expanded = []

    for row in rows:
        photo_list = row.get('_photo_list', [])
        license_list = row.get('_license_list', [])

        if not row.get('_split_eligible') or len(photo_list) <= 1:
            expanded.append(row)
            continue

        for photo_index, photo_filename in enumerate(photo_list):
            split_row = dict(row)
            split_row['Sighting.sightingID'] = row['_sighting_id']
            split_row['photo_count'] = 1
            split_row['photo_filenames'] = photo_filename
            split_row['_photo_list'] = [photo_filename]
            split_row['_license_list'] = (
                [license_list[photo_index]] if photo_index < len(license_list) else []
            )
            expanded.append(split_row)

    return expanded
```

- [ ] **Step 5: Apply it on the CSV path in `run()`**

At line 2155, replace the write dispatch:

```python
            if self.html_review:
                html_filename = f"inat_observations_review_{species_part}{place_part}_{timestamp}.html"
                self.write_html(all_observations_data, html_filename)
            else:
                # The HTML path does its own splitting in the browser, so only the
                # direct-CSV path needs it applied here.
                csv_rows = all_observations_data
                if self.social_split:
                    csv_rows = split_rows_by_photo(csv_rows)
                csv_filename = f"inat_observations_{species_part}{place_part}_{timestamp}.csv"
                self.write_csv(csv_rows, csv_filename)
```

- [ ] **Step 6: Run the new tests**

Run: `python3 -m pytest test_export_integrity.py -q -k "process_observations_always or split_rows_by_photo"`
Expected: PASS (4 tests)

- [ ] **Step 7: Fix the two tests that assert the old seam**

`test_dedup_keeps_every_social_split_row` calls `process_observations` expecting 4 rows. Replace it with:

```python
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
```

- [ ] **Step 8: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS. `test_merged_export_column_count_covers_recombined_photos` still passes at this point — it greps generated HTML, and Task 4 removes it alongside the merge code it describes.

- [ ] **Step 9: Verify the CSV output is unchanged**

Run:

```bash
python3 - <<'EOF'
import importlib.util, tempfile, pathlib
spec = importlib.util.spec_from_file_location("m", "inat-download-new-species-sightings.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
OBS = {"id": 111, "taxon": {"name": "Panthera onca"}, "observed_on": "2026-07-01",
       "photos": [{"url": "https://x/a/square.jpg", "license_code": "cc-by"} for _ in range(3)]}
for social in (False, True):
    with tempfile.TemporaryDirectory() as tmp:
        d = m.iNaturalistDownloader(output_dir=tmp, days_back=1, species_list=["x"], social_split=social)
        d.download_photo = lambda u, f: True
        rows = d.process_observations([OBS], "x")
        if social: rows = m.split_rows_by_photo(rows)
        d.write_csv(rows, "o.csv")
        text = pathlib.Path(tmp, "o.csv").read_text()
        lines = text.splitlines()
        print(f"social_split={social}: {len(lines)-1} data rows")
        idx = lines[0].split(',').index('Sighting.sightingID')
        print("   sightingID column:", [l.split(',')[idx] for l in lines[1:]])
EOF
```

Expected: `social_split=False: 1 data rows` with an empty sighting ID, and `social_split=True: 3 data rows` all sharing one non-empty UUID.

- [ ] **Step 10: Commit**

```bash
git add inat-download-new-species-sightings.py test_export_integrity.py
git commit -m "refactor: extract splitting into a pure split_rows_by_photo()

process_observations() carried two nearly identical 34-key row literals, one
per branch of the social_split check. Splitting now happens in a standalone
function applied only on the direct-CSV path, so the literal exists once.

Moving the split after deduplication also makes the bug fixed in 8c70595
structurally impossible rather than merely fixed: deduplicate_rows() can no
longer see split rows, because they do not exist yet when it runs."
```

---

### Task 2: Feed the browser split state and per-photo licences

`write_html()` (line 770) builds the JSON payload. It needs three additions so the browser can own grouping. No visible behavior change yet.

**Files:**
- Modify: `inat-download-new-species-sightings.py:770-900` (`write_html`)
- Test: `test_export_integrity.py`

**Interfaces:**
- Consumes: `_sighting_id` and `_split_eligible` from Task 1.
- Produces: each entry in the page's `observations` array gains `sighting_id: str`, `initially_split: bool`, and `photo_licensed: bool[]` (parallel to `photos`, padded to `max_photos`).

- [ ] **Step 1: Write the failing test**

Add to `test_export_integrity.py`:

```python
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

        assert entry["sighting_id"], "browser has no sighting id to promote"
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
        assert entry["sighting_id"], "a sighting id is still needed for manual splits"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest test_export_integrity.py -q -k payload`
Expected: FAIL with `KeyError: 'initially_split'`.

- [ ] **Step 3: Add the fields**

In `write_html`, the `all_media_licensed` computation already exists. Directly after it, add:

```python
            # Per-photo licence flags. A split row only exports its own photo, so
            # it can be selected on that photo's licence alone -- which lets
            # splitting rescue the licensed photos from an observation that is
            # deselected wholesale under the all-or-nothing rule.
            photo_licensed = [
                bool(license_list[i]) if i < len(license_list) else False
                for i in range(len(photo_list))
            ]
            photo_licensed += [False] * (max_photos - len(photo_licensed))
```

Then in the `obs_data` dict, replace the `'sighting_id'` entry and add two more:

```python
                'sighting_id': row.get('_sighting_id'),
                'initially_split': bool(row.get('_split_eligible')) and len(photo_list) > 1,
                'photo_licensed': photo_licensed,
```

- [ ] **Step 4: Run the tests**

Run: `python3 -m pytest test_export_integrity.py -q -k payload`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add inat-download-new-species-sightings.py test_export_integrity.py
git commit -m "feat: give the review page split state and per-photo licences

Adds sighting_id, initially_split and photo_licensed to the payload so the
browser can own row grouping. No behaviour change yet."
```

---

### Task 3: Build the Node test harness

The generated page's JavaScript has no real test coverage — the only existing check greps for the string `function csvColumnCount`. Task 4 rewrites that JavaScript substantially, so build the harness first.

**Files:**
- Create: `test_review_page_js.py`
- Create: `js_harness/run_page.js`

**Interfaces:**
- Consumes: the generated page from Task 2.
- Produces:
  - `js_harness/run_page.js` — invoked as `node js_harness/run_page.js <page.html> <script.js>`; loads the page's inline script in a `vm` context with a stubbed DOM, runs the assertion script, prints its output.
  - `test_review_page_js.py::run_js(html_path, assertions) -> str` — writes the assertion snippet to a temp file, shells out to node, returns stdout. Skips the test when node is absent.
  - `test_review_page_js.py::build_page(tmp_path, n_photos=4, social_split=False, licenses=None, observations=None)` — generates a real review page. `observations` accepts a list of `{"id": int, "n_photos": int, "licenses": [...]}"` specs for multi-observation fixtures; the scalar form builds a single observation. Tests that assert on ordering or cross-observation behaviour MUST use the list form — a single observation makes such assertions vacuous.

- [ ] **Step 1: Write the harness**

Create `js_harness/run_page.js`:

```javascript
// Runs a generated review page's inline <script> in a stubbed DOM, then runs an
// assertion snippet in the same context. Test-only: the page itself never needs
// node, and must stay self-contained vanilla JS opened over file://.
const fs = require('fs');
const vm = require('vm');

const [pagePath, assertionsPath] = process.argv.slice(2);

const html = fs.readFileSync(pagePath, 'utf8');
const match = html.match(/<script>\n([\s\S]*)\n    <\/script>/);
if (!match) {
  console.error('could not find the inline script block');
  process.exit(1);
}

const created = [];
function makeElement(tag) {
  const el = {
    tagName: tag, style: {}, dataset: {}, children: [], _text: '',
    classList: {
      _set: new Set(),
      add(...c) { c.forEach(x => el.classList._set.add(x)); },
      remove(...c) { c.forEach(x => el.classList._set.delete(x)); },
      contains(c) { return el.classList._set.has(c); },
    },
    appendChild(child) { el.children.push(child); return child; },
    addEventListener() {}, removeAttribute() {}, setAttribute() {},
    querySelectorAll: () => [],
    get textContent() { return el._text; },
    set textContent(v) { el._text = String(v); },
    set innerHTML(v) { if (v === '') el.children = []; },
    checked: false, type: '', className: '', id: '',
  };
  created.push(el);
  return el;
}

const byId = {};
const sandbox = {
  console,
  document: {
    getElementById: id => (byId[id] = byId[id] || makeElement('div')),
    createElement: makeElement,
    addEventListener() {},
    querySelectorAll: () => [],
  },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  alert: () => {},
  // Exposed so assertions can inspect what was rendered.
  __created: created,
  __byId: byId,
};
vm.createContext(sandbox);

vm.runInContext(match[1], sandbox);
vm.runInContext(fs.readFileSync(assertionsPath, 'utf8'), sandbox);
```

- [ ] **Step 2: Write the pytest wrapper and one smoke test**

Create `test_review_page_js.py`:

```python
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
```

- [ ] **Step 3: Run the smoke test**

Run: `python3 -m pytest test_review_page_js.py -q`
Expected: PASS (1 test), or SKIP if node is unavailable. If it fails on the script-block regex, print `html[:200]` from the harness and adjust the pattern to the actual indentation.

- [ ] **Step 4: Commit**

```bash
git add js_harness/run_page.js test_review_page_js.py
git commit -m "test: add a Node harness for the review page's JavaScript

The generated page's JS had no behavioural coverage -- the only check grepped
the HTML for a function name. This loads the inline script in a vm context with
a stubbed DOM so the real functions can be called. Node stays a test-only
dependency and the page stays self-contained; tests skip when node is absent."
```

---

### Task 4: Replace Merge with Split in the page's JavaScript

The substantive task. Replaces the merge machinery with one `splitState` model, derived rows, composite selection keys, and a single export path.

**Files:**
- Modify: `inat-download-new-species-sightings.py:1391` (the `<th>`), `:1435-1524` (merge state, selection, merge column, `toggleMerge`), `:1526-1733` (`renderObservations`), `:1735-1771` (stats and selection), `:1773-1930` (`generateCSV`, `csvColumnCount`)
- Test: `test_review_page_js.py`

**Interfaces:**
- Consumes: `sighting_id`, `initially_split`, `photo_licensed` from Task 2; the harness from Task 3.
- Produces, in the page's JS: `splitState` Map, `isSplit(obs)`, `toggleSplit(observationId)`, `displayRows()`, `rowKey(obs, photoIndex)`, `defaultSelected(obs, photoIndex)`, `isSelected(obs, photoIndex)`, `generateCSV(rows)` taking display rows, `csvColumnCount(rows)`.
- Removed: `mergedSightings`, `mergedBorderColors`, `toggleMerge`, `sightingIdCounts`, `initializeMergeColumn`, the index-keyed `isSelected(index)`.

**Reminder:** this is inside a Python f-string. Every `{` and `}` in the JavaScript below must be **doubled** when written into the file. The code blocks here show the JavaScript as it should appear *in the rendered page*.

- [ ] **Step 1: Write the failing tests**

Add to `test_review_page_js.py`:

```python
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
    page = build_page(tmp_path, observations=[
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m pytest test_review_page_js.py -q`
Expected: FAIL — `toggleSplit is not defined`.

- [ ] **Step 3: Replace the state block**

Delete lines 1435-1438 (`mergedSightings`, `mergedBorderColors` and their comments) and the `mergeColors` palette array. Delete the `sightingIdCounts` block at 1482-1489. Replace the `selectionState` / `defaultSelected` / `isSelected` block (1460-1480) with:

```javascript
// observation_id -> bool. Seeded from initially_split (the flag plus the
// organism-evidence suppression), then owned by the reviewer.
const splitState = new Map();

function isSplit(obs) {
    if (!splitState.has(obs.observation_id)) {
        splitState.set(obs.observation_id, Boolean(obs.initially_split));
    }
    return splitState.get(obs.observation_id);
}

function toggleSplit(observationId) {
    const obs = observations.find(o => o.observation_id === observationId);
    if (!obs || obs.photo_count <= 1) return;
    splitState.set(observationId, !isSplit(obs));
    renderObservations();
    updateStats();
    updateCSV();
}

// One display row per photo when split, otherwise one per observation.
function displayRows() {
    const rows = [];
    observations.forEach(obs => {
        if (isSplit(obs)) {
            // Iterate photo_count, not photos.length: photos and licenses are
            // padded to maxPhotos with nulls and must stay index-aligned.
            for (let i = 0; i < obs.photo_count; i++) rows.push({obs: obs, photoIndex: i});
        } else {
            rows.push({obs: obs, photoIndex: null});
        }
    });
    return rows;
}

// Stable across split toggles, so a deselected photo stays deselected through a
// split -> unsplit -> re-split round trip. The merged row has its own key.
function rowKey(obs, photoIndex) {
    return obs.observation_id + ':' + (photoIndex === null ? 'all' : photoIndex);
}

const selectionState = new Map();

function defaultSelected(obs, photoIndex) {
    // A split row exports only its own photo, so it needs only that photo
    // licensed; a merged row exports all of them and needs all licensed.
    const licensed = photoIndex === null
        ? obs.all_media_licensed
        : Boolean(obs.photo_licensed && obs.photo_licensed[photoIndex]);
    return licensed &&
           !obs.has_non_organism_evidence &&
           !obs.is_skulls_and_bones &&
           obs.quality_grade !== 'needs_id';
}

function isSelected(obs, photoIndex) {
    const key = rowKey(obs, photoIndex);
    if (!selectionState.has(key)) {
        selectionState.set(key, defaultSelected(obs, photoIndex));
    }
    return selectionState.get(key);
}
```

- [ ] **Step 4: Replace `toggleMerge` and the column initialiser**

Delete `initializeMergeColumn` (1500-1506) and `toggleMerge` (1508-1524). Add:

```javascript
function initializeSplitColumn() {
    // Only useful when something can actually be split.
    const header = document.getElementById('split-header');
    if (header && maxPhotos > 1) header.style.display = '';
}
```

Change the `DOMContentLoaded` handler to call `initializeSplitColumn()` unconditionally instead of calling `initializeMergeColumn()` only when `socialSplitMode`.

At line 1391 change the header cell:

```html
<th id="split-header" style="display: none;">Split</th>
```

- [ ] **Step 5: Rewrite `renderObservations` to iterate display rows**

Replace the sort and loop at the top of `renderObservations` (1526 onward). Sort at observation granularity so groups stay adjacent, then expand:

```javascript
function renderObservations() {
    const tbody = document.getElementById('observations-body');
    tbody.innerHTML = '';

    // Rank observations, not rows: expanding after sorting keeps an
    // observation's photos adjacent instead of scattering them.
    const ordered = observations.slice().sort((a, b) => {
        const aSel = anySelected(a), bSel = anySelected(b);
        if (aSel === bSel) return 0;
        return aSel ? -1 : 1;
    });

    let colorIndex = 0;
    ordered.forEach(obs => {
        const split = isSplit(obs);
        const groupClass = (colorIndex++ % 2 === 0) ? 'obs-group-even' : 'obs-group-odd';
        const indices = split ? Array.from({length: obs.photo_count}, (_, i) => i) : [null];

        indices.forEach(photoIndex => {
            const tr = document.createElement('tr');
            if (split) tr.classList.add(groupClass);
            renderRow(tr, obs, photoIndex);
            tbody.appendChild(tr);
        });
    });

    updateStats();
}

function anySelected(obs) {
    if (isSplit(obs)) {
        for (let i = 0; i < obs.photo_count; i++) if (isSelected(obs, i)) return true;
        return false;
    }
    return isSelected(obs, null);
}
```

Move the existing per-row cell building (checkbox, photo, id, date, species, location, GPS, observer, quality, license, photo count) into `renderRow(tr, obs, photoIndex)`, keeping every existing cell and its `textContent` usage. Change only these three things inside it:

```javascript
    // Checkbox: keyed on the composite row key, not an array index.
    checkbox.checked = isSelected(obs, photoIndex);
    checkbox.addEventListener('change', () => {
        selectionState.set(rowKey(obs, photoIndex), checkbox.checked);
        handleCheckboxChange();
    });

    // Photo cell: a split row previews its own photo.
    const photoPath = photoIndex === null
        ? obs.photo_path
        : (obs.all_photo_paths && obs.all_photo_paths[photoIndex]) || null;

    // Photo count cell.
    tdPhotoCount.textContent = photoIndex === null ? obs.photo_count : 1;
```

Then append the Split cell as the last cell, replacing the old merge cell:

```javascript
    // Split / Unsplit control
    const tdSplit = document.createElement('td');
    if (obs.photo_count > 1) {
        const btn = document.createElement('button');
        btn.className = 'btn-split' + (isSplit(obs) ? ' split' : '');
        btn.textContent = isSplit(obs) ? 'Unsplit' : 'Split';
        btn.onclick = () => toggleSplit(obs.observation_id);
        tdSplit.appendChild(btn);
    }
    tr.appendChild(tdSplit);
```

Rename the `.btn-merge` CSS rules to `.btn-split`, and `.btn-merge.merged` to `.btn-split.split`. Delete the `.merged-row` rule.

- [ ] **Step 6: Update selection and stats to use display rows**

Replace `updateStats`, `getSelectedObservations` and `setAllSelected`:

```javascript
function updateStats() {
    const rows = displayRows();
    document.getElementById('total-count').textContent = rows.length;
    document.getElementById('selected-count').textContent =
        rows.filter(r => isSelected(r.obs, r.photoIndex)).length;
    document.getElementById('obscured-count').textContent =
        observations.filter(obs => obs.coordinates_obscured).length;
}

function getSelectedObservations() {
    return displayRows().filter(r => isSelected(r.obs, r.photoIndex));
}

function setAllSelected(value) {
    displayRows().forEach(r => selectionState.set(rowKey(r.obs, r.photoIndex), value));
    renderObservations();
    updateCSV();
}
```

- [ ] **Step 7: Rewrite `generateCSV` for display rows**

Replace the whole `socialSplitMode` grouping block at the top of `generateCSV` (1773 onward) — it takes display rows now, so there is nothing to regroup:

```javascript
function generateCSV(rows) {
    if (rows.length === 0) {
        return 'No observations selected';
    }

    const columnCount = csvColumnCount(rows);
    const headers = [ /* ...unchanged list, through 'photo_filenames'... */ ];
    for (let i = 0; i < columnCount; i++) {
        headers.push(`Encounter.mediaAsset${i}`);
        headers.push(`Encounter.mediaAsset${i}.license`);
    }

    const lines = [headers.join(',')];

    rows.forEach(({obs, photoIndex}) => {
        const photos = photoIndex === null
            ? obs.photos.slice(0, obs.photo_count)
            : [obs.photos[photoIndex]];
        const licenses = photoIndex === null
            ? obs.licenses.slice(0, obs.photo_count)
            : [obs.licenses[photoIndex]];

        // Mode-dependent BY DESIGN -- see the spec, decision 4. With the flag,
        // every row keeps a sighting ID so existing Wildbook imports are
        // unchanged, even a lone row. Do not "simplify" this to isSplit alone.
        const sightingId = (socialSplitMode || isSplit(obs)) ? obs.sighting_id : '';

        const row = [
            escapeCSV(obs.observation_id),
            escapeCSV(obs.observed_on),
            escapeCSV(obs.year),
            escapeCSV(obs.month),
            escapeCSV(obs.day),
            escapeCSV(obs.scientific_name),
            escapeCSV(obs.genus),
            escapeCSV(obs.specific_epithet),
            escapeCSV(obs.common_name),
            escapeCSV(obs.latitude),
            escapeCSV(obs.longitude),
            escapeCSV(obs.location),
            escapeCSV(obs.location_id),
            escapeCSV(obs.living_status),
            escapeCSV(obs.submitter_id),
            escapeCSV('unapproved'),
            escapeCSV(obs.project_name),
            escapeCSV(obs.project_owner),
            escapeCSV(sightingId),
            escapeCSV(obs.observer),
            escapeCSV(obs.quality_grade),
            escapeCSV(obs.url),
            escapeCSV(obs.other_catalog_numbers),
            escapeCSV(obs.researcher_comments),
            escapeCSV(photos.length),
            escapeCSV(photos.join('; '))
        ];

        for (let i = 0; i < columnCount; i++) {
            row.push(escapeCSV(photos[i]));
            row.push(escapeCSV(licenses[i]));
        }

        lines.push(row.join(','));
    });

    return lines.join('\n');
}

function csvColumnCount(rows) {
    // Sized from the rows actually written: an all-split export must not carry
    // empty mediaAsset columns, and a merged one must fit its widest row.
    return Math.max(1, ...rows.map(
        r => r.photoIndex === null ? r.obs.photo_count : 1
    ));
}
```

Keep the existing `headers` array contents exactly as they are — only the `mediaAsset` loop bound changes.

- [ ] **Step 8: Run the JS tests**

Run: `python3 -m pytest test_review_page_js.py -q`
Expected: PASS (9 tests). If you get `Unexpected token` from node, you missed a `{{`/`}}` doubling — run `node --check` on the extracted script to find the line:

```bash
python3 -c "
import importlib.util,re,tempfile,pathlib
spec=importlib.util.spec_from_file_location('m','inat-download-new-species-sightings.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
d=m.iNaturalistDownloader(output_dir=tempfile.mkdtemp(),days_back=1,species_list=['x'])
d.download_photo=lambda u,f:True
d.write_html(d.process_observations([{'id':1,'taxon':{'name':'X'},'observed_on':'2026-01-01','photos':[]}],'x'),'r.html')
p=pathlib.Path(d.output_dir,'r.html').read_text()
pathlib.Path('/tmp/page.js').write_text(re.search(r'<script>\n(.*)\n    </script>',p,re.S).group(1))
" && node --check /tmp/page.js
```

- [ ] **Step 9: Delete the test that asserts the removed merge behavior**

Remove `test_merged_export_column_count_covers_recombined_photos` from
`test_export_integrity.py` entirely. It asserts `"function csvColumnCount" in html`,
which proves nothing about behavior and describes a code path this task just deleted.
`test_deselecting_one_photo_drops_only_that_row_from_the_csv` above covers the real
concern — that column sizing follows the rows actually emitted.

It is deleted here, in the same commit as the code it describes, so every commit on the
branch stays green and the diff is self-consistent.

- [ ] **Step 10: Verify no Python SyntaxWarning and run the full suite**

Run: `python3 -W error::SyntaxWarning -c "import io,ast; ast.parse(io.open('inat-download-new-species-sightings.py',encoding='utf-8').read()); print('clean')"`
Expected: `clean`

Run: `python3 -m pytest -q`
Expected: PASS — no failures. If anything is red, this task is not done.

- [ ] **Step 11: Commit**

```bash
git add inat-download-new-species-sightings.py test_review_page_js.py test_export_integrity.py
git commit -m "feat: add a per-observation Split/Unsplit control to the review page

Replaces the Merge machinery with one grouping model. splitState is seeded
from Python's initially_split and owned by the reviewer thereafter; table rows
are derived from it, so a split observation shows one selectable row per photo
and the reviewer can drop a single bad photo.

Selection keys become composite (observation:photoIndex) so choices survive a
split -> unsplit -> re-split round trip, and sorting ranks observations rather
than rows so a split group never scatters. Split rows are selected on their own
photo's licence, which lets splitting rescue the CC-licensed photos from an
observation deselected wholesale by the all-or-nothing rule."
```

---

### Task 5: Document the control

**Files:**
- Modify: `README.md`
- Test: the full suite

**Interfaces:**
- Consumes: everything above.
- Produces: no code interfaces; documentation only.

- [ ] **Step 1: Confirm the starting state is green**

Run: `python3 -m pytest -q`
Expected: PASS, with more tests than the 34 this branch started at. The stale grep test
was already removed in Task 4 alongside the code it described.

- [ ] **Step 2: Update the README**

In the `--social-split-observations` section, replace the "HTML Review Mode Features" bullet list describing the Merge button with:

```markdown
**HTML Review Mode Features:**

Every observation with more than one photo gets a **Split** button, whether or not
`--social-split-observations` was used. Press it and the row expands into one row per
photo, each with its own checkbox, all sharing one `Sighting.sightingID` so Wildbook
still records them as a single sighting. Deselect any photo to leave it out entirely.
**Unsplit** collapses the rows back together.

- Rows from the same observation are colour-coded (alternating backgrounds) so you can
  see which belong together
- A split row is selected by default if *its own* photo carries a license, so splitting
  is a way to keep the CC-licensed photos from an observation that is otherwise
  deselected because one photo is all-rights-reserved
- `--social-split-observations` now only sets the *starting* state: observations it would
  have split start split, and you can Unsplit any of them
- Split state lives in the page only. Reloading the file starts from the defaults again.
```

Then update the open-question block in that section, appending:

```markdown
> **Partially mitigated:** the per-observation Split button means this suppression is no
> longer the last word — a reviewer can split any observation the flag skipped. The
> question of what the flag's default *should* be is still open.
```

- [ ] **Step 3: Verify the docs match the code**

Run: `grep -c "btn-split\|Unsplit" inat-download-new-species-sightings.py`
Expected: a non-zero count, confirming the README describes shipped behavior.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the per-observation Split control

Every multi-photo observation now gets a Split button regardless of the flag,
so --social-split-observations only sets the starting state."
```

---

### Task 6: End-to-end verification against the live API

Generated-text assertions do not prove the page works in a browser. This task is manual and produces no commit unless it finds a bug.

**Files:** none modified.

**Interfaces:** none.

- [ ] **Step 1: Generate a real page with multi-photo observations**

```bash
mkdir -p /tmp/split-e2e && python3 inat-download-new-species-sightings.py \
  --species "Panthera onca" --days 120 --rate-limit 0.5 \
  --html-review --output /tmp/split-e2e
```

Expected: a run reporting `Maximum photos per observation:` greater than 1. If it is 1, raise `--days` until a multi-photo observation appears — the feature is untestable without one.

- [ ] **Step 2: Check the page structurally**

```bash
python3 - <<'EOF'
import re, glob
html = open(glob.glob('/tmp/split-e2e/*.html')[0], encoding='utf-8').read()
print("script blocks:", html.count('</script>'))
print("split column header:", 'id="split-header"' in html)
print("merge machinery gone:", not any(
    n in html for n in ('mergedSightings', 'toggleMerge', 'sightingIdCounts', 'merged-row')))
print("maxPhotos:", re.search(r'const maxPhotos = (\d+);', html).group(1))
EOF
```

Expected: 1 script block, split header present, merge machinery gone, `maxPhotos` > 1.

- [ ] **Step 3: Open it and exercise the control by hand**

Open the HTML file in a browser. Confirm each of:

- A multi-photo row shows a **Split** button; a single-photo row shows none
- Pressing Split expands it into one row per photo, adjacent, colour-banded, each with its own checkbox and its own photo thumbnail
- The Selected and Total counts change to match
- Deselecting one photo and clicking **Download CSV** produces a file with one row per *remaining* photo, sharing one `Sighting.sightingID`, and no row naming the deselected photo
- Pressing **Unsplit** collapses back to one row carrying all photos, with an empty `Sighting.sightingID`
- Re-splitting restores the earlier per-photo deselection
- The browser console is free of errors throughout

- [ ] **Step 4: Confirm the direct-CSV path is untouched**

```bash
python3 inat-download-new-species-sightings.py --species "Panthera onca" \
  --days 120 --rate-limit 0.5 --output /tmp/split-e2e-csv
python3 -c "
import glob, csv
path = glob.glob('/tmp/split-e2e-csv/*.csv')[0]
rows = list(csv.DictReader(open(path, encoding='utf-8')))
ids = {r['Sighting.sightingID'] for r in rows}
print('rows:', len(rows))
print('sightingID values:', ids)
assert ids == {''}, 'a non-split run must leave Sighting.sightingID empty'
print('OK: non-split CSV unchanged')
"
```

Expected: `OK: non-split CSV unchanged`.

---

## Self-Review

**Spec coverage.** Every section maps to a task: the Python seam and sighting-ID handling to Task 1; the payload additions to Task 2; the browser model, export path and `csvColumnCount` change to Task 4; the JS harness and its seven named behaviors to Tasks 3-4; the three existing-test rewrites to Tasks 1 (two of them) and 4 (the grep, deleted with the code it described); the self-contained-page constraint to Global Constraints; end-to-end verification to Task 6. Decision 4's mode-dependent rule is implemented in Task 4 Step 7 with the required comment, and guarded by `test_merged_row_sighting_id_depends_on_the_flag`. Out-of-scope items are not implemented anywhere, as intended.

**Placeholder scan.** No TBDs. Every code step carries real code. The one abbreviated block — the `headers` array in Task 4 Step 7 — is explicitly marked unchanged, with an instruction to keep the existing contents, because reproducing 26 unchanged lines invites a transcription error.

**Type consistency.** `isSelected` and `defaultSelected` take `(obs, photoIndex)` everywhere after Task 4; the pre-existing index-taking `isSelected(index)` is explicitly listed as removed. `generateCSV` takes display rows (`{obs, photoIndex}`) in both its definition and at the `getSelectedObservations()` call site. `rowKey`, `toggleSplit`, `displayRows`, `anySelected` and `csvColumnCount` are used with the signatures defined. On the Python side `split_rows_by_photo` is module-level and referenced as `mod.split_rows_by_photo` in tests and bare in `run()`, matching how `fetch_json` is already handled. `_sighting_id` and `_split_eligible` are written in Task 1 and read in Task 2 under those exact names.
