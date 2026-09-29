"""Ingest a hand-labelled KMZ/KML of trench lines (Google Earth: LineStrings, optionally inside MultiGeometry, grouped by Placemark name).
Writes <region>/labels/<tag>_ids.npy (uint16 line id per pixel, 0 = none) and <tag>_lines.json (id, group, name, length, azimuth, vertices in row/col).
usage: python -m trenchkit.labels region.json path.kmz [tag]"""
import sys, os, json, zipfile, io, math, numpy as np, cv2, xml.etree.ElementTree as ET
from .grid import load_region, load_grid, to_rc
NS = "{http://www.opengis.net/kml/2.2}"
def read_kml(path):
    if path.lower().endswith(".kmz"):
        z = zipfile.ZipFile(path); name = [n for n in z.namelist() if n.lower().endswith(".kml")][0]; root = ET.parse(io.BytesIO(z.read(name))).getroot()
    else: root = ET.parse(path).getroot()
    out = []
    for pm in root.iter(NS + "Placemark"):
        nm = pm.find(NS + "name"); nm = nm.text.strip() if nm is not None and nm.text else "unnamed"
        for gi, ls in enumerate(pm.iter(NS + "LineString")):
            pts = [tuple(map(float, c.split(",")[:2])) for c in ls.find(NS + "coordinates").text.split()]
            if len(pts) >= 2: out.append((nm, gi, pts))
    return out
def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0])); d = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(d))
def ingest(R, kmz, tag="labels"):
    G = load_grid(R); H, W = G["height"], G["width"]; ids = np.zeros((H, W), "uint16"); lines = []; k = 0
    for name, gi, pts in read_kml(kmz):
        rows, cols = to_rc(G, [p[0] for p in pts], [p[1] for p in pts])
        if rows.max() < 0 or cols.max() < 0 or rows.min() >= H or cols.min() >= W: print("outside grid:", name, gi); continue
        k += 1; seg = np.hypot(np.diff(rows), np.diff(cols)) * G["res"]; az = np.degrees(np.arctan2(np.diff(cols), -np.diff(rows))) % 180
        c2 = np.sum(seg * np.cos(np.radians(2 * az))); s2 = np.sum(seg * np.sin(np.radians(2 * az)))
        cv2.polylines(ids, [np.column_stack([cols, rows]).round().astype("int32")], False, int(k), 1)
        lines.append({"id": k, "group": name, "name": f"{name} L{gi}", "len_km": sum(hav(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) / 1000,
                      "azimuth": float((np.degrees(np.arctan2(s2, c2)) / 2) % 180), "straightness": float(np.hypot(c2, s2) / max(seg.sum(), 1e-9)),
                      "rows": rows.round(2).tolist(), "cols": cols.round(2).tolist(), "lonlat": pts,
                      "bbox_rc": [int(max(rows.min(), 0)), int(min(rows.max(), H - 1)), int(max(cols.min(), 0)), int(min(cols.max(), W - 1))]})
    d = os.path.join(R["dir"], "labels"); os.makedirs(d, exist_ok=True); np.save(os.path.join(d, f"{tag}_ids.npy"), ids); json.dump(lines, open(os.path.join(d, f"{tag}_lines.json"), "w"), indent=1)
    print(f"{len(lines)} lines, {sum(l['len_km'] for l in lines):.1f} km, {int((ids > 0).sum())} label px ->", d)
    for l in lines: print(f'  {l["id"]:3d} {l["name"]:30s} {l["len_km"]:6.2f} km az {l["azimuth"]:5.1f} straight {l["straightness"]:.2f}')
    return ids, lines
if __name__ == "__main__":
    ingest(load_region(sys.argv[1]), sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "labels")
