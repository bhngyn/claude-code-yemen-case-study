"""Line components + ranking from a fused (or any) z map.  Hysteresis (background p97 / p99.7) -> connected components with a strong seed -> skeleton ->
spur pruning -> longest path >= min_len_m -> attributes from every available map -> score.  Writes candidates/<tag>_components.json, <tag>_labels.npy, <tag>.kml.
If labels exist, each component gets label_frac (share of its skeleton within 30 m of a label line) and a hit/miss summary is printed.
Components are extracted from EACH listed map with that map's own thresholds and merged (duplicates of the same line dropped), so a weak map cannot raise
the threshold of a strong one; region["fuse"]["extract"] lists the maps (default: every s1_change map + s2_appear_red).
usage: python -m trenchkit.fuse region.json [map_name ...]"""
import sys, os, json, numpy as np, cv2, warnings
from collections import deque
from skimage.morphology import skeletonize
from skimage.measure import label, regionprops
from .grid import load_region, load_grid, to_lonlat
warnings.filterwarnings("ignore")
def longest_path(sk):
    pts = set(zip(*np.nonzero(sk)))
    def bfs(src):
        dist = {src: 0}; qd = deque([src]); last = src
        while qd:
            p = qd.popleft(); last = p
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    n = (p[0] + dr, p[1] + dc)
                    if n in pts and n not in dist: dist[n] = dist[p] + 1; qd.append(n)
        return last, dist
    best = (0, None, None); seen = set()
    for p0 in list(pts):
        if p0 in seen: continue
        a_, d0 = bfs(p0); seen |= set(d0); b_, d1 = bfs(a_)
        if d1[b_] > best[0]: best = (d1[b_], a_, b_)
    return best
def prune(sk, K=12):
    sk = sk.copy(); ker = np.ones((3, 3), "float32")
    for _ in range(K):
        nb = cv2.filter2D(sk.astype("float32"), -1, ker, borderType=cv2.BORDER_CONSTANT) - sk.astype("float32"); ends = sk & (nb <= 1.5)
        if not ends.any(): break
        sk[ends] = False
    return sk
def trace(sk, a, b):
    """ordered pixel path from a to b along the skeleton (BFS parents)"""
    pts = set(zip(*np.nonzero(sk))); par = {a: None}; qd = deque([a])
    while qd:
        p = qd.popleft()
        if p == b: break
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                n = (p[0] + dr, p[1] + dc)
                if n in pts and n not in par: par[n] = p; qd.append(n)
    path = []; p = b
    while p is not None: path.append(p); p = par.get(p)
    return path[::-1]
