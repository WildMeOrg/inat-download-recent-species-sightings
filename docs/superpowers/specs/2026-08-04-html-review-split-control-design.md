# Per-observation Split/Unsplit control in the HTML review page

**Date:** 2026-08-04
**Status:** Design — approved

## Problem

A single iNaturalist observation sometimes contains photos of **different individuals**.
Today the reviewer has no way to say so at review time. The only lever is the
`--social-split-observations` command-line flag, which is decided before the page is
generated and applies to the whole run:

- **Without the flag**, a multi-photo observation always exports as one Encounter carrying
  every photo — so several individuals get collapsed into one animal.
- **With the flag**, every qualifying multi-photo observation is split, whether or not the
  photos actually show different individuals. The review page offers a per-group **Merge**
  button to undo that, but only in this direction.

A user has asked for the opposite direction: reviewing without the flag, be able to press
**Split** on the specific observation that needs it, and undo it if the judgement was wrong.

There is a second reason to want this. The flag suppresses splitting for observations
annotated *Evidence of Presence: Organism*, on the mistaken belief that the annotation means
"one individual". It does not — it only means the evidence is the animal itself rather than a
track or scat (see the open question in `README.md`). Because most wild-animal observations
carry that annotation, the flag under-splits badly. A per-observation control gives the
reviewer a direct override and makes the flag stop being the only lever.

## Outcome

A reviewer opening the generated HTML page can press **Split** on any observation with more
than one photo. Its row expands into one row per photo, each independently selectable, all
sharing one `Sighting.sightingID` so Wildbook still knows they are one sighting. **Unsplit**
collapses it back. This works in both flag modes; the flag now only chooses the *starting*
state.

## Decisions taken

Recorded because each closed off a real alternative:

1. **One row per photo only.** No arbitrary photo grouping (no "photos A+B are individual 1,
   C+D are individual 2"). A 4-photo observation showing 2 individuals splits to 4 rows or
   stays at 1. Arbitrary grouping needs per-photo assignment UI and is deferred until the
   simple version has been used in anger.

   > **Amended after the final whole-branch review.** "Photo" here means an iNaturalist
   > photo, and the code counted *files*. An animated GIF is one photo that
   > `extract_gif_frames` turns into N JPEGs, so a 30-frame GIF was offering a Split button
   > that produced 30 Encounters of one animal at one instant. Grouping a split row's frames
   > together would contradict the export table below (a split row is exactly one media
   > asset), so such observations are simply not splittable, in either mode. They export as
   > one Encounter carrying every frame, which is what the default mode already does.
2. **Split expands the table, and each row is independently selectable.** The reviewer can
   drop one bad photo and keep the rest. This is deliberately *not* symmetric with the
   existing Merge button, which only affects the export.
3. **Sighting IDs are pre-generated in Python**, carried as an internal `_sighting_id`, and
   promoted to the `Sighting.sightingID` column only when a row is split. Avoids depending on
   `crypto.randomUUID` in a `file://` page, stays deterministic for tests, and keeps
   unsplit output byte-identical to today.
4. **A lone row in a `--social-split-observations` run keeps its sighting ID.** The cleaner
   semantic rule ("a Sighting only means something when it groups 2+ Encounters") was
   rejected in favour of not changing existing Wildbook imports. The cost is that the export
   rule is mode-dependent, which must stay commented so it is not "tidied up" later.
5. **`node` becomes a soft test-suite dependency**, skipped when absent. It is for the test
   harness only.

## Hard constraint: the page stays self-contained

The generated review page is a single `.html` file a biologist opens over `file://`. It must
remain inline vanilla JavaScript with **no build step, no npm, no modules, and no external
requests**. The Node test harness only extracts the inline `<script>` text to exercise it; it
is never part of producing or shipping the page.

## Architecture

### Python: splitting becomes a seam, not a branch

`process_observations()` currently contains two nearly identical 34-key row literals — one per
branch of `if self.social_split`. The key sets are identical; they differ only in
`photo_count`, `photo_filenames`, `_photo_list`, `_license_list` and `Sighting.sightingID`.
That duplication is a hazard for exactly the work coming next (adding Wildbook columns).

`process_observations()` stops splitting and always emits **one row per observation**.
Splitting moves into a pure function applied afterwards, only on the direct-CSV path:

```
run():
  process_observations()   -> one row per observation, always
  deduplicate_rows()       -> now only ever sees whole observations
  html_review?
    yes -> write_html(rows)                              # browser owns grouping
    no  -> social_split ? split_rows_by_photo(rows) : rows -> write_csv()
```

This ordering matters beyond tidiness. The bug fixed in `8c70595` — deduplication collapsing
split rows because it keyed on `observation_id` — was caused by dedup running *after*
splitting. It now cannot: dedup only ever sees one row per observation. The composite
`(observation_id, photos)` key stays as a cheap guard.

> **Amended after the final whole-branch review.** That last sentence was wrong and the
> composite key was removed. It is not a cheap guard but a strictly weaker one: two passes
> over the same observation need not agree on its photo list (one transient photo-download
> failure is enough), and both rows then survive as duplicate Encounters sharing media that
> self-matches in Wildbook. `deduplicate_rows` keys on `observation_id` alone and keeps the
> row with the most photos.

`split_rows_by_photo(rows)` owns the split decision, including the organism-evidence
suppression, and is a pure rows→rows function with no API or filesystem access — testable in
a way the inline branch never was.

### Payload additions

`write_html()` adds two fields per observation:

- `sighting_id` — the pre-generated UUID (read from `_sighting_id`, not from the
  `Sighting.sightingID` column, which is empty at this point)
- `initially_split` — whether the flag *and* the organism-evidence suppression would have
  split this observation. Keeps the biology logic in Python, in one place; the browser only
  holds state.

`initially_split` and sighting-ID emission are independent, which is easy to misread. A
single-photo observation in a `--social-split-observations` run has `initially_split === false`
(there is nothing to split, and its Split button is hidden) yet still exports a sighting ID,
because the export rule keys on `socialSplitMode`, not on split state. That is decision 4
working as intended, not an inconsistency.

### Browser: one grouping model

```js
// observation_id -> bool. Seeded from obs.initially_split, then the reviewer owns it.
const splitState = new Map();
```

The table stops being 1:1 with `observations` and is derived:

```js
function displayRows() {          // [{obs, photoIndex}] — photoIndex null when merged
  const rows = [];
  observations.forEach(obs => {
    if (isSplit(obs)) {
      // Iterate photo_count, NOT obs.photos.length: photos and licenses are both
      // padded to maxPhotos with nulls, and filtering the nulls out would break
      // the index pairing between the two arrays.
      for (let i = 0; i < obs.photo_count; i++) rows.push({obs, photoIndex: i});
    } else {
      rows.push({obs, photoIndex: null});
    }
  });
  return rows;
}
```

Consequences, each handled explicitly:

- **Selection keys become composite**: `${observation_id}:${photoIndex ?? 'all'}`, replacing
  the flat index into `observations`. Selections then survive a split→unsplit→re-split round
  trip: deselect photo C, unsplit, re-split, and C is still deselected. The merged row keeps
  its own independent `:all` key, so collapsing does not inherit per-photo choices.
- **Sorting moves to observation granularity.** Selected-first still applies but ranks
  observations, then expands their photos in order, so a split group never scatters.
- **Default selection improves for split rows.** A merged row keeps today's rule (requires
  `all_media_licensed`); a split row only requires *its own* photo to be licensed. Splitting
  therefore rescues the CC-licensed photos from an observation that was deselected wholesale
  because one photo was all-rights-reserved.
