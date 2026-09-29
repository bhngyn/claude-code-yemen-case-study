"""Sentinel-2 L2A per-epoch median composites (AWS earth-search COGs, no account needed).
For each epoch in region["epochs"] and each MGRS tile touching the grid: the N lowest-cloud scenes (nodata < 5 %) are read for each band,
SCL-masked (cloud, shadow, snow, nodata), median-combined and stored as data/s2/<epoch>_<tile>.npz {med (int16, -32768 nodata), water, veg, row, col}.
Resumable (existing files are skipped).   usage: python -m trenchkit.fetch_s2 region.json [epoch ...]"""
import sys, os, json, time, collections, urllib.request, numpy as np, rasterio, warnings
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from concurrent.futures import ThreadPoolExecutor
from .grid import load_region, load_grid, bounds, bbox_lonlat
warnings.filterwarnings("ignore")
os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2",
                  CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", GDAL_CACHEMAX="512")
STAC = "https://earth-search.aws.element84.com/v1/search"; BAND_RES = {"red": 10, "green": 10, "blue": 10, "nir": 10, "swir16": 20, "swir22": 20, "rededge1": 20}
def search(bbox, dt):
    body = {"collections": ["sentinel-2-l2a"], "bbox": bbox, "datetime": dt, "limit": 100}; out = []
    while True:
        r = urllib.request.Request(STAC, json.dumps(body).encode(), {"Content-Type": "application/json", "User-Agent": "trenchkit/1.0"}); d = json.load(urllib.request.urlopen(r, timeout=90))
        for f in d["features"]:
            p = f["properties"]; out.append({"id": f["id"], "date": p["datetime"][:10], "tile": p["grid:code"][-5:], "cc": p.get("eo:cloud_cover", 100), "nodata": p.get("s2:nodata_pixel_percentage", 0),
                                             "baseline": p.get("s2:processing_baseline"), "offset_applied": p.get("earthsearch:boa_offset_applied"), "assets": {k: v["href"] for k, v in f["assets"].items() if k in BAND_RES or k == "scl"}})
        nxt = [l for l in d.get("links", []) if l["rel"] == "next"]
        if not nxt: break
        body = nxt[0]["body"]
    return out
def read_scene(it, band, B):
    with rasterio.open(it["assets"][band]) as s:
        b = s.bounds; ib = (max(B[0], b.left), max(B[1], b.bottom), min(B[2], b.right), min(B[3], b.top))
        if ib[2] <= ib[0] or ib[3] <= ib[1]: return None
        w = from_bounds(*ib, s.transform).round_offsets().round_lengths(); a = s.read(1, window=w).astype("float32")
        if BAND_RES[band] == 20: a = np.repeat(np.repeat(a, 2, 0), 2, 1)                     # 20 m bands to the 10 m grid (nearest)
    with rasterio.open(it["assets"]["scl"]) as s:
        scl = s.read(1, window=from_bounds(*ib, s.transform).round_offsets().round_lengths(), out_shape=a.shape, resampling=Resampling.nearest)
    nod = a == 0
    if float(it["baseline"] or 0) >= 4.0 and not it["offset_applied"]: a -= 1000                 # harmonise the PB04 BOA offset
    a[nod | np.isin(scl, (0, 1, 3, 8, 9, 10))] = np.nan; return a, scl, ib
def select(R, G, epochs):
    """per epoch/tile: the scenes_per_tile lowest-cloud scenes with < 5 % nodata; cached in data/s2/selection.json"""
    d = os.path.join(R["dir"], "data", "s2"); os.makedirs(d, exist_ok=True); sp = os.path.join(d, "selection.json"); sel = json.load(open(sp)) if os.path.exists(sp) else {}
    n = R.get("s2", {}).get("scenes_per_tile", 3)
    for ep in epochs:
        if ep in sel: continue
        d0, d1 = R["epochs"][ep]; items = search(bbox_lonlat(G), f"{d0}T00:00:00Z/{d1}T23:59:59Z"); by = collections.defaultdict(dict)
        for i in sorted(items, key=lambda i: i["id"]): by[i["tile"]][i["date"]] = i
        sel[ep] = {t: sorted((i for i in dd.values() if i["nodata"] < 5), key=lambda i: i["cc"])[:n] for t, dd in by.items()}
        print(ep, {t: [(g["date"], round(g["cc"], 1)) for g in v] for t, v in sel[ep].items()}, flush=True)
    json.dump(sel, open(sp, "w"), indent=1); return sel