MAX_PIECES = 6
def extract(F, valid, res, minpx, lo_pct, hi_pct, name):
    """line components of one z map: hysteresis (its own background p97 / p99.7) -> skeleton -> longest path >= minpx.  Returns raw components with global skeleton coords."""
    H, W = F.shape; bg = np.asarray(F[::30, ::30]).astype("float32")[np.asarray(valid[::30, ::30])]; bg = bg[bg != 0]; q = np.percentile(bg, [50, 90, lo_pct, 99, hi_pct]); lo, hi = q[2], q[4]
    print(f"{name}: background pctl 50/90/{lo_pct}/99/{hi_pct}:", np.round(q, 2), flush=True)
    weak = np.zeros((H, W), bool); strong = np.zeros((H, W), bool)
    for rs in range(0, H, 1000): f = np.asarray(F[rs:rs + 1000]).astype("float32"); weak[rs:rs + 1000] = f > lo; strong[rs:rs + 1000] = f > hi
    weak = cv2.morphologyEx(weak.astype("uint8"), cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))).astype(bool)
    lab = label(weak, connectivity=2); keep = np.unique(lab[strong]); keep = set(keep[keep > 0].tolist()); del weak, strong; out = []
    for rp in regionprops(lab):
        if rp.label not in keep or rp.area < 60: continue
        r0, c0, r1, c1 = rp.bbox
        if max(r1 - r0, c1 - c0) < minpx * 0.6 or min(r1 - r0, c1 - c0) <= 4: continue
        sk0 = skeletonize(rp.image); sk = prune(sk0, 12); slen = int(sk.sum())
        if slen < minpx: continue
        fz = np.asarray(F[r0:r1, c0:c1]).astype("float32"); rem = sk.copy(); piece = 0
        while piece < MAX_PIECES:                                   # peel the longest path, then the next longest of what is left (networks: trench + tracks + bunds)
            path, pa, pb = longest_path(rem)
            if path < minpx: break
            pp = trace(rem, pa, pb); pr = np.array([p[0] for p in pp]); pc = np.array([p[1] for p in pp]); tort = path / max(np.hypot(pa[0] - pb[0], pa[1] - pb[1]), 1.0)
            m = np.zeros(rem.shape, "uint8"); m[pr, pc] = 1; keep_sk = cv2.dilate(m, np.ones((3, 3), "uint8")).astype(bool) & rem       # this path plus its 1-px neighbours
            if tort <= 3.0:
                rr, cc = np.nonzero(keep_sk)
                out.append({"source": name, "bbox": [int(c0), int(r0), int(c1 - c0), int(r1 - r0)], "path_m": path * res, "skel_m": slen * res, "branchiness": float(slen / path), "piece": piece, "tortuosity": float(tort),
                            "sk_r": rr + r0, "sk_c": cc + c0, "path_rc": np.array([[p[0] + r0, p[1] + c0] for p in pp[::3]]), "z_source": float(np.median(fz[keep_sk]))})
            rem &= ~cv2.dilate(m, np.ones((7, 7), "uint8")).astype(bool); piece += 1
            if slen / path <= 1.5: break                            # a simple line: one piece is enough
    print(f"  {name}: {lab.max()} weak components, {len(keep)} with a strong seed, {len(out)} lines >= {minpx * res:.0f} m", flush=True); del lab; return out
def merge(cands, H, W, tol=3, overlap=0.6):
    """union of per-map components: strongest first; a component whose skeleton lies >= overlap within tol px of an accepted one is dropped (duplicate of the same line)"""
    cands = sorted(cands, key=lambda c: -c["z_source"]); taken = np.zeros((H, W), bool); keep = []; k = np.ones((2 * tol + 1, 2 * tol + 1), "uint8")
    for c in cands:
        x, y, w, h = c["bbox"]; r0, c0, r1, c1 = max(y - tol, 0), max(x - tol, 0), min(y + h + tol, H), min(x + w + tol, W)
        frac = taken[c["sk_r"], c["sk_c"]].mean()
        if frac >= overlap: c["_dup"] = True; continue
        m = np.zeros((r1 - r0, c1 - c0), "uint8"); m[c["sk_r"] - r0, c["sk_c"] - c0] = 1; taken[r0:r1, c0:c1] |= cv2.dilate(m, k).astype(bool); c["overlap_prev"] = float(frac); keep.append(c)
    return keep
