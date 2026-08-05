# iNaturalist → Wildbook import, as a served agent skill

**Date:** 2026-07-22
**Author:** Jason (jason@wildme.org)
**Status:** Design — pending approval

## Problem

This repo (`inat-download-recent-species-sightings`) is a standalone Python tool that
downloads recent iNaturalist observations for target species, filters them for photo-ID
quality, downloads the photos, and writes a Wildbook bulk-import CSV (plus an optional
interactive HTML review page). It works, but it is unmaintained, and it now overlaps with
Wildbook's new **agentic access** model: Wildbook serves plain-language "agent skills" as
markdown over HTTP that any AI assistant (Claude/Codex) can fetch and follow, backed by a
read-only scoped-search token API.

We want to migrate this tool from a standalone repo into that model: a skill a biologist's
AI assistant can discover and use to get iNaturalist data, review it, and prepare it for
bulk import into Wildbook — without shipping a maintained, distributable executable.

## Goals

1. Preserve the tool's crown-jewel logic: captive exclusion, license/quality/evidence-type
   filtering, Skulls-and-Bones exclusion, social-species split, GIF-frame extraction, and
   the exact Wildbook bulk-import column mapping.
2. Deliver it as a **markdown agent skill served from Wildbook**, consistent with the
   existing `find-missed-matches` / `review-id-problems` skills.
3. Keep the implementation in the **public, MIT-licensed repo** as the single source of
   truth; the skill points at a pinned release and teaches the agent how to use it — no
   bundled/shipped script and no inline code copy to keep in sync.
4. Make records **dedup-ready** by writing the iNaturalist observation ID into
   `Encounter.otherCatalogNumbers` in the output CSV.

## Non-goals (this version)

- **YouTube tools, Flickr tools, CLIP image filtering** — dropped from scope. They are
  separate concerns from the iNat→Wildbook flow and out of scope for this migration.
- **The MCP server** (`inat-mcp-server/`) — not carried forward. The served-markdown skill
  replaces it.
- **Live duplicate detection** — deferred. We add the `otherCatalogNumbers` column now so
  records become dedup-able, but the skill does not yet query Wildbook to flag existing
  imports. (See Future work.)
- **Programmatic push into Wildbook** — not possible with the agent token and out of scope.
  See "Import path" below.

## Key constraints discovered

- **The agent bearer token is read-only.** Verified in `Wildbook-clean2/src/main/webapp/
  WEB-INF/web.xml`: the token filter (`tokenAuthSearch`) is mapped only to
  `/api/v3/search/**` and `/api/v3/media/resolve`. `/api/v3/bulk-import` is gated by `authc`
  (session/form auth). `WildbookTokenAuthenticationFilter` **deliberately does not create a
  session** ("a login on a bearer request could mint a session reusable on write endpoints").
  There is no token→session exchange. So an agent cannot push a bulk import with the token.
- **Dedup is feasible later without new platform work.** `Encounter.otherCatalogNumbers` is
  indexed into OpenSearch and searchable via `POST /api/v3/search/encounter` — it is even
  retained in the restricted no-access field set. Storing the iNat observation ID there makes
  "have I already imported this?" answerable through the read-only token API.
- **Skills register via a fixed map.** `AgentSkill.java` serves markdown from
  `src/main/resources/agent-skills/` keyed by a `SKILL_RESOURCES` map (name validated
  `^[a-z0-9-]+$`, never path-concatenated). Adding a skill = add a resource file + one map
  entry + an `index.md` row. `index.md` is not itself fetchable.

## Delivery model

A single markdown skill, `inat-to-wildbook-import`, served from Wildbook's agent-skill
endpoint at `GET /api/v3/agent-skill/inat-to-wildbook-import`, alongside the existing skills.

The skill is a thin, plain-language guide. The **implementation stays in the public,
MIT-licensed repo** (`github.com/WildMeOrg/inat-download-recent-species-sightings`), and the
skill points the agent at a **pinned release/tag** of it, with the context needed to run it,
curate the results, and prepare the import.

Rationale (why served markdown pointing at the public repo, not inline code or a repo-cloned
MCP skill):

- **Discoverability.** Any agent that reads `GET /api/v3/agent-skill` finds it — no MCP
  install step. The skill tells the agent where the tool lives and how to fetch it.
- **Single source of truth.** The tool's logic lives in exactly one place — the public repo,
  maintained normally. There is no inline copy in the markdown to drift out of sync, and no
  regeneration of subtle filtering logic (evidence-of-presence annotation IDs, project 488,
  social-split) that could silently corrupt it.
