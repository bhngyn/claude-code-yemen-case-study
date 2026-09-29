"""Recall of labelled lines at fixed background false-alarm rates, for any set of line-response maps on the region grid.
Recall = share of label pixels whose (2*tol+1)^2 neighbourhood max exceeds the threshold; background = valid pixels > 300 m from any label.
usage: python -m trenchkit.evaluate region.json [tag] [map_name ...]     (default: every map in <region>/maps/*.npy)"""
import sys, os, glob, json, numpy as np, cv2
from scipy.ndimage import maximum_filter
from .grid import load_region, load_grid
FA = (0.005, 0.01, 0.02)
def evaluate(R, maps, tag="labels", tol=3, valid=None, stride=7, out=None):
    """maps: {name: array or path}; arrays may be float16 memmaps.  Returns the result dict and prints the table."""
    d = os.path.join(R["dir"], "labels"); ids = np.load(os.path.join(d, f"{tag}_ids.npy"), mmap_mode="r"); lines = json.load(open(os.path.join(d, f"{tag}_lines.json")))
    far = ~cv2.dilate((np.asarray(ids) > 0).astype("uint8"), np.ones((61, 61), "uint8")).astype(bool)
    res = {}
    for name, m in maps.items():
        m = np.load(m, mmap_mode="r") if isinstance(m, str) else m
        bg = np.asarray(m[::stride, ::stride]).astype("float32"); ok = far[::stride, ::stride] & np.isfinite(bg) & (bg != 0)
        if valid is not None: ok &= np.asarray(valid[::stride, ::stride])
        bg = bg[ok]; thr = {fa: float(np.percentile(bg, 100 * (1 - fa))) for fa in FA}; res[name] = {"thr": thr, "lines": {}}
        for l in lines:
            r0, r1, c0, c1 = l["bbox_rc"]; r0, c0 = max(r0 - 6, 0), max(c0 - 6, 0); r1, c1 = r1 + 7, c1 + 7
            sub = np.nan_to_num(np.asarray(m[r0:r1, c0:c1]).astype("float32")); mx = maximum_filter(sub, 2 * tol + 1); lm = np.asarray(ids[r0:r1, c0:c1]) == l["id"]
            res[name]["lines"][str(l["id"])] = {fa: float((mx[lm] > thr[fa]).mean()) if lm.any() else 0.0 for fa in FA}
    if out: json.dump(res, open(out, "w"), indent=1)
    report(res, lines); return res
def report(res, lines):
    maps = list(res); print(f"Recall of label centreline at FA {' / '.join(f'{f*100:.1f}%' for f in FA)} (30 m tolerance)")
    hdr = f'{"line":30s} {"km":>6s} {"az":>4s} | ' + " | ".join(f"{n[:17]:>17s}" for n in maps); print(hdr)
    tot = {n: np.zeros(len(FA)) for n in maps}; gt = {}; km = 0
    for l in lines:
        row = f'{l["name"]:30s} {l["len_km"]:6.2f} {l["azimuth"]:4.0f} | '
        for n in maps:
            a = np.array([res[n]["lines"][str(l["id"])][fa] for fa in FA]); row += " ".join(f"{x:5.2f}" for x in a) + " | "; tot[n] += a * l["len_km"]
            gt.setdefault(l["group"], {"km": 0}).setdefault(n, np.zeros(len(FA))); gt[l["group"]][n] += a * l["len_km"]
        gt[l["group"]]["km"] += l["len_km"]; km += l["len_km"]; print(row)
    print("-" * len(hdr))
    for g, d in gt.items(): print(f'{g:30s} {d["km"]:6.2f}      | ' + " | ".join(" ".join(f"{x:5.2f}" for x in d[n] / d["km"]) for n in maps))
    print(f'{"ALL (km-weighted)":30s} {km:6.2f}      | ' + " | ".join(" ".join(f"{x:5.2f}" for x in tot[n] / km) for n in maps))
if __name__ == "__main__":
    R = load_region(sys.argv[1]); tag = sys.argv[2] if len(sys.argv) > 2 else "labels"; names = sys.argv[3:]
    md = os.path.join(R["dir"], "maps"); files = [os.path.join(md, n if n.endswith(".npy") else n + ".npy") for n in names] if names else [f for f in sorted(glob.glob(os.path.join(md, "*.npy"))) if not f.endswith(("_w.npy", "_sign.npy", "valid.npy", "veg.npy", "busy.npy"))]
    evaluate(R, {os.path.basename(f)[:-4]: f for f in files}, tag, out=os.path.join(R["dir"], f"eval_{tag}.json"))
