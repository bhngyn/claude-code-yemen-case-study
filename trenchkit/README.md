# trenchkit: screening a region for linear military earthworks with Sentinel-1 and Sentinel-2

`trenchkit` turns a region definition into a ranked, reviewable list of candidate trenches, berms and ditches, and scores itself against hand-labelled
lines (a Google Earth KMZ) so that every new region also improves the detector. It packages the Tihama (Hays / Al-Fazah) work of September 2026,
where the labels in `Yemen identified trenches.kmz` (185 km in four complexes) were used to measure and redesign the signatures.

* Inputs: Sentinel-2 L2A (AWS earth-search, no account), Sentinel-1 RTC (Microsoft Planetary Computer, no account), Esri Wayback (public tiles).
* Runs on the 8 GB M2 with `/usr/bin/python3` (numpy, scipy, opencv, scikit-image, rasterio, Pillow, matplotlib, scikit-learn).
* Everything is a CLI stage writing into `work/<region>/`; every stage is resumable. Outputs are a KML for Google Earth and an offline review HTML.

## Quick start for a new region

```bash
cd /Volumes/T7/yemen-maps/trenchkit
cp regions/template.json regions/marib_west.json       # edit: name, centre/radius or bbox, epochs, before/after
PYTHONPATH=. /usr/bin/python3 -m trenchkit.run regions/marib_west.json --labels /path/to/labels.kmz   # --labels is optional
```

Then open `work/marib_west/candidates/fused.kml` in Google Earth and `work/marib_west/review/fused_review.html` in a browser.
Individual stages (same order as `run`):

| stage | command | what it does | time (100 km disk) |
|---|---|---|---|
| grid | `python -m trenchkit.grid R.json` | UTM 10 m grid snapped to the S2 20 m grid, `grid.json` | seconds |
| labels | `python -m trenchkit.labels R.json file.kmz` | KMZ/KML lines to a raster of line ids + `lines.json` (length, azimuth, straightness) | seconds |
| fetch_s2 | `python -m trenchkit.fetch_s2 R.json [epoch ...]` | per-epoch, per-tile median composites of the lowest-cloud scenes, SCL-masked, water/veg masks | 1 to 3 h for 6 epochs |
| fetch_s1 | `python -m trenchkit.fetch_s1 R.json [epoch ...]` | per relative orbit and polarisation, mean of up to 20 full-coverage dates per epoch, in dB, resumable per date | 0.2 MB/s today: 20 to 30 min per date, i.e. 10+ h per orbit |
| detect | `python -m trenchkit.detect R.json [signature ...]` | the signature maps below, tiled; co-registers S1 to S2 first | 60 to 90 min |
| fuse | `python -m trenchkit.fuse R.json [map ...]` | per map: hysteresis at its own background p97/p99.7, skeletons, lines >= 900 m; union of the maps' components (duplicates dropped), attributes from every map, hand score, KML; label hit/miss summary if labels exist | 5 min per map |
| features | `python -m trenchkit.features R.json` | per-component cross-section profiles in every epoch and orbit -> feature vector | 10 min |
| rank | `python -m trenchkit.rank R.json` (or `--apply model.json`) | learned ranker (logistic + gradient boosting) with leave-one-group-out validation, or apply a saved model from another region | 1 min |
| review | `python -m trenchkit.review R.json fused 100` | offline HTML: chips per epoch/orbit, attributes, verdict boxes (export as JSON) | 5 min |
| wayback | `python -m trenchkit.wayback R.json fused 40` | Esri Wayback before/after frames (0.3 to 0.6 m) around the top candidates, drawn into the review page on the next `review` run | 1 to 2 min per candidate |
| evaluate | `python -m trenchkit.evaluate R.json` | recall of the label lines at 0.5 / 1 / 2 % background false-alarm rate for every map | 2 min |

## Region file