def run(R, G, names=None, tag="fused", min_len_m=900, lo_pct=97, hi_pct=99.7):
    md = os.path.join(R["dir"], "maps"); cd = os.path.join(R["dir"], "candidates"); os.makedirs(cd, exist_ok=True); valid = np.load(os.path.join(md, "valid.npy"), mmap_mode="r"); res = G["res"]; minpx = int(min_len_m / res)
    names = names or R.get("fuse", {}).get("extract", [f for f in sorted(os.listdir(md)) if f.startswith("s1_change") and f.endswith(".npy") and not f.endswith("_w.npy")] + ["s2_appear_red"])
    names = [n[:-4] if n.endswith(".npy") else n for n in names if os.path.exists(os.path.join(md, (n if n.endswith(".npy") else n + ".npy")))]
    maps = {f[:-4]: np.load(os.path.join(md, f), mmap_mode="r") for f in sorted(os.listdir(md)) if f.endswith(".npy") and f not in ("valid.npy", "veg.npy", "busy.npy") and not f.endswith(("_w.npy", "_sign.npy"))}
    H, W = valid.shape; raw = []
    for n in names: raw += extract(maps[n], valid, res, minpx, lo_pct, hi_pct, n)
    comps = merge(raw, H, W); print(f"{len(raw)} raw components from {names} -> {len(comps)} after de-duplication", flush=True)
    signs = {f[:-9]: np.load(os.path.join(md, f), mmap_mode="r") for f in os.listdir(md) if f.endswith("_sign.npy")}
    busy = np.load(os.path.join(md, "busy.npy"), mmap_mode="r") if os.path.exists(os.path.join(md, "busy.npy")) else None; veg = np.load(os.path.join(md, "veg.npy"), mmap_mode="r") if os.path.exists(os.path.join(md, "veg.npy")) else None
    ld = os.path.join(R["dir"], "labels"); ids = np.load(os.path.join(ld, "labels_ids.npy"), mmap_mode="r") if os.path.exists(os.path.join(ld, "labels_ids.npy")) else None
    lab = np.zeros((H, W), "int32")
    for i, c in enumerate(comps, 1):
        rr, cc = c.pop("sk_r"), c.pop("sk_c"); c["bbox"] = [int(cc.min()), int(rr.min()), int(cc.max() - cc.min() + 1), int(rr.max() - rr.min() + 1)]
        x, y, w, h = c["bbox"]; r0, r1, c0, c1 = y, y + h, x, x + w; sk = np.zeros((h, w), bool); sk[rr - y, cc - x] = True
        c["label"] = i; c["row"] = float(rr.mean()); c["col"] = float(cc.mean()); c["path_rc"] = c["path_rc"].tolist()
        m = np.zeros((h, w), "uint8"); m[rr - y, cc - x] = 1; m = cv2.dilate(m, np.ones((3, 3), "uint8")).astype(bool); sub = lab[r0:r1, c0:c1]; sub[m & (sub == 0)] = i
        for k, mp in maps.items(): z = np.asarray(mp[r0:r1, c0:c1]).astype("float32")[sk]; c["z_" + k] = float(np.median(z)); c["frac3_" + k] = float((z > 3).mean())
        c["z_fused"] = float(np.median(np.asarray(maps["fused"][r0:r1, c0:c1]).astype("float32")[sk])) if "fused" in maps else c["z_source"]
        for k, sg in signs.items(): c["bright_frac_" + k] = float((np.asarray(sg[r0:r1, c0:c1])[sk] > 0).mean())
        c["busy"] = float(np.asarray(busy[r0:r1, c0:c1])[sk].mean()) if busy is not None else 0.0; c["veg"] = float(np.asarray(veg[r0:r1, c0:c1])[sk].mean()) if veg is not None else 0.0
        if ids is not None: near = cv2.dilate((np.asarray(ids[r0:r1, c0:c1]) > 0).astype("uint8"), np.ones((7, 7), "uint8")).astype(bool); c["label_frac"] = float(near[sk].mean())
    lon, lat = to_lonlat(G, [c["row"] for c in comps], [c["col"] for c in comps])
    for c, x, y in zip(comps, lon, lat): c["lon"], c["lat"] = float(x), float(y)
    zk = [k for k in maps if k != "fused"]
    for c in comps:
        zs = sorted([max(c["z_" + k] - 1.5, 0) for k in zk], reverse=True); ev = zs[0] + 0.7 * sum(zs[1:])          # strongest source + joint-evidence bonus
        c["score"] = c["path_m"] / 1000 * ev * (1 - 0.9 * c["busy"]) * (1 - 0.6 * c["veg"]) * min(1.0, 1.6 / c["tortuosity"]) * min(1.0, 1.8 / c["branchiness"])
    comps.sort(key=lambda c: -c["score"])
    for i, c in enumerate(comps): c["rank"] = i + 1
    np.save(os.path.join(cd, f"{tag}_labels.npy"), lab); json.dump(comps, open(os.path.join(cd, f"{tag}_components.json"), "w"))
    print(len(comps), f"line components >= {min_len_m} m; by source:", {n: sum(c["source"] == n for c in comps) for n in names})
    write_kml(R, G, comps, os.path.join(cd, f"{tag}.kml"), zk)
    if ids is not None: label_summary(R, comps, ids, lab)
    return comps