- **Stats count displayed rows**, so Total moves when splitting. Obscured stays
  observation-based.

Removed rather than kept alongside: `mergedSightings`, `mergedBorderColors`, `toggleMerge()`,
`sightingIdCounts`, and the `.merged-row` styling. The `merge-header` `<th>` becomes a Split
column, shown when `maxPhotos > 1` instead of being gated on the flag. The existing
`obs-group-even/odd` alternating colours are reused to show which rows share an observation.
The button renders only for observations with more than one photo.

### Export

`generateCSV()` collapses to a single path over the selected display rows:

| | merged row | split row |
|---|---|---|
| media assets | all photos → `mediaAsset0..N-1` | that photo → `mediaAsset0` |
| `photo_count` | N | 1 |
| `photo_filenames` | joined | that one filename |
| `Sighting.sightingID` | `socialSplitMode ? id : ''` | `id` |

The sighting-ID rule is `socialSplitMode || isSplit(obs)`, which is mode-dependent by
decision 4 above and must carry a comment saying so.

`csvColumnCount()` changes from "floor at `maxPhotos`" to "max over the rows actually
emitted, floored at 1" — otherwise an all-split export carries N−1 empty column pairs. This
is behaviour-neutral for both modes today, since split mode's `maxPhotos` is already 1.

## Testing

The feature is almost entirely browser logic, and **the browser logic currently has no real
coverage**: the one existing test greps the generated HTML for the string
`function csvColumnCount`, which proves nothing about behaviour.

### JS harness (new)

Formalise the throwaway harness used during the code review: load the generated page's inline
`<script>` into Node's `vm` with a stubbed DOM, then call the real functions. Invoked from
pytest, `pytest.skip` when `shutil.which('node')` is None.

- Split expands to N display rows; Unsplit collapses back to 1
- Selection survives split → unsplit → re-split
- Deselecting one photo drops only that row; the rest keep the shared sighting ID
- Merged rows emit no sighting ID without the flag, and one with it
- Column count shrinks to 1 when everything is split
- Split rows stay adjacent after sorting
- No Split button on single-photo observations

### Python

- `split_rows_by_photo`: N photos → N rows, one photo each, shared sighting ID, other fields
  preserved; organism-evidence suppression respected; single-photo observations untouched
- `process_observations` returns one row per observation in **both** flag modes
- `deduplicate_rows` over whole observations
- Regression guards on the two promises above: non-split CSV leaves `Sighting.sightingID`
  empty; split-mode CSV populates it on **every** row

### Existing tests to rewrite

They assert the old seam and will fail by construction:

- `test_export_integrity.py::test_dedup_keeps_every_social_split_row` → retarget at
  `split_rows_by_photo`, and assert dedup keeps one row for the unsplit case
- `test_export_integrity.py::test_merged_export_column_count_covers_recombined_photos` →
  replace the `csvColumnCount` string grep with the behavioural JS test
- `test_export_integrity.py::test_both_export_paths_emit_the_same_columns` → **keep as-is**

### End-to-end

Run against the live API with a multi-photo species and open the page in a browser — press
Split, deselect a photo, press Unsplit, export, and inspect the CSV. Generated-text
assertions do not prove the page works.

## Out of scope

- Arbitrary photo grouping within an observation (decision 1) — the data model keeps
  `splitState` per observation, so adding it later is a change, not a rewrite
- Persisting review decisions between page loads; `splitState` is browser-session only, as
  `mergedSightings` is today
- Any change to `--social-split-observations` on the direct-CSV path (no `--html-review`)
- Resolving the `README.md` open question about the organism-evidence suppression. This
  design makes it survivable by giving the reviewer an override; it does not change the
  flag's behaviour.
