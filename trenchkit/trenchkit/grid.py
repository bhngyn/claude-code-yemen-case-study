"""Region grid: a north-up UTM raster at res_m (default 10 m) covering the region bbox or centre+radius.
grid.json = {"epsg", "x0", "y0", "res", "width", "height"} with (x0, y0) the top-left corner; row 0 = north, col 0 = west.
Also the lon/lat <-> row/col helpers every other stage uses."""
import json, os, sys, math, numpy as np
from rasterio.warp import transform
def load_region(path):
    R = json.load(open(path)); R["_path"] = os.path.abspath(path); R.setdefault("res_m", 10)
    R["dir"] = os.path.join(os.path.dirname(R["_path"]), "..", "work", R["name"]) if "dir" not in R else R["dir"]
    R["dir"] = os.path.abspath(R["dir"]); os.makedirs(R["dir"], exist_ok=True); return R
def utm_epsg(lon, lat): return (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
def build(R):
    res = R["res_m"]; snap = 2 * res                                   # snap to the 20 m S2 grid so 10 m and 20 m bands nest
    if "bbox_lonlat" in R:
        w, s, e, n = R["bbox_lonlat"]; epsg = R.get("epsg") or utm_epsg((w + e) / 2, (s + n) / 2)
        xs, ys = transform("EPSG:4326", f"EPSG:{epsg}", [w, e, w, e], [s, s, n, n])
        x0, x1 = math.floor(min(xs) / snap) * snap, math.ceil(max(xs) / snap) * snap; y0, y1 = math.floor(min(ys) / snap) * snap, math.ceil(max(ys) / snap) * snap
    else:
        lon, lat = R["center_lonlat"]; rad = R["radius_m"]; epsg = R.get("epsg") or utm_epsg(lon, lat)
        (cx,), (cy,) = transform("EPSG:4326", f"EPSG:{epsg}", [lon], [lat]); cx, cy = round(cx / snap) * snap, round(cy / snap) * snap
        x0, x1, y0, y1 = cx - rad, cx + rad, cy - rad, cy + rad
    G = {"epsg": epsg, "x0": x0, "y0": y1, "res": res, "width": int(round((x1 - x0) / res)), "height": int(round((y1 - y0) / res))}
    json.dump(G, open(os.path.join(R["dir"], "grid.json"), "w"), indent=1); return G
def load_grid(R):
    p = os.path.join(R["dir"], "grid.json"); return json.load(open(p)) if os.path.exists(p) else build(R)
def bounds(G): return (G["x0"], G["y0"] - G["height"] * G["res"], G["x0"] + G["width"] * G["res"], G["y0"])
def bbox_lonlat(G):
    x0, y0, x1, y1 = bounds(G); lons, lats = transform(f"EPSG:{G['epsg']}", "EPSG:4326", [x0, x1, x0, x1], [y0, y0, y1, y1]); return [min(lons), min(lats), max(lons), max(lats)]
def to_rc(G, lon, lat):
    E, N = transform("EPSG:4326", f"EPSG:{G['epsg']}", list(np.atleast_1d(lon)), list(np.atleast_1d(lat)))
    return (G["y0"] - np.array(N)) / G["res"], (np.array(E) - G["x0"]) / G["res"]
def to_lonlat(G, rows, cols):
    E = G["x0"] + np.atleast_1d(cols) * G["res"]; N = G["y0"] - np.atleast_1d(rows) * G["res"]
    lon, lat = transform(f"EPSG:{G['epsg']}", "EPSG:4326", list(E), list(N)); return np.array(lon), np.array(lat)
def valid_disk(G, R):
    """boolean mask of the region proper (a disk when the region is centre+radius, else everything)"""
    if "center_lonlat" not in R: return np.ones((G["height"], G["width"]), bool)
    r, c = to_rc(G, *R["center_lonlat"]); yy, xx = np.ogrid[:G["height"], :G["width"]]; return (yy - r[0]) ** 2 + (xx - c[0]) ** 2 <= (R["radius_m"] / G["res"]) ** 2
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = build(R); print(json.dumps(G), "\nbbox lon/lat", [round(v, 4) for v in bbox_lonlat(G)], f"\n{G['width']}x{G['height']} px at {G['res']} m ->", R["dir"])
