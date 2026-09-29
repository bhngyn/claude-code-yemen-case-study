"""Sentinel-1 RTC (Planetary Computer, gamma0 linear power) multi-date mean stacks per epoch, relative orbit and polarisation.
Output data/s1/o<orbit>_<pol>_<epoch>.npy = float16 dB mean over up to max_dates_per_epoch evenly spaced dates (nan where < 3 looks), plus _cnt.npy.
Resumable: a .partial.npz accumulator is written after every date, so a killed job continues where it stopped.
usage: python -m trenchkit.fetch_s1 region.json [epoch ...]      (orbits: region["s1"]["orbits"] = "auto" -> every relative orbit with >= 8 dates in the epoch, or a list)"""
import sys, os, json, time, collections, urllib.request, threading, numpy as np, rasterio, warnings
from rasterio.windows import from_bounds
from concurrent.futures import ThreadPoolExecutor
from .grid import load_region, load_grid, bounds, bbox_lonlat
warnings.filterwarnings("ignore")
os.environ.update(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="5", GDAL_HTTP_RETRY_DELAY="2", GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES", GDAL_HTTP_TIMEOUT="120")
UA = {"Content-Type": "application/json", "User-Agent": "trenchkit/1.0"}; PC = "https://planetarycomputer.microsoft.com/api"
def token(): return json.load(urllib.request.urlopen(urllib.request.Request(f"{PC}/sas/v1/token/sentinel-1-rtc", headers=UA), timeout=60))["token"]
def search(bbox, dt):
    body = {"collections": ["sentinel-1-rtc"], "bbox": bbox, "datetime": dt, "limit": 100}; out = []
    while True:
        d = json.load(urllib.request.urlopen(urllib.request.Request(f"{PC}/stac/v1/search", json.dumps(body).encode(), UA), timeout=90))
        for f in d["features"]:
            p = f["properties"]; out.append({"id": f["id"], "date": p["datetime"][:10], "orbit": p["sat:relative_orbit"], "dir": p["sat:orbit_state"], "platform": p.get("platform"), "bbox": f["bbox"], **{k: f["assets"][k]["href"] for k in ("vv", "vh") if k in f["assets"]}})
        nxt = [l for l in d.get("links", []) if l["rel"] == "next"]
        if not nxt: break
        body = nxt[0]["body"]
    return out
def coverage(item, bbox):
    """fraction of the region bbox covered by the scene footprint bbox"""
    w, s, e, n = bbox; x0, y0, x1, y1 = item["bbox"]; return max(0, min(e, x1) - max(w, x0)) * max(0, min(n, y1) - max(s, y0)) / ((e - w) * (n - s))
def plan(R, G):
    """which dates per (epoch, orbit): cached in data/s1/plan.json"""
    d = os.path.join(R["dir"], "data", "s1"); os.makedirs(d, exist_ok=True); pp = os.path.join(d, "plan.json")
    if os.path.exists(pp): return json.load(open(pp))
    S = R["s1"]; bbox = bbox_lonlat(G); P = {}
    for ep, (d0, d1) in S["epochs"].items():
        items = search(bbox, f"{d0}T00:00:00Z/{d1}T23:59:59Z"); by = collections.defaultdict(lambda: collections.defaultdict(list))
        for it in items: by[it["orbit"]][it["date"]].append(it)
        orbits = [o for o in by if len(by[o]) >= S.get("min_dates", 8)] if S.get("orbits", "auto") == "auto" else [int(o) for o in S["orbits"]]
        for o in orbits:
            dates = sorted(by[o]); full = [dd for dd in dates if sum(coverage(i, bbox) for i in by[o][dd]) >= 0.98]     # dates whose scenes cover the whole region
            pick = [full[int(round(k))] for k in np.linspace(0, len(full) - 1, min(S.get("max_dates_per_epoch", 20), len(full)))] if full else []
            P[f"{ep}|{o}"] = {"epoch": ep, "orbit": o, "dir": by[o][dates[0]][0]["dir"], "n_available": len(dates), "n_full": len(full), "dates": sorted(set(pick)), "scenes": {dd: by[o][dd] for dd in sorted(set(pick))}}
            print(f"{ep} orbit {o} ({P[f'{ep}|{o}']['dir']}): {len(dates)} dates, {len(full)} full-coverage, stacking {len(set(pick))}", flush=True)
    json.dump(P, open(pp, "w"), indent=1); return P
def stack(R, G, key, P, pol):
    d = os.path.join(R["dir"], "data", "s1"); ep, o = P[key]["epoch"], P[key]["orbit"]; out = os.path.join(d, f"o{o}_{pol}_{ep}.npy")
    if os.path.exists(out): return out, "cached"
    H, W = G["height"], G["width"]; B = bounds(G); part = out[:-4] + ".partial.npz"
    if os.path.exists(part): z = np.load(part); acc, cnt, done = z["acc"], z["cnt"], set(z["done"].tolist())
    else: acc, cnt, done = np.zeros((H, W), "float32"), np.zeros((H, W), "uint8"), set()
    tok = token(); lock = threading.Lock(); todo = [dd for dd in P[key]["dates"] if dd not in done]
    def one(dd):
        t0 = time.time(); a_all = np.zeros((H, W), "float32"); c_all = np.zeros((H, W), "uint8")
        for it in P[key]["scenes"][dd]:
            if pol not in it: continue
            try:
                with rasterio.open(it[pol] + "?" + tok) as s: a = s.read(1, window=from_bounds(*B, s.transform), boundless=True, fill_value=0, out_shape=(H, W)).astype("float32")
            except Exception as e: print("ERR", dd, str(e)[:100], flush=True); return dd, False
            ok = np.isfinite(a) & (a > 0); a_all[ok] += np.clip(a[ok], 0, 2.0); c_all[ok] += 1                # clip corner-reflector spikes
        with lock:
            m = c_all > 0; acc[m] += a_all[m] / c_all[m]; cnt[m] += 1; done.add(dd); np.savez(part, acc=acc, cnt=cnt, done=np.array(sorted(done)))
        print(f"{key} {pol} {dd} {time.time() - t0:.0f}s ({len(done)}/{len(P[key]['dates'])})", flush=True); return dd, True
    with ThreadPoolExecutor(2) as ex: list(ex.map(one, todo))
    n = len(P[key]["dates"]); m = acc / np.maximum(cnt, 1); m[cnt < max(min(3, n), n // 3)] = np.nan          # need 3 looks (or all of them when fewer were stacked)
    np.save(out, (10 * np.log10(np.maximum(m, 1e-5))).astype("float16")); np.save(out[:-4] + "_cnt.npy", cnt); os.remove(part); return out, int(np.median(cnt))
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); P = plan(R, G); eps = sys.argv[2:] or list(R["s1"]["epochs"])
    for key in P:
        if P[key]["epoch"] not in eps: continue
        for pol in R["s1"].get("pol", ["vv"]): print(stack(R, G, key, P, pol), flush=True)
    print("S1 done")
