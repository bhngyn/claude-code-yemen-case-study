"""Earth Engine replacement for fetch_s1 + fetch_s2 (minutes instead of a day per orbit).  Writes the same files the other stages read:
  data/s1/o<orbit>_<pol>_<before|after>.npy   float16 dB, mean in linear power of every IW GRD scene of that orbit in the epoch (nan where < 3 looks)
  data/s2/<epoch>_EE.npz                      {med (red), med_green, med_blue, med_nir: int16 reflectance*1e4 (-32768 nodata), water, veg, row=0, col=0}
S1 is COPERNICUS/S1_GRD (ellipsoid-corrected sigma0, not terrain-flattened: fine for change and for detrended line maps, but hill slopes show in s1_static).
S2 is COPERNICUS/S2_HARMONIZED (L1C TOA, available from 2016 so early "before" epochs work), QA60 cloud mask + CLOUDY_PIXEL_PERCENTAGE < 20, median.
water = median NDWI > 0.1, veg = median NDVI > 0.35.  Tiles are pulled on the exact region grid (crs_transform) and cached in data/ee_tiles/.
usage: python -m trenchkit.fetch_ee region.json [s1|s2 ...]"""
import sys, os, io, json, time, zipfile, urllib.request, numpy as np, rasterio, ee
from concurrent.futures import ThreadPoolExecutor
from .grid import load_region, load_grid, bbox_lonlat
T = 1000
def pull(img, G, tdir, nb, scale=1.0, nodata=-32768):
    """download img (int16) on the grid in T x T tiles -> float32 (nb, H, W) with nan for nodata, divided by scale"""
    os.makedirs(tdir, exist_ok=True); H, W = G["height"], G["width"]; jobs = [(r, c) for r in range(0, H, T) for c in range(0, W, T)]
    def one(rc):
        r, c = rc; p = os.path.join(tdir, f"t_{r}_{c}.tif")
        if os.path.exists(p): return p
        h, w = min(T, H - r), min(T, W - c); tr = [G["res"], 0, G["x0"] + c * G["res"], 0, -G["res"], G["y0"] - r * G["res"]]
        for a in range(5):
            try:
                url = img.getDownloadURL({"crs": f"EPSG:{G['epsg']}", "crs_transform": tr, "dimensions": f"{w}x{h}", "format": "GEO_TIFF"})
                data = urllib.request.urlopen(url, timeout=900).read(); break
            except Exception as e: print("retry", r, c, str(e)[:150], flush=True); time.sleep(10 * (a + 1))
        else: raise RuntimeError(f"tile {r},{c} failed")
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z: data = z.read([x for x in z.namelist() if x.endswith(".tif")][0])
        open(p + ".part", "wb").write(data); os.rename(p + ".part", p); return p
    with ThreadPoolExecutor(10) as ex: paths = list(ex.map(one, jobs))
    out = np.full((nb, H, W), np.nan, "float32")
    for (r, c), p in zip(jobs, paths):
        with rasterio.open(p) as s: a = s.read().astype("float32")
        a[a == nodata] = np.nan; out[:, r:r + a.shape[1], c:c + a.shape[2]] = a / scale
    return out
