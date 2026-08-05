# iNaturalist → Wildbook Import Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the standalone iNaturalist downloader into a Wildbook-served agent skill: a plain-language markdown skill (served from `/api/v3/agent-skill`) that points biologists' AI assistants at the public, MIT-licensed repo to download, curate, and prepare iNaturalist observations for Wildbook bulk import.

**Architecture:** The tool's code stays in the public repo (`github.com/WildMeOrg/inat-download-recent-species-sightings`) as the single source of truth; the skill is a thin guide pinned to a tagged release. One code change lands in the repo (a dedup-ready `Encounter.otherCatalogNumbers` column); everything else is the Wildbook-served markdown skill plus its registration and tests.

**Tech Stack:** Python 3.6+ (standard library only) for the tool; Java 8 + JUnit 5 + Maven for the Wildbook skill tests; Markdown for the skill and index.

## Global Constraints

- **Python: standard library only, 3.6+.** The tool takes no third-party deps except optional Pillow (GIF handling). Do not add dependencies.
- **External-ID format is exactly `iNaturalist:<observation_id>`** — e.g. `iNaturalist:12345678`. Use this verbatim string everywhere it appears (row value, tests, skill prose).
- **Pinned release tag is `v1.0.0`.** The skill references the repo at this exact tag. Cut it (Task 2 handoff) after the repo changes merge.
- **New CSV column header is exactly `Encounter.otherCatalogNumbers`.** Use verbatim in both export paths, tests, and skill.
- **Skill markdown must contain these six section headers verbatim** (the Wildbook content test requires them): `## When to use this`, `## What it does, in plain terms`, `## What you'll need`, `## How to do it`, `## How to report results`, `## Cautions`.
- **Skill frontmatter `name:` must equal the file stem** `inat-to-wildbook-import` (drift test requires it), and the map value must be `inat-to-wildbook-import.md`.
- **No ACL field names anywhere in served markdown:** never write `publiclyReadable`, `submitterUserId`, `submitterUserIds`, `viewUsers`, `editUsers` (the content test fails on these). Note `Encounter.submitterID` is fine — it is a different string.
- **No jargon terms outside the `## How to do it` section:** avoid `embedding`, `vector`, `cosine`, `centroid`, `cluster`, `latent`, `bcubed` (content test strips only the How-to-do-it section before checking).
- **This skill is NOT read-only.** Do not call the shared `assertSkillStructure` helper on it (that helper requires a read-only/worklist promise). Give it its own content test.
- **Copyright holder is `Conservation X Labs`** (matches the repo's existing notice and the committed `LICENSE`).

---

## Task 1: Add the dedup-ready `Encounter.otherCatalogNumbers` column (repo: `inat-download-recent-species-sightings`)

Populate a new `Encounter.otherCatalogNumbers` column with `iNaturalist:<observation_id>` in **both** export paths — the direct CSV writer and the HTML review page's JS-generated CSV — so imported encounters carry a searchable back-reference to their iNaturalist source.

**Files:**
- Modify: `inat-download-new-species-sightings.py` (six edit points below)
- Test: `test_other_catalog_numbers.py` (create)

**Interfaces:**
- Consumes: `iNaturalistDownloader(output_dir, days_back, species_list, ...)` and its `process_observations(observations, species_name) -> List[dict]`, `write_csv(data, filename)`, `write_html(data, filename)`.
- Produces: every exported row carries key/column `Encounter.otherCatalogNumbers` with value `iNaturalist:<observation_id>`.

- [ ] **Step 1: Write the failing test**

Create `test_other_catalog_numbers.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 test_other_catalog_numbers.py`
Expected: FAIL — `KeyError: 'Encounter.otherCatalogNumbers'` from the first test.

- [ ] **Step 3: Add the column value in `process_observations` (both row dicts)**

In `inat-download-new-species-sightings.py`, in the **social-split** row dict, after the line `'url': obs_url,` (~line 638), add:

```python
                        'Encounter.otherCatalogNumbers': f'iNaturalist:{obs_id}',
```

In the **non-split** row dict, after the line `'url': obs_url,` (~line 679), add:

```python
                    'Encounter.otherCatalogNumbers': f'iNaturalist:{obs_id}',
```

- [ ] **Step 4: Add the column to the CSV writer fieldnames**

In `write_csv`, in the `fieldnames` list, after the `'url',` entry (~line 756), add:

```python
            'Encounter.otherCatalogNumbers',
```

- [ ] **Step 5: Add the column to the HTML review export (three edits)**

(a) In `write_html`, in the `obs_data` dict, after `'url': row.get('url'),` (~line 847), add:

```python
                'other_catalog_numbers': row.get('Encounter.otherCatalogNumbers'),
```

(b) In the HTML template's JS `headers` array, after the `'url',` entry (~line 1825), add:

```javascript
                'Encounter.otherCatalogNumbers',
```

(c) In the JS row builder, after `escapeCSV(obs.url),` (~line 1863), add:

```javascript
                    escapeCSV(obs.other_catalog_numbers),
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python3 test_other_catalog_numbers.py`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add inat-download-new-species-sightings.py test_other_catalog_numbers.py
git commit -m "feat: add Encounter.otherCatalogNumbers (iNaturalist:<id>) for Wildbook dedup"
```

---

## Task 2: README pass and release prep (repo: `inat-download-recent-species-sightings`)

Make the repo read well as the skill's reference: document the new column and the Wildbook Bulk Import handoff, scope biologists to the core script, and mark the out-of-scope tooling. Then a human cuts the pinned release.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document the new column in the CSV Format table**

In `README.md`, in the CSV columns table (the `| Column | Description |` table), add a row after the `Encounter.verbatimLocality` row:

```markdown
| Encounter.otherCatalogNumbers | External source reference `iNaturalist:<observation_id>` — lets Wildbook detect whether this observation was already imported |
```

- [ ] **Step 2: Add a "Scope" note near the top of the README**

After the opening paragraph, add:

```markdown
## Scope

The supported, maintained entry point is **`inat-download-new-species-sightings.py`** — the
iNaturalist → Wildbook downloader. The `inat-mcp-server/` directory (YouTube and Flickr search,
experimental CLIP filtering) is legacy and **not** part of the Wildbook import workflow; it is
kept for reference only and may be removed in a future release.
```

- [ ] **Step 3: Add a "Using with Wildbook" note**

After the CSV Format section, add:

```markdown
## Using the output with Wildbook

The generated CSV and `photos/` folder are ready for Wildbook's **Bulk Import** page: upload the
photo folder, then the CSV. Every encounter is written as `unapproved` so your team can verify it
before it enters analyses. The `Encounter.otherCatalogNumbers` column carries an
`iNaturalist:<id>` back-reference so a record can later be recognised as already imported.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document otherCatalogNumbers, Wildbook handoff, and repo scope"
```

- [ ] **Step 5 (human handoff — not an agent action): cut the pinned release**

After Tasks 1–2 are merged to `main` and pushed, a maintainer cuts the tag the skill pins to:

```bash
git tag -a v1.0.0 -m "First release for the Wildbook iNaturalist import skill"
git push origin v1.0.0
```

This tag must exist before the skill (Task 3) is usable in production, because the skill instructs agents to fetch the tool at `v1.0.0`. (The Task 3 tests only assert the tag string is present in the markdown; they do not fetch it, so Task 3 can be written and tested before the tag is pushed.)

---

## Task 3: Add the `inat-to-wildbook-import` served skill (repo: `Wildbook-clean2`)

Create the plain-language skill markdown, register it, list+describe it in the root index (restructured into two groups), and add/adjust the Java content tests. All Wildbook-side changes land together because the drift test fails the moment the skill is registered.

**Files:**
- Create: `src/main/resources/agent-skills/inat-to-wildbook-import.md`
- Modify: `src/main/java/org/ecocean/api/AgentSkill.java` (add one `SKILL_RESOURCES` entry)
- Modify: `src/main/resources/agent-skills/index.md` (restructure into two groups; list+describe the new skill)
- Modify: `src/test/java/org/ecocean/api/AgentSkillContentTest.java` (new content test; update the drift test)

**Interfaces:**
- Consumes: `AgentSkill.SKILL_RESOURCES` (static map, name → filename); the servlet serves any mapped `^[a-z0-9-]+$` name from `/agent-skills/`.
- Produces: a fetchable skill at `GET /api/v3/agent-skill/inat-to-wildbook-import`, listed in `GET /api/v3/agent-skill`.

- [ ] **Step 1: Write the failing tests**

In `AgentSkillContentTest.java`, add this new test method (before the closing brace of the class):

```java
    @Test void inat_to_wildbook_import_is_well_formed() {
        String md = load("/agent-skills/inat-to-wildbook-import.md");
        assertFalse(md.isEmpty(), "inat-to-wildbook-import must be non-empty");
        assertTrue(md.contains("name: inat-to-wildbook-import"),
            "frontmatter name must equal the file stem");
        for (String s : REQUIRED_SECTIONS)
            assertTrue(md.contains(s), "import skill must contain section " + s);
        assertTrue(md.contains("github.com/WildMeOrg/inat-download-recent-species-sightings"),
            "must point at the public repo");
        assertTrue(md.contains("v1.0.0"), "must pin to the released tag");
        assertTrue(md.contains("Encounter.otherCatalogNumbers"),
            "must name the dedup back-reference column");
        assertTrue(md.toLowerCase().contains("bulk import"),
            "must hand off to the Wildbook Bulk Import UI");
        assertNoLeak(md);
        assertNoJargon(userFacingSections(md));
        // it is an import-prep skill, so it must NOT be forced through the read-only template
        assertTrue(load("/agent-skills/index.md").contains("inat-to-wildbook-import"),
            "root index must list the import skill");
    }
```

Then update `catalog_files_and_index_do_not_drift` part (c). Replace:

```java
        java.util.Set<String> keys = new java.util.HashSet<>(AgentSkill.SKILL_RESOURCES.keySet());
        keys.remove("api-reference");
        assertEquals(new java.util.HashSet<>(java.util.Arrays.asList(analytical)), keys,
            "the analytical skills in the map must be exactly the four listed in the index");
```

with:

```java
        assertTrue(AgentSkill.SKILL_RESOURCES.containsKey("inat-to-wildbook-import"),
            "the import-prep skill must be registered");
        java.util.Set<String> keys = new java.util.HashSet<>(AgentSkill.SKILL_RESOURCES.keySet());
        keys.remove("api-reference");
        keys.remove("inat-to-wildbook-import");
        assertEquals(new java.util.HashSet<>(java.util.Arrays.asList(analytical)), keys,
            "the analytical skills in the map must be exactly the four listed in the index");
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `mvn -q -Dtest=AgentSkillContentTest test`
Expected: FAIL — `inat_to_wildbook_import_is_well_formed` fails (resource missing) and `catalog_files_and_index_do_not_drift` fails (`containsKey` false).

- [ ] **Step 3: Create the skill markdown**

Create `src/main/resources/agent-skills/inat-to-wildbook-import.md`:

```markdown
---
name: inat-to-wildbook-import
description: Pull recent iNaturalist sightings of your species, curate them, and prepare them for bulk import into Wildbook.
---

# Get iNaturalist sightings into Wildbook

## When to use this
Use this when the person says things like "get recent iNaturalist observations of my species
ready for Wildbook", "pull last month's jaguar sightings from the Pantanal so I can import them",
or "download weedy seadragon photos from iNaturalist for our catalog."

## What it does, in plain terms
It downloads recent, wild, photographed sightings of the species you name from iNaturalist, keeps
only the ones suitable for photo identification, downloads the photos, and writes a Wildbook
bulk-import spreadsheet plus a folder of photos. It can also make a simple web page for reviewing
the sightings and unchecking any you don't want before import. It only prepares files — you do the
actual import in Wildbook, and you decide what to keep.

## What you'll need
Python 3.6 or newer (standard library only; the Pillow package is needed only if you want animated
GIFs handled). The species name(s), and optionally a place and a number of days back. The Wildbook
`locationID` and `submitterID` you want stamped on the encounters. No iNaturalist account and no
Wildbook token are required — this uses the public iNaturalist API and hands the finished files to
Wildbook's Bulk Import page.

## Where the tool lives
The tool is the public, MIT-licensed repository
`https://github.com/WildMeOrg/inat-download-recent-species-sightings`, pinned to release `v1.0.0`.
Fetch that release — either download `inat-download-new-species-sightings.py` from the `v1.0.0`
tag, or clone the repo and check out `v1.0.0`. Always use the pinned release so results stay
consistent.

## How to do it
1. Get the tool at the pinned release:
   `git clone https://github.com/WildMeOrg/inat-download-recent-species-sightings && cd inat-download-recent-species-sightings && git checkout v1.0.0`
   (or download `inat-download-new-species-sightings.py` from the `v1.0.0` tag).
2. Run it for the person's species and scope. Example:
   `python3 inat-download-new-species-sightings.py --species "Panthera onca" --days 30 --place "Mato Grosso" --use-locationID "MatoGrosso" --use-submitterID "their_wildbook_username" --html-review --output ./inat_data`
   Use `--social-split-observations` for social species where several animals can share one
   observation. Drop `--html-review` to write the CSV directly with no review page.
3. If you made the review page, open it and help the person uncheck low-quality or unlicensed
   sightings; the page keeps good ones checked and sorted to the top. Export the curated CSV.
4. Hand off for import: tell the person to open Wildbook's **Bulk Import** page, upload the
   `photos/` folder, then upload the CSV. Every row is marked `unapproved` so their team verifies
   before anything enters analyses.
5. Each row carries `Encounter.otherCatalogNumbers` set to `iNaturalist:<observation id>`. This is
   the back-reference that lets Wildbook recognise a sighting that was already imported, so keep it
   in the spreadsheet.

## How to report results
Speak plainly. Say, for example, "I found 47 jaguar sightings from the Pantanal in the last 30
days; 39 have open licenses and clear photos and are ready to import." Tell the person where the
CSV and `photos/` folder are, how many rows the spreadsheet has, and the exact next step (upload
the photos then the CSV on Wildbook's Bulk Import page). Never say anything was imported — you only
prepared the files.

## Cautions
Respect iNaturalist licenses: sightings whose photos have no open license are flagged and left
unchecked — do not import them without the owner's permission. The tool is polite to iNaturalist's
servers (about one request per second); large pulls take a few minutes. Everything is stamped
`unapproved` for the team's own review. This skill cannot import for you and cannot change anything
in Wildbook — the person does the upload.

## Additional references
- Tool source (MIT): https://github.com/WildMeOrg/inat-download-recent-species-sightings (release `v1.0.0`)
```

- [ ] **Step 4: Register the skill in `AgentSkill.java`**

In `src/main/java/org/ecocean/api/AgentSkill.java`, in the `SKILL_RESOURCES` static block, after the `review-id-problems` entry, add:

```java
        m.put("inat-to-wildbook-import", "inat-to-wildbook-import.md");
```

- [ ] **Step 5: Restructure `index.md` into two groups and list+describe the new skill**

Replace the contents of `src/main/resources/agent-skills/index.md` with:

```markdown
# Wildbook Helper — Toolbox

These tools help you work with your animal photo-ID catalog in two ways: **check and tidy** the
catalog you already have, and **get new sightings into** it. Each tool's page tells your assistant
exactly what to do; you review and make the final decisions in Wildbook.

## What you'll need

Most tools here need a short-lived access token from Wildbook. In Wildbook, open your account menu
and choose **API Access** to create one, then paste **only that token** to your assistant — never
your username or password. The token has an expiration date that may vary by Wildbook; create a
fresh one when it stops working. Full technical detail is in the **api-reference** page (fetch
`/api/v3/agent-skill/api-reference`). The import-prep tools below are the exception — they need no
token, because they only prepare files you upload yourself.

## Check and tidy your catalog (read-only — the tools only suggest; you make the changes in Wildbook)

| Tool | Use this when you want to… | Fetch |
|---|---|---|
| find-missed-matches | check whether the same animal was recorded twice under different names | `/api/v3/agent-skill/find-missed-matches` |
| find-misfiled-sightings | check whether any sightings are filed under the wrong animal | `/api/v3/agent-skill/find-misfiled-sightings` |
| how-good-is-our-matching | understand how reliable the automatic matching is for a species or site | `/api/v3/agent-skill/how-good-is-our-matching` |
| review-id-problems | go through suspected ID problems photo-by-photo and build a to-do list | `/api/v3/agent-skill/review-id-problems` |

## Get sightings into Wildbook (import prep — no token needed)

| Tool | Use this when you want to… | Fetch |
|---|---|---|
| inat-to-wildbook-import | pull recent iNaturalist sightings of your species and prepare them for bulk import | `/api/v3/agent-skill/inat-to-wildbook-import` |

## How this works

When you describe one of the tasks above to your AI assistant, it fetches that tool's page and
follows the steps there. Each page tells the assistant exactly what to look up or run and how to
show you what it finds — so you can review and decide.

## Additional references

These tools are only a subset of the data management and scientific analysis tasks you can do with
this API and Wildbook. For more information about Wildbook, see:
- [Wildbook Documentation](https://wildbook.docs.wildme.org/)
- [Wildbook Community](https://community.wildme.org/)
- [How I AI by Wildbook User Dr. Simon Pierce](https://github.com/simonjpierce/how-i-ai)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `mvn -q -Dtest=AgentSkillContentTest test`
Expected: PASS — all methods green, including `inat_to_wildbook_import_is_well_formed`, `catalog_files_and_index_do_not_drift`, and the unchanged `index_is_plain_language_and_lists_the_four_tools` (index still contains the four names, "read-only", "api-reference", and "API Access").

- [ ] **Step 7: Commit**

```bash
git add src/main/resources/agent-skills/inat-to-wildbook-import.md \
        src/main/resources/agent-skills/index.md \
        src/main/java/org/ecocean/api/AgentSkill.java \
        src/test/java/org/ecocean/api/AgentSkillContentTest.java
git commit -m "feat(agent-skills): add inat-to-wildbook-import served skill"
```

---

## Handoff / follow-ons (not agent tasks)

- **Cut `v1.0.0`** on the tool repo (Task 2, Step 5) before announcing the skill.
- **Open the Wildbook PR** for Task 3 against the appropriate branch.
- **Decide the fate of `inat-mcp-server/`** (YouTube/Flickr/CLIP): trim from the repo or leave marked non-core (README already flags it). Out of scope for this plan.
- **Future:** live dedup (skill queries `POST /api/v3/search/encounter` on `otherCatalogNumbers` before export); a write-scoped token for true agentic push; converting `wildbook-import` to the same served-skill model.

## Self-review notes

- **Spec coverage:** delivery model (Task 3), core scope only (README scope note, Task 2), point-at-repo/no inline code (Task 3 skill body + tests), MIT license (done during design), dedup-ready column (Task 1), root index lists+describes with two groups and per-group token note (Task 3, Step 5), Wildbook registration + tests + drift-test update (Task 3), disposition/release (Task 2 + handoff). All covered.
- **Placeholder scan:** none — the pinned tag (`v1.0.0`) and external-ID format (`iNaturalist:<id>`) are fixed in Global Constraints and used verbatim.
- **Type/string consistency:** `Encounter.otherCatalogNumbers`, `iNaturalist:12345678`, `inat-to-wildbook-import`, and `v1.0.0` are used identically across the Python edits, the Python test, the skill markdown, and the Java tests.