```json
{
 "name": "tihama_hays",
 "center_lonlat": [43.0984, 14.1077], "radius_m": 50000,        // or "bbox_lonlat": [w, s, e, n]
 "res_m": 10,
 "epochs": {"2021": ["2021-06-15", "2021-09-21"], "2022": [...], ..., "2026": ["2026-06-15", "2026-09-21"]},   // S2 composite windows, same season every year
 "before": "2021", "after": "2026",                                // the change pair; every epoch after "before" counts as "post"
 "s1": {"epochs": {"before": ["2021-01-01", "2022-01-15"], "after": ["2026-01-01", "2026-09-21"]}, "orbits": "auto", "pol": ["vv"], "max_dates_per_epoch": 20,
        "shift": {"o6_vv": [0, 2]}},                                // optional: force the S1->S2 registration roll (dy, dx) instead of estimating it
 "s2": {"bands": ["red"], "scenes_per_tile": 3},
 "detect": {"s1_change": {"L": 61, "widths": [1, 3, 5, 9]}, "fuse": ["s1_change", "s2_change", "s1_static", "s2_appear"]},   // optional overrides
 "wayback_before": "2021-12-31",                                   // optional: latest acceptable capture date for the Wayback "before" frame
 "dir": "/Volumes/T7/yemen-maps/trenchkit/work/tihama_hays"        // optional
}
```

## The signatures (what the detector looks for)

All maps are z-scores of an oriented bar (matched) filter bank: a centre bar of width w (1, 3, 5, 9 px = 10 to 90 m) minus two flank bars, over 18
orientations, length L = 61 px (610 m); the response is the smaller of the two flank contrasts so step edges do not fire, and each width is normalised
by the robust scale of its own background so the maps are comparable.

| map | input | earthwork behaviour it targets | Tihama result |
|---|---|---|---|
| `s1_change_o<orbit>_<pol>` | dB(after) - dB(before), detrended over 3 km | fresh spoil, berms and cut faces are rough: +1 to +4 dB bright line 40 to 90 m wide, any orientation | the workhorse: 29 % of label km at 0.5 % FA, 49 % at 2 % |
| `s1_static_o<orbit>_<pol>` | dB(after) detrended | the same line is bright now whether or not the "before" epoch is clean (pre-existing works, bad before epoch) | as good as change (29 / 48 %) and partly independent |
| `s2_change_red` | mean of the post epochs minus the before epoch, signed | persistent optical line of either sign: bright spoil / track, or dark trench and shadow | weak: 2 to 3 % at 0.5 % FA |
| `s2_appear_red` | mean over post epochs of the per-epoch signed line z, minus the before-epoch line z | a line that is there in every later epoch and was not there before, sign-agnostic | best optical map, 7 / 21 %; catches the Southern Trenches' bright track |
| `fused` | for each pixel, max over k of (sum of the k largest z) / sqrt(k) | keeps single-sensor lines, rewards agreement | a review/feature layer only: extracting components from it lost the weak lines, because every added map raises the fused background (p99.7 went from 7.4 to 10.2) |

Then `fuse` extracts line components from each map separately (so a road-heavy static map cannot raise the threshold of the change map) and merges them, and `rank` learns which components are trenches from their feature vectors (contrast per epoch, persistence, appearance
step, radar width, tortuosity, farmland density, ...). The learned ranking, not the raw maps, is what gets reviewed.

## Lessons from the Tihama labels (September 2026)

1. **The old pipeline saw a third of the belt.** Fused v3 covered 24 % of the 185 labelled km at 0.5 % false alarm (43 % at 2 %). Site A and B types were
   fine; the narrow fighting trenches of the Southern Trenches and the middle complex (3 to 5 m wide, little spoil) were mostly missed.
2. **Optical change alone is nearly useless at 10 m** for these features: the red-band line contrast flips sign between lines and between years
   (bright spoil/track vs dark cut/vegetation), so a single signed difference cancels. Persistence across epochs (`s2_appear`) is the only optical
   signal worth having, and it is still an order of magnitude behind radar.
3. **Radar is clutter-limited, not noise-limited.** Longer integration (121 and 181 px) lowered recall; the false alarms are real linear changes
   (tracks, field bunds, wadi banks, pipelines). Gains come from discriminating line types (temporal persistence, width, straightness, context),
   hence the learned ranker.
4. **Radar look direction is a modest effect, not a gate.** Lines running N-S (across the range direction) average +1.6 dB of change contrast,
   E-W lines +1.2 dB (correlation with N-S-ness 0.3, km-weighted); the E-W graded corridor at site B (+2.4 dB) outshines most N-S fighting trenches.
   Size, freshness and spoil matter more than orientation. A second orbit adds looks but not a new geometry: both S1 orbits look roughly east-west.
