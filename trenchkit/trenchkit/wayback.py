"""Esri World Imagery Wayback before/after frames (~0.6 m/px at z18) for the top-N ranked candidates, for the review page and for hand labelling.
after  = newest Wayback release.   before = newest release whose capture date at the candidate centre is on/before region["wayback_before"] (default: end of the S2 before epoch).
Writes review/wayback/r<rank>_{before,after}.jpg (+ _trace.jpg with the detected line) and r<rank>.json.  Resumable.
usage: python -m trenchkit.wayback region.json [tag=fused] [top=40] [--hand]   (--hand ranks by the hand score instead of the learned one; --refresh reloads the release list)"""
import sys, os, io, re, json, math, datetime, urllib.request, urllib.parse, concurrent.futures as cf, numpy as np
from PIL import Image, ImageDraw, ImageFont
from .grid import load_region, load_grid, to_lonlat
CFG = os.path.join(os.path.dirname(__file__), "data", "waybackconfig.json"); CFG_URL = "https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json"
def get(u):
    for _ in range(4):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        except Exception as e: err = e
    raise err
def releases(refresh=False):
    if refresh or not os.path.exists(CFG): open(CFG, "wb").write(get(CFG_URL))
    cfg = json.load(open(CFG)); rd = lambda v: re.search(r"(\d{4}-\d{2}-\d{2})", v["itemTitle"]).group(1)
    return sorted(((rd(v), k, v) for k, v in cfg.items() if "metadataLayerUrl" in v), key=lambda t: t[0])
def meta(rel, lon, lat):
    q = urllib.parse.urlencode({"f": "json", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "outFields": "SRC_DATE2,SRC_DATE,SRC_DESC,SRC_RES", "returnGeometry": "false"})
    for lid in (4, 5, 6, 7, 8):
        try: j = json.loads(get(f"{rel['metadataLayerUrl']}/{lid}/query?{q}"))
        except Exception: continue
        if j.get("features"):
            a = j["features"][0]["attributes"]; dd = a.get("SRC_DATE2") or a.get("SRC_DATE")
            return {"captured": datetime.datetime.fromtimestamp(dd / 1000, datetime.timezone.utc).date().isoformat() if isinstance(dd, (int, float)) else None, "sensor": a.get("SRC_DESC"), "res_m": a.get("SRC_RES")}
    return {}
