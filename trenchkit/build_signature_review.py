"""Offline HTML: what the labelled trenches look like in Sentinel-1/2, how the old and new detectors score against them, and how the learned ranker
performs.  Reads the JSON/log products of earthwork_scan/kmz_eval and work/tihama_hays; embeds every figure as a data URI.
usage: /usr/bin/python3 build_signature_review.py -> /Volumes/T7/yemen-maps/trench_signature_review.html"""
import json, os, io, re, base64, html, numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
ES = "/Volumes/T7/yemen-maps/earthwork_scan"; WK = "/Volumes/T7/yemen-maps/trenchkit/work/tihama_hays"; OUT = "/Volumes/T7/yemen-maps/trench_signature_review.html"
def b64(path, maxw=1800, q=80):
    im = Image.open(path).convert("RGB")
    if im.width > maxw: im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, "JPEG", quality=q); return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
def table(rows, hdr, num_from=1):
    return "<table><tr>" + "".join(f"<th{' class=n' if i >= num_from else ''}>{html.escape(str(h))}</th>" for i, h in enumerate(hdr)) + "</tr>" + "".join("<tr>" + "".join(f"<td{' class=n' if i >= num_from else ''}>{html.escape(str(v))}</td>" for i, v in enumerate(r)) + "</tr>" for r in rows) + "</table>"
lines = json.load(open(f"{ES}/kmz_eval/lines.json")); prof = json.load(open(f"{ES}/kmz_eval/profiles.json")); groups = []
for l in lines:
    if l["group"] not in groups: groups.append(l["group"])
css = "body{margin:0;background:#fbfaf7;color:#1d1d1b;font:15px/1.5 Georgia,'Times New Roman',serif;padding:0 24px 80px;max-width:1500px}h1{font-size:28px;margin:26px 0 4px}h2{font-size:21px;margin:38px 0 8px;border-top:1px solid #c9c4b6;padding-top:14px}h3{font-size:17px;margin:22px 0 6px}.sub{color:#5a5a55;font-size:14px;max-width:1000px}table{border-collapse:collapse;font:13px/1.35 Helvetica,Arial,sans-serif;margin:8px 0 14px}td,th{padding:3px 9px 3px 0;border-bottom:1px solid #e0dccf;text-align:left;vertical-align:top}th{color:#5a5a55;font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}img{max-width:100%;display:block;margin:6px 0;border:1px solid #d8d4c8}.fig{margin:10px 0 18px}.cap{font-size:13px;color:#5a5a55;max-width:1000px}.call{background:#f1eee4;border-left:3px solid #9a7b2f;padding:8px 12px;margin:12px 0;max-width:1000px}code{font:13px Menlo,monospace;background:#f1eee4;padding:0 3px}"
o = [f"<!doctype html><html><head><meta charset='utf-8'><title>Trench signatures, Tihama 2026</title><style>{css}</style></head><body>",
     "<h1>What the hand-labelled trenches look like to Sentinel-1 and Sentinel-2, and what that changes in the detector</h1>",
     f"<div class='sub'>Labels: <code>Yemen identified trenches.kmz</code> (2026-09-22), {len(lines)} lines, {sum(l['len_km'] for l in lines):.0f} km in four complexes on the 10 m Tihama grid. Data: Sentinel-2 red-band Jun-Sep composites 2021-2026, Sentinel-1 RTC orbit 6 VV means for 2021 and 2026, Esri Wayback 0.3-0.6 m frames. Built {__import__('datetime').date.today().isoformat()} by <code>trenchkit/build_signature_review.py</code>.</div>"]
# 1. labels
o.append("<h2>1. The labels</h2>")
o.append(table([(l["name"], f"{l['len_km']:.1f}", f"{l['azimuth']:.0f}", f"{l['straightness']:.2f}", f"{prof[str(l['id'])]['prof']['S1_change_dB']['contrast']:+.2f}", f"{prof[str(l['id'])]['prof']['S1_after_dB']['contrast']:+.2f}", f"{prof[str(l['id'])]['prof']['S2_change']['contrast']*1e4:+.0f}", " ".join(f"{prof[str(l['id'])]['prof']['S2_'+e]['contrast']*1e4:+.0f}" for e in ('2021','2022','2023','2024','2025','2026'))) for l in lines],
               ["line", "km", "azimuth", "straightness", "S1 change dB", "S1 2026 static dB", "S2 red change DN", "S2 red line-minus-flank per epoch 2021..2026 (DN)"]))
o.append("<div class='cap'>Contrast = median cross-section value at the line minus the flanks 100-250 m either side. Radar change is positive (rougher/brighter) on 23 of 25 lines; optical contrast changes sign from line to line and from year to year.</div>")
for g in groups:
    fn = f"{ES}/kmz_eval/profiles_" + re.sub(r"\W+", "_", g).lower() + ".png"
    if os.path.exists(fn): o.append(f"<h3>{html.escape(g)}: cross-section profiles</h3><div class='fig'><img src='{b64(fn, 1500, 78)}'><div class='cap'>Columns: Sentinel-1 change (dB), Sentinel-1 2026 static (dB), Sentinel-2 red change 2021 to 2026 (DN), and the per-epoch optical line contrast. Shaded = interquartile range along the line; x axis = metres from the labelled centreline.</div></div>")