5. **Register S1 to S2 by line maps, not intensities.** Raw SAR and optical intensities do not correlate; the bar-filter line maps of both do. The
   sweep finds the 2 px (20 m) eastward offset of the RTC product automatically.
6. **Check the epoch you call "before".** The Southern Trenches appear on Sentinel-2 from 2022 and were absent in 2018 Wayback frames; a region whose
   works predate the before epoch needs the static maps (`s1_static`) or an earlier before epoch.
7. **Yearly composites are registered to < 0.3 px** (phase correlation check), so sign flips between years are radiometric, not misalignment.

## Results on the Tihama labels (2026-09-22, whole 100 km grid)

Per-pixel recall of the 185 label km at 0.5 / 1 / 2 % background false alarm (30 m tolerance):

| map | 0.5 % | 1 % | 2 % |
|---|---|---|---|
| `s1_change_o6_vv` (new, L = 61) | 0.34 | 0.44 | 0.53 |
| `s1_static_o6_vv` | 0.21 | 0.30 | 0.44 |
| `s2_appear_red` | 0.06 | 0.10 | 0.19 |
| `s2_change_red` | 0.01 | 0.02 | 0.03 |
| `fused` (4 maps) | 0.26 | 0.34 | 0.45 |
| v3 fused (21 Sep, for reference) | 0.24 | 0.33 | 0.43 |

Component level (what an analyst would actually review), union extraction from the radar change, radar static and optical appearance maps with
longest-path peeling of networked blobs, 847 candidates >= 900 m, hand score:

| reviewed top N | label km within 30 m of a candidate | candidates touching a label |
|---|---|---|
| 25 | 15 % | 28 % |
| 50 | 16 % | 16 % |
| 100 | 19 % | 12 % |
| 200 | 24 % | 9 % |
| 400 | 27 % | 6 % |

Every complex is represented near the top (site A lines rank 1 and 2, the middle complex chain ranks 2 to 20, Southern Trenches' bright line rank 7,
site B rank 11), but 73 % of the label kilometres are still not inside any candidate at 400: the narrow fighting trenches with +0.6 dB of radar
contrast never pass the p99.7 seed threshold. The learned ranker (24 positives) does not beat the hand score out of sample (16.4 % vs 15.2 % held-out
label km in the top 100), so `rank` falls back to the hand score and says so; its logistic weights nevertheless read as expected: radar static line
share (+1.7), radar change contrast (+1.4), radar static z (+1.1), optical persistence across post epochs (+0.9), and negative for lines that were
already there in the before epoch (-1.1), vegetation (-0.8) and radar brightness before (-0.7). It needs the next labelling rounds (more positives,
and explicit negatives: tracks, bunds, wadi banks) before it can be trusted.

## Evaluation and transfer

* With labels, `fuse` prints the label km covered by the top N components and the share of top-N components that touch a label; `evaluate` prints
  per-line recall at fixed false-alarm rates for every map (the numbers in the tables above).
* `rank` validates leave-one-group-out (each labelled complex held out in turn), which approximates transfer to a new area, and writes
  `candidates/fused_ranker_logreg.json`. In a new region without labels: `python -m trenchkit.rank new.json --apply work/tihama_hays/candidates/fused_ranker_logreg.json`.
* Verdicts entered in the review HTML export as JSON; a KMZ traced in Google Earth from the confirmed candidates is the next label set.

## Known limits and the next steps that would matter most

* The seed threshold (p99.7 of the map background) is what excludes the faint trenches; lowering it to p99 roughly doubles the candidate count.
  The right fix is a better ranker fed with more labels, then a lower threshold. `fuse(..., lo_pct=95, hi_pct=99)` is the knob.

* Sentinel-1 download speed from Planetary Computer (0.15 to 0.4 MB/s in September 2026) is the bottleneck: a 100 km region needs a day per orbit.
  Google Earth Engine (or a faster mirror) would make per-date stacks, both orbits and VH cheap.
* Only orbit 6 VV was used in Tihama; a second orbit and VH add independent looks and help lines that one geometry misses.
* Static maps flag every road; the ranker has to carry that load. A road/track mask from OSM or from the before-epoch static line map would help.
* 10 m data cannot see a 3 m trench without spoil. For those, a static line detector on Wayback tiles (0.6 m) over the ranked candidates' surroundings,
  or a coarser Wayback scan (z16, 2.4 m) of a whole front-line strip, is the realistic upgrade.