def ll2tile(lon, lat, z): n = 2 ** z; return (lon + 180) / 360 * n, (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
def tile2merc(x, y, z): n = 2 ** z; R = 6378137 * math.pi; return -R + 2 * R * x / n, R - 2 * R * y / n
def ll2merc(lon, lat): R = 6378137; return R * np.radians(lon), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
def fetch_box(rel, lon0, lat0, lon1, lat1, Z):
    x0, y1 = ll2tile(lon0, lat0, Z); x1, y0 = ll2tile(lon1, lat1, Z); tx0, tx1, ty0, ty1 = int(x0), int(math.ceil(x1)), int(y0), int(math.ceil(y1))
    W, H = (tx1 - tx0) * 256, (ty1 - ty0) * 256; M = np.zeros((H, W, 3), "uint8"); tiles = [(tx, ty) for tx in range(tx0, tx1) for ty in range(ty0, ty1)]
    def one(t):
        try: return t, np.asarray(Image.open(io.BytesIO(get(rel["itemURL"].format(level=Z, row=t[1], col=t[0])))).convert("RGB"))
        except Exception: return t, None
    miss = 0
    with cf.ThreadPoolExecutor(12) as ex:
        for (tx, ty), a in ex.map(one, tiles):
            if a is None: miss += 1; continue
            M[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = a
    mx0, my1 = tile2merc(tx0, ty0, Z); mx1, my0 = tile2merc(tx1, ty1, Z); return M, (mx0, my0, mx1, my1), miss, len(tiles)
def run(R, G, tag="fused", top=40, hand=False, refresh=False):
    cd = os.path.join(R["dir"], "candidates"); rf = os.path.join(cd, f"{tag}_components_ranked.json"); comps = json.load(open(rf if os.path.exists(rf) and not hand else os.path.join(cd, f"{tag}_components.json")))
    key = "rank_learned" if os.path.exists(rf) and not hand else "rank"; comps = sorted(comps, key=lambda c: c[key])[:top]; od = os.path.join(R["dir"], "review", "wayback"); os.makedirs(od, exist_ok=True)
    rels = releases(refresh); latest = rels[-1]; cutoff = R.get("wayback_before") or R["epochs"][R["before"]][1]
    probe_dates = sorted({d for d in [cutoff] + [f"{y}-{m:02d}-15" for y in range(int(cutoff[:4]), int(cutoff[:4]) - 4, -1) for m in (12, 9, 6, 3)] if d <= cutoff}, reverse=True)
    probes = []
    for d in probe_dates:
        r = next((t for t in rels if t[0] >= d), None)
        if r and r not in probes: probes.append(r)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 26)
    for c in comps:
        rk = c[key]; jp = os.path.join(od, f"r{rk}.json")
        if os.path.exists(jp): continue
        rc = np.array(c["path_rc"]); lon, lat = to_lonlat(G, rc[:, 0], rc[:, 1]); pad = max(300, 0.15 * c["path_m"]) / 111320
        lon0, lon1 = lon.min() - pad / math.cos(math.radians(lat.mean())), lon.max() + pad / math.cos(math.radians(lat.mean())); lat0, lat1 = lat.min() - pad, lat.max() + pad
        span_m = max((lon1 - lon0) * 111320 * math.cos(math.radians(lat.mean())), (lat1 - lat0) * 111320); Z = 18 if span_m <= 2500 else (17 if span_m <= 5000 else 16); clon, clat = float(lon.mean()), float(lat.mean())
        picks = [("after", latest)]
        for p in probes:
            m = meta(p[2], clon, clat)
            if m.get("captured") and m["captured"] <= cutoff: picks.append(("before", p)); break
        info = {"rank": rk, "label": c["label"], "lat": clat, "lon": clon, "zoom": Z, "frames": {}}
        for role, (rdate, rk_, rel) in picks:
            M, (mx0, my0, mx1, my1), miss, n = fetch_box(rel, lon0, lat0, lon1, lat1, Z); H, W = M.shape[:2]; m = meta(rel, clon, clat)
            im = Image.fromarray(M); im.save(os.path.join(od, f"r{rk}_{role}.jpg"), quality=88)
            X, Y = ll2merc(lon, lat); px = (X - mx0) / (mx1 - mx0) * W; py = (my1 - Y) / (my1 - my0) * H
            ov = Image.new("RGBA", im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov); d.line(list(zip(px, py)), fill=(255, 60, 60, 150), width=max(2, int(4 * 2 ** (Z - 18))), joint="curve")
            tr = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB"); d = ImageDraw.Draw(tr); mpp = (mx1 - mx0) / W * math.cos(math.radians(clat)); bar = 250 / mpp
            d.rectangle([W - 30 - bar, H - 34, W - 30, H - 26], fill="white", outline="black"); d.text((W - 30 - bar, H - 66), "250 m", fill="white", font=font, stroke_width=2, stroke_fill="black")
            d.rectangle([0, 0, W, 40], fill=(0, 0, 0)); d.text((10, 6), f"{role}: captured {m.get('captured')} {m.get('sensor') or ''} {m.get('res_m') or ''} m (release {rdate}, z{Z})", fill="white", font=font)
            tr.save(os.path.join(od, f"r{rk}_{role}_trace.jpg"), quality=86)
            info["frames"][role] = {"release": rdate, "captured": m.get("captured"), "sensor": m.get("sensor"), "res_m": m.get("res_m"), "bounds_merc": [mx0, my0, mx1, my1], "size": [W, H], "missing_tiles": miss, "tiles": n}
        json.dump(info, open(jp, "w"), indent=1); print(f"r{rk} {clat:.4f}N {clon:.4f}E z{Z}: " + ", ".join(f"{k} {v['captured']}" for k, v in info["frames"].items()), flush=True)
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); a = [x for x in sys.argv[2:] if not x.startswith("--")]
    run(R, G, a[0] if a else "fused", int(a[1]) if len(a) > 1 else 40, hand="--hand" in sys.argv, refresh="--refresh" in sys.argv)