def s1(R, G):
    d = os.path.join(R["dir"], "data", "s1"); os.makedirs(d, exist_ok=True); g = ee.Geometry.Rectangle(bbox_lonlat(G)); pols = [p.upper() for p in R["s1"].get("pol", ["vv"])]
    col = ee.ImageCollection("COPERNICUS/S1_GRD").filterBounds(g).filter(ee.Filter.eq("instrumentMode", "IW"))
    for p in pols: col = col.filter(ee.Filter.listContains("transmitterReceiverPolarisation", p))
    info = {}
    for ep, (d0, d1) in R["s1"]["epochs"].items():
        ce = col.filterDate(d0, ee.Date(d1).advance(1, "day")); hist = ce.aggregate_histogram("relativeOrbitNumber_start").getInfo()
        orbits = sorted(int(float(o)) for o, n in hist.items() if n >= 8) if R["s1"].get("orbits", "auto") == "auto" else [int(o) for o in R["s1"]["orbits"]]
        for o in orbits:
            if all(os.path.exists(os.path.join(d, f"o{o}_{p.lower()}_{ep}.npy")) for p in pols): continue
            co = ce.filter(ee.Filter.eq("relativeOrbitNumber_start", o)); n = co.size().getInfo()
            lin = co.map(lambda im: ee.Image(10).pow(im.select(pols).divide(10)).updateMask(im.select(pols[0]).gt(-30)))
            cnt = lin.select(pols[0]).count(); m = lin.mean().log10().multiply(10).updateMask(cnt.gte(3))
            img = ee.Image.cat(m.multiply(100), cnt).toInt16().unmask(-32768)
            t0 = time.time(); a = pull(img, G, os.path.join(R["dir"], "data", "ee_tiles", f"s1_o{o}_{ep}"), len(pols) + 1)
            for k, p in enumerate(pols): np.save(os.path.join(d, f"o{o}_{p.lower()}_{ep}.npy"), (a[k] / 100).astype("float16"))
            info[f"{ep}|{o}"] = {"scenes": n, "median_looks": float(np.nanmedian(a[-1][::17, ::17]))}; print(f"S1 {ep} orbit {o}: {n} scenes, {time.time() - t0:.0f}s", flush=True)
    # keep only orbits present in both epochs
    have = lambda ep: {f.split("_")[0] for f in os.listdir(d) if f.endswith(f"_{ep}.npy")}
    for f in os.listdir(d):
        if f.endswith("_after.npy") and f.split("_")[0] not in have("before"): os.rename(os.path.join(d, f), os.path.join(d, f + ".unpaired"))
    json.dump(info, open(os.path.join(d, "ee_info.json"), "w"), indent=1)
def s2(R, G):
    d = os.path.join(R["dir"], "data", "s2"); os.makedirs(d, exist_ok=True); g = ee.Geometry.Rectangle(bbox_lonlat(G))
    def mask(im):
        qa = im.select("QA60"); return im.updateMask(qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0)))
    for ep, (d0, d1) in R["epochs"].items():
        out = os.path.join(d, f"{ep}_EE.npz")
        if os.path.exists(out): continue
        c = ee.ImageCollection("COPERNICUS/S2_HARMONIZED").filterBounds(g).filterDate(d0, ee.Date(d1).advance(1, "day")).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20)).map(mask)
        n = c.size().getInfo(); m = c.select(["B4", "B3", "B2", "B8"]).median()
        ndwi = m.normalizedDifference(["B3", "B8"]); ndvi = m.normalizedDifference(["B8", "B4"])
        img = ee.Image.cat(m, ndwi.gt(0.1), ndvi.gt(0.35)).toInt16().unmask(-32768)
        t0 = time.time(); a = pull(img, G, os.path.join(R["dir"], "data", "ee_tiles", f"s2_{ep}"), 6, scale=1.0)
        q = lambda x: np.nan_to_num(x, nan=-32768).astype("int16")
        np.savez_compressed(out, med=q(a[0]), med_green=q(a[1]), med_blue=q(a[2]), med_nir=q(a[3]), water=np.nan_to_num(a[4]) > 0, veg=np.nan_to_num(a[5]) > 0, row=0, col=0, bands=np.array(["red", "green", "blue", "nir"]))
        print(f"S2 {ep}: {n} scenes, {time.time() - t0:.0f}s", flush=True); del a
if __name__ == "__main__":
    ee.Initialize(); R = load_region(sys.argv[1]); G = load_grid(R); which = sys.argv[2:] or ["s2", "s1"]
    if "s2" in which: s2(R, G)
    if "s1" in which: s1(R, G)
    print("fetch_ee done", flush=True)