- **No malware/maintenance surface.** The skill markdown is inert text; the code is a normal
  public open-source repo that the user — and any scanner — can inspect. Nothing is bundled,
  installed, or signed. The agent fetches the published script (or clones the repo) and runs
  it transparently in the user's session, under the user's approval.
- **Reproducibility.** Everyone runs the *same published* script, and the skill references a
  **pinned tag** rather than `main`, so the tool can evolve without breaking biologists
  mid-workflow.

Trade-off and its mitigation: the skill now depends on the external repo staying available
and stable. **Mitigations:** the repo is under `WildMeOrg` (Wild Me controls it), and the
skill pins to a tagged release; if the repo is ever renamed or moved, the skill's link is the
one thing to update.

## Skill content and structure

The file follows the house style of the existing agent-skills (frontmatter + these sections):

- **Frontmatter:** `name: inat-to-wildbook-import`, one-line `description`.
- **When to use this** — "get recent iNaturalist sightings of my species ready to import into
  Wildbook", "pull last month's jaguar observations from the Pantanal for bulk import".
- **What it does, in plain terms** — queries iNaturalist for recent, wild, photographed
  observations of the target species; keeps only records suitable for photo-ID; downloads the
  photos; writes a Wildbook bulk-import CSV + a flat photo folder; optionally an HTML review
  page for the biologist to curate before import. It only prepares files — the biologist does
  the actual upload in Wildbook.
- **What you'll need** — Python 3.6+ (standard library only for the core; Pillow only if GIF
  handling is wanted), the target species name(s), optional place and date range, and the
  Wildbook `locationID` / `submitterID` to stamp on the encounters. No iNaturalist account or
  key is required (public API).
- **How to do it** — numbered steps the agent follows: fetch the tool from the pinned release
  of the public repo (raw download of `inat-download-new-species-sightings.py`, or
  `git clone` at the tag); run it with the chosen parameters (species, `--days`, optional
  `--place`, `--use-locationID`, `--use-submitterID`, `--social-split-observations`,
  `--html-review`); open the HTML review (if generated) for the biologist to deselect
  low-quality records; then upload the resulting CSV + photo folder through Wildbook's
  **Bulk Import UI**.
- **Where the tool lives** — the pinned repo URL and how to fetch it, plus a one-line note
  that the script is Python-3.6+ standard-library only (Pillow needed only for GIF handling).
- **How to report results** — plainly: how many observations were found, how many passed
  filters, how many photos, where the CSV and photos are, and the exact next step (Bulk Import
  UI). Never claim anything was imported.
- **Cautions** — respects iNaturalist licenses (unlicensed photos are flagged/deselected);
  rate-limited to be a good API citizen; all encounters are stamped `unapproved` for the
  team's own verification; the token cannot import for you.
- **Additional references** — link to the origin repo/commit for provenance.

## The tool (stays in the repo, unchanged except for the dedup column)

The skill relies on the existing `inat-download-new-species-sightings.py`
(`iNaturalistDownloader` class) in the public repo. No logic is copied out; the only code
change is the dedup-ready column below, made **in the repo**. The pieces the skill exercises:

- `search_species` / `resolve_place` — name → iNaturalist taxon/place IDs.
- `get_observations` — paged query with `captive=false`, `has[]=photos`,
  `quality_grade=any`, date window, optional `place_id`.
- `process_observations` — coordinate/annotation parsing; living-status and
  evidence-of-presence detection (`controlled_attribute_id 22`, values 24 = organism/single-
  subject, 19 = dead, 14 = alive); Skulls-and-Bones project ID 488 detection; social-split
  with shared `Sighting.sightingID`.
- `download_photo` / `extract_gif_frames` — photo download and animated-GIF → static-frame
  extraction (Pillow, optional).
- `write_csv` / `write_html` — the Wildbook column mapping and the interactive review page.

## Output format change (dedup-ready)

The exporter in the repo (`write_csv` / `process_observations`) gains one column:
**`Encounter.otherCatalogNumbers`**, populated with the iNaturalist observation ID (e.g.
`iNaturalist:12345678` or the observation URL — exact token format to be finalized in the
plan). This is the field Wildbook indexes and exposes to the token search API, so a future
version can ask "is this observation already in the catalog?" by searching
`POST /api/v3/search/encounter` on `otherCatalogNumbers`. No live query is built in this
version; only the column is added. This is the one code change this migration makes to the
public repo.

The iNat ID currently lands only in a plain `observation_id` column and in
`Encounter.researcherComments` (as a URL) — neither round-trips into a searchable Wildbook
field, which is why the new column is required for dedup to be possible later.

## Import path