def composite(R, G, sel, ep, tile, bands):
    out = os.path.join(R["dir"], "data", "s2", f"{ep}_{tile}.npz")
    if os.path.exists(out): return out, "cached"
    B = bounds(G); t0 = time.time(); arrs = {}; scls = None; ib = None
    for band in bands:
        res = [r for r in (read_scene(it, band, B) for it in sel[ep][tile]) if r is not None]
        if not res: return out, "no overlap"
        arrs[band] = np.nan_to_num(np.nanmedian(np.stack([r[0] for r in res]), 0), nan=-32768).astype("int16"); scls = [r[1] for r in res]; ib = res[0][2]
    water = np.mean([s == 6 for s in scls], 0) >= 0.5; veg = np.mean([s == 4 for s in scls], 0) >= 0.5
    col = int(round((ib[0] - B[0]) / G["res"])); row = int(round((B[3] - ib[3]) / G["res"]))
    np.savez_compressed(out, med=arrs[bands[0]], **{f"med_{b}": arrs[b] for b in bands[1:]}, water=water, veg=veg, row=row, col=col, bands=np.array(bands))
    return out, arrs[bands[0]].shape, f"{time.time() - t0:.0f}s"
def mosaic(R, G, ep, band="red", tiles=None, window=None):
    """assemble one epoch/band onto the grid as float32 reflectance (nan = nodata).  window = (r0, r1, c0, c1) to crop."""
    d = os.path.join(R["dir"], "data", "s2"); H, W = G["height"], G["width"]; r0, r1, c0, c1 = window or (0, H, 0, W); out = np.full((r1 - r0, c1 - c0), np.nan, "float32")
    key = "med" if band == "red" else f"med_{band}"
    for f in sorted(os.listdir(d)):
        if not (f.startswith(ep + "_") and f.endswith(".npz")): continue
        z = np.load(os.path.join(d, f)); r, c = int(z["row"]), int(z["col"]); med = z[key]; h, w = med.shape
        rr0, rr1, cc0, cc1 = max(r, r0), min(r + h, r1), max(c, c0), min(c + w, c1)
        if rr1 <= rr0 or cc1 <= cc0: continue
        sub = med[rr0 - r:rr1 - r, cc0 - c:cc1 - c].astype("float32"); sub[sub == -32768] = np.nan; dst = out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0]; ok = np.isfinite(sub); dst[ok] = sub[ok]
    return out / 1e4
def mosaic_cached(R, G, ep, band="red"):
    """full-grid epoch/band mosaic as a float16 memmap, built once into data/s2/mosaic_<epoch>_<band>.npy"""
    p = os.path.join(R["dir"], "data", "s2", f"mosaic_{ep}_{band}.npy")
    if not os.path.exists(p): np.save(p, mosaic(R, G, ep, band).astype("float16"))
    return np.load(p, mmap_mode="r")
def masks(R, G, eps):
    """union over epochs/tiles of the water and vegetation masks, plus tile seams (6 px) -> (water, veg, seam) bool grids"""
    d = os.path.join(R["dir"], "data", "s2"); H, W = G["height"], G["width"]; water = np.zeros((H, W), bool); veg = np.zeros((H, W), bool); seam = np.zeros((H, W), bool)
    for f in sorted(os.listdir(d)):
        if not any(f.startswith(ep + "_") for ep in eps) or not f.endswith(".npz"): continue
        z = np.load(os.path.join(d, f)); r, c = int(z["row"]), int(z["col"]); h, w = z["water"].shape; sl = (slice(r, min(r + h, H)), slice(c, min(c + w, W))); hh, ww = sl[0].stop - r, sl[1].stop - c
        water[sl] |= z["water"][:hh, :ww]; veg[sl] |= z["veg"][:hh, :ww]; e = np.zeros((hh, ww), bool); e[:6] = e[-6:] = True; e[:, :6] = e[:, -6:] = True; seam[sl] |= e
    return water, veg, seam
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); epochs = sys.argv[2:] or list(R["epochs"]); bands = R.get("s2", {}).get("bands", ["red"])
    sel = select(R, G, epochs); jobs = [(ep, t) for ep in epochs for t in sel[ep]]
    with ThreadPoolExecutor(2) as ex:
        for r in ex.map(lambda j: composite(R, G, sel, j[0], j[1], bands), jobs): print(r, flush=True)
    print("S2 done")