def write_kml(R, G, comps, path, zk, top=300):
    pm = []
    for c in comps[:top]:
        rc = np.array(c["path_rc"]); lon, lat = to_lonlat(G, rc[:, 0], rc[:, 1]); cs = " ".join(f"{a:.6f},{b:.6f},0" for a, b in zip(lon, lat))
        col = "ff2828ff" if c["rank"] <= 50 else ("ff28a8ff" if c["rank"] <= 150 else "ff28d0d0"); desc = f"{c['path_m']/1000:.1f} km; score {c['score']:.1f}; " + "; ".join(f"{k} z={c['z_' + k]:.1f}" for k in zk) + f"; busy {c['busy']:.2f}" + (f"; label_frac {c['label_frac']:.2f}" if "label_frac" in c else "")
        pm.append(f"<Placemark><name>r{c['rank']} ({c['path_m']/1000:.1f} km)</name><description>{desc}</description><Style><LineStyle><color>{col}</color><width>3</width></LineStyle></Style><LineString><tessellate>1</tessellate><coordinates>{cs}</coordinates></LineString></Placemark>")
    open(path, "w").write(f'<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>{R["name"]} candidates (top {min(top, len(comps))}; red = rank 1-50, orange = 51-150, yellow = rest)</name>' + "".join(pm) + "</Document></kml>")
    print("kml", path)
def label_summary(R, comps, ids, lab):
    """label km covered by components at rank <= N, and share of the top N that touch a label"""
    lines = json.load(open(os.path.join(R["dir"], "labels", "labels_lines.json"))); res = load_grid(R)["res"]
    keep = {c["label"]: c["rank"] for c in comps}; H, W = lab.shape; hitrank = np.full(len(lines) + 1, 10 ** 9)
    for l in lines:
        r0, r1, c0, c1 = l["bbox_rc"]; r0, c0 = max(r0 - 6, 0), max(c0 - 6, 0); sub = np.asarray(lab[r0:r1 + 7, c0:c1 + 7]); lm = np.asarray(ids[r0:r1 + 7, c0:c1 + 7]) == l["id"]
        nearlab = cv2.dilate(lm.astype("uint8"), np.ones((7, 7), "uint8")).astype(bool); ranks = [keep[v] for v in np.unique(sub[nearlab]) if v in keep]
        l["_ranks"] = sorted(ranks)
        # covered fraction per rank cutoff
        l["_cov"] = {}
        for N in (25, 50, 100, 200, 400):
            good = np.isin(sub, [v for v in np.unique(sub) if v in keep and keep[v] <= N]); near = cv2.dilate(good.astype("uint8"), np.ones((7, 7), "uint8")).astype(bool); l["_cov"][N] = float(near[lm].mean()) if lm.any() else 0
    km = sum(l["len_km"] for l in lines)
    print("\nLabel coverage by ranked components (share of label km within 30 m of a component ranked <= N) and precision proxy (share of top-N components touching a label):")
    for N in (25, 50, 100, 200, 400):
        cov = sum(l["_cov"][N] * l["len_km"] for l in lines) / km; top = comps[:N]; prec = np.mean([c.get("label_frac", 0) > 0.3 for c in top]) if top else 0
        print(f"  top {N:3d}: label km covered {cov:5.2f} | components touching a label (>30 % of their length) {prec:5.2f}")
    for l in lines: print(f'  {l["name"]:30s} {l["len_km"]:5.1f} km  best rank {l["_ranks"][0] if l["_ranks"] else "-":>5}  ranks {l["_ranks"][:6]}  covered@100 {l["_cov"][100]:.2f}')
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); names = [a for a in sys.argv[2:] if not a.startswith("--")] or None; run(R, G, names)