The skill stops at **prepare validated files → biologist uploads via the Bulk Import UI**.
This matches the existing `wildbook-import` skill and stays within the read-only token model.
Programmatic push is not offered: the token is read-only by design, and doing a session-cookie
login would mean the agent handling the biologist's real credentials — a much larger security
surface. If true agentic push is wanted later, the clean path is platform work (a write-scoped
token variant that `bulk-import` accepts), noted as future work — not something this skill
should work around.

## Wildbook integration

- Add `src/main/resources/agent-skills/inat-to-wildbook-import.md`.
- Add one entry to `SKILL_RESOURCES` in `AgentSkill.java`:
  `m.put("inat-to-wildbook-import", "inat-to-wildbook-import.md");`
- Update the root skill (`agent-skills/index.md`) so it **lists and describes** the new skill
  (see "Root index changes" below) — not just a bare row.
- Extend the agent-skill content test (`AgentSkillContentTest.java`) to cover the new file,
  following the existing pattern.

### Root index changes (`/api/v3/agent-skill` → `index.md`)

The root index is the entry point every agent fetches first, so the new skill must be
discoverable and described there. The current index frames the whole toolbox as read-only
catalog hygiene ("Everything here is **read-only**") and presents an access token as
universally required. An import-prep skill breaks both assumptions — it *gets data into*
Wildbook rather than analyzing the existing catalog, and it needs no token (it uses the
public iNaturalist API and hands off to the Bulk Import UI). So the index needs a light
restructure, not just an appended row:

1. **Reframe the intro.** Broaden it from "check and tidy up your catalog" to cover both
   purposes, and scope the "read-only" promise to the catalog-hygiene group specifically
   rather than the whole toolbox.
2. **Split "The toolbox" into two labelled groups:**
   - *Check and tidy your catalog (read-only, needs a token)* — the existing four skills,
     unchanged.
   - *Get sightings into Wildbook (import prep)* — `inat-to-wildbook-import`, described in one
     plain-language line (e.g. "pull recent iNaturalist sightings of your species and prepare
     them for bulk import") with its fetch path `/api/v3/agent-skill/inat-to-wildbook-import`.
     This is the group `wildbook-import` joins when it is converted (Future work).
3. **Make the token requirement per-group, not universal.** Keep the "What you'll need"
   token guidance for the read-only group, but note that the import-prep tools don't require a
   token — they produce files you upload yourself in Wildbook.

Every new skill must appear in the index **with a description**, matching the existing rows'
"Use this when you want to…" phrasing, so an agent scanning the root can pick the right tool.

## Disposition of this repo

This repo is now the **canonical home** of the tool: public, MIT-licensed
(`github.com/WildMeOrg/inat-download-recent-species-sightings`), and the single source of
truth the served skill points at. It is not retired. Migration tasks here:

- **License:** add `LICENSE` (MIT, Conservation X Labs) and replace the README's
  "All rights reserved" notice with an MIT reference. *(Done during design.)*
- **Cut a tagged release** for the skill to pin to (after the `otherCatalogNumbers` change and
  a README pass), so biologists always run a stable version.
- **Scope the public surface.** The repo still carries the YouTube tools, Flickr tools, CLIP
  filtering, and MCP server, which are out of scope for this workflow. Decide at plan time
  whether to trim them or clearly mark them non-core in the README; at minimum the skill
  points biologists only at `inat-download-new-species-sightings.py`, not the extra tooling.
- **README pass** so the repo reads well as the skill's reference (usage, the new column, the
  Wildbook Bulk Import handoff).

`wildbook-import` (the sibling skill, currently an MCP-backed skill in the `claude-skills`
repo) is a natural candidate to move to the same "served skill pointing at a public repo"
model next, but that is a separate follow-on, not part of this migration.

## Future work

- **Live dedup:** the skill queries `POST /api/v3/search/encounter` on
  `otherCatalogNumbers` before export and flags/omits already-imported observations.
- **Write-scoped token / agentic push:** platform enhancement so an agent can submit the bulk
  import directly instead of handing off to the UI.
- **Convert `wildbook-import` to a served skill**, co-locating the two data-prep skills.

## Testing

- `AgentSkillContentTest.java` — assert the new skill is fetchable, has frontmatter, and
  contains the expected sections (mirror the existing skills' assertions). Optionally assert
  the skill references the pinned repo URL so a broken/blank link is caught in CI.
- Tool smoke test **in this repo**: run the script against a known species/place with a short
  date window; confirm it produces a CSV with the expected columns (including
  `Encounter.otherCatalogNumbers`) and downloads photos. Lives here, since this repo owns the
  implementation and Wildbook only serves inert markdown.