# wayback examples
ex = [("Southern Trenches, window 7 (13.960N 43.386E): a 3-5 m fighting trench with faint spoil in bare plain, 2018 vs 2025", f"{ES}/wayback/kmz/southern_trenches_pair_07.jpg"), ("Southern Trenches, window 3 (13.937N 43.311E): trench beside a track and a wadi in vegetated ground, 2018 vs 2022", f"{ES}/wayback/kmz/southern_trenches_pair_03.jpg"),
      ("Trench Complex, window 22 (14.079N 43.454E): trench with berm and patrol track through fields, 2021 vs 2025 (labelled line L7, radar change only +1.1 dB)", f"{ES}/wayback/kmz/trench_complex_pair_22.jpg"), ("Main Trench Complex, window 15 (14.151N 43.266E): the eastern end follows a wadi-bank track (L3), 2021 vs 2025", f"{ES}/wayback/kmz/main_trench_complex_pair_15.jpg")]
o.append("<h3>High-resolution examples</h3>")
for cap, fn in ex:
    if os.path.exists(fn): o.append(f"<div class='fig'><img src='{b64(fn, 1800, 80)}'><div class='cap'>{html.escape(cap)}. Yellow = the KMZ trace, drawn on the right-hand panel only.</div></div>")
# 2. old detector vs labels
o.append("<h2>2. How the September 21 detector (v3) scores against the labels</h2>")
o.append("<pre style='font:12px Menlo,monospace;background:#f1eee4;padding:10px;overflow-x:auto'>" + html.escape(open(f"{ES}/kmz_eval/eval_v3_report.txt").read()) + "</pre>")
o.append("<div class='call'>Recall is the share of labelled centreline pixels whose 30 m neighbourhood exceeds the threshold that lets through 0.5 / 1 / 2 % of the background. The fused v3 map reaches 24 % of the label kilometres at 0.5 % false alarm and 43 % at 2 %; the red-band change map is at 1-5 %. The right-hand column shows which labelled lines were inside a v3 line component and at what rank: the Trench Complex (site A) and Main Trench Complex (site B) were found, the Southern Trenches and most of the middle complex were not.</div>")
# 3. experiments
o.append("<h2>3. Signature experiments on the label window</h2>")
E = json.load(open(f"{ES}/kmz_eval/eval_exp.json"))["maps"]; gk = {}
for l in lines: gk.setdefault(l["group"], []).append(l)
rows = []
for name, r in E.items():
    row = [name]; tot = np.zeros(2); km = 0
    for g, ls in gk.items():
        a = np.zeros(2); k = 0
        for l in ls: v = r["lines"][str(l["id"])]; a += np.array([v["0.005"], v["0.02"]]) * l["len_km"]; k += l["len_km"]
        tot += a; km += k; row.append(f"{a[0]/k:.2f} / {a[1]/k:.2f}")
    row.append(f"{tot[0]/km:.2f} / {tot[1]/km:.2f}"); rows.append(row)
o.append(table(rows, ["map (window-local thresholds)"] + [g for g in gk] + ["all km"]) + "<div class='cap'>Recall at 0.5 % / 2 % false alarm, thresholds set inside the 28 x 43 km label window (harder than the whole-grid thresholds of section 2). L = bar length in 10 m pixels.</div>")
o.append("<div class='call'>Longer integration does not help (61 px is best at every group), all optical variants stay below 8 % at 0.5 % FA, and the radar static map is as informative as radar change. The false alarms are real linear changes, so the limit is clutter, not noise: discrimination has to happen at the component level.</div>")
# 4. full-grid run with trenchkit + ranker
o.append("<h2>4. The rebuilt pipeline on the full grid, and the learned ranker</h2>")
for fn, cap in ((f"{WK}/fuse.log", "Component extraction on the new fused map, with the label hit/miss summary"), (f"{WK}/rank.log", "Learned ranker: leave-one-complex-out coverage and the logistic weights"), (f"{WK}/eval.log", "Per-line recall of every new map (whole-grid thresholds)")):
    if os.path.exists(fn): o.append(f"<h3>{html.escape(cap)}</h3><pre style='font:12px Menlo,monospace;background:#f1eee4;padding:10px;overflow-x:auto'>" + html.escape(open(fn).read()[-12000:]) + "</pre>")
o.append("<div class='cap'>Products: <code>trenchkit/work/tihama_hays/candidates/fused.kml</code> (Google Earth), <code>trenchkit/work/tihama_hays/review/fused_review.html</code> (offline review with verdict boxes), <code>trenchkit/README.md</code> (the process).</div>")
o.append("</body></html>"); open(OUT, "w").write("".join(o)); print(OUT, os.path.getsize(OUT) // 1024, "KB")
