"""Per-component feature vectors for ranking.  For every candidate (skeleton path from fuse), cross-section profiles (+-300 m, every 3rd path pixel)
are sampled in: each S2 epoch (red), each S1 orbit/pol before & after.  Features = flank-relative contrast at the line per epoch, its persistence,
the appearance step, S1 change/static contrast and width, plus the geometric and map attributes fuse already computed.
usage: python -m trenchkit.features region.json [tag=fused]   -> candidates/<tag>_features.json"""
import sys, os, json, numpy as np, cv2
from scipy.ndimage import map_coordinates
from .grid import load_region, load_grid
from .fetch_s2 import mosaic_cached
T = np.arange(-30, 31); FL = np.r_[5:20, 41:56]           # flank samples: 100-250 m either side
def profile(arr, R, C, nr, nc, r0, c0):
    rows = R[:, None] + T[None, :] * nr[:, None] - r0; cols = C[:, None] + T[None, :] * nc[:, None] - c0
    P = map_coordinates(arr, [rows.ravel(), cols.ravel()], order=1, mode="nearest").reshape(len(R), len(T)); return P - np.median(P[:, FL], 1, keepdims=True)
def stats(P):
    med = np.median(P, 0); pk = int(np.argmax(np.abs(med[27:34]))) + 27; c = float(med[pk]); half = np.abs(med) > abs(c) / 2; lo = hi = pk
    while lo > 0 and half[lo - 1]: lo -= 1
    while hi < 60 and half[hi + 1]: hi += 1
    return c, int((hi - lo + 1) * 10), float(np.median(P[:, 28:33].max(1) if c > 0 else P[:, 28:33].min(1)))     # contrast, width m, per-point median of the line value
def run(R, G, tag="fused"):
    cd = os.path.join(R["dir"], "candidates"); comps = json.load(open(os.path.join(cd, f"{tag}_components.json"))); md = os.path.join(R["dir"], "maps")
    reg = json.load(open(os.path.join(md, "registration.json"))) if os.path.exists(os.path.join(md, "registration.json")) else {}
    eps = list(R["epochs"]); post = [e for e in eps if e > R["before"]]; S2 = {e: mosaic_cached(R, G, e, "red") for e in eps}
    s1 = {}
    for f in sorted(os.listdir(os.path.join(R["dir"], "data", "s1"))):
        if f.endswith("_after.npy"): k = f[:-10]; s1[k] = (np.load(os.path.join(R["dir"], "data", "s1", f.replace("_after", "_before")), mmap_mode="r"), np.load(os.path.join(R["dir"], "data", "s1", f), mmap_mode="r"), reg.get(k[1:], {}).get("shift", [0, 0]))
    feats = []
    for c in comps:
        rc = np.array(c["path_rc"], "float32"); Rr, Cc = rc[:, 0], rc[:, 1]
        if len(Rr) < 8: k = np.ones(3) / 3
        else: k = np.ones(7) / 7
        rs = np.convolve(np.pad(Rr, len(k) // 2, "edge"), k, "valid"); cs = np.convolve(np.pad(Cc, len(k) // 2, "edge"), k, "valid"); tr, tc = np.gradient(rs), np.gradient(cs); n = np.hypot(tr, tc) + 1e-9; nr, nc = -tc / n, tr / n
        r0, r1 = int(Rr.min()) - 35, int(Rr.max()) + 36; c0, c1 = int(Cc.min()) - 35, int(Cc.max()) + 36; r0, c0 = max(r0, 0), max(c0, 0); f = {"rank": c["rank"], "label": c["label"]}
        ep_c = {}
        for e in eps:
            a = np.nan_to_num(np.asarray(S2[e][r0:r1, c0:c1]).astype("float32")); con, wid, _ = stats(profile(a, Rr, Cc, nr, nc, r0, c0)); ep_c[e] = con * 1e4; f[f"s2c_{e}"] = con * 1e4
            if e == R["after"]: f["s2_width_m"] = wid
        pc = np.array([ep_c[e] for e in post]); b = ep_c[R["before"]]
        f["s2_before_abs"] = abs(b); f["s2_post_mean"] = float(pc.mean()); f["s2_post_absmean"] = float(np.abs(pc).mean()); f["s2_post_min_abs"] = float(np.abs(pc).min()); f["s2_step"] = float(pc.mean() - b); f["s2_step_abs"] = abs(float(pc.mean() - b))
        f["s2_persist"] = float(np.mean(np.sign(pc) == np.sign(pc.mean()))); f["s2_post_sd"] = float(pc.std()); f["s2_max_abs"] = float(np.abs(pc).max())
        for k, (bf, af, sh) in s1.items():
            wa = np.asarray(af[r0 - sh[0]:r1 - sh[0], c0 - sh[1]:c1 - sh[1]]).astype("float32"); wb = np.asarray(bf[r0 - sh[0]:r1 - sh[0], c0 - sh[1]:c1 - sh[1]]).astype("float32")
            d = np.nan_to_num(wa - wb); ca, wida, _ = stats(profile(np.nan_to_num(np.clip(wa, -30, 5)), Rr, Cc, nr, nc, r0, c0)); cd_, widd, _ = stats(profile(np.clip(d, -8, 8), Rr, Cc, nr, nc, r0, c0)); cb, _, _ = stats(profile(np.nan_to_num(np.clip(wb, -30, 5)), Rr, Cc, nr, nc, r0, c0))
            f[f"s1chg_{k}"] = cd_; f[f"s1chg_w_{k}"] = widd; f[f"s1after_{k}"] = ca; f[f"s1after_w_{k}"] = wida; f[f"s1before_{k}"] = cb
        for k in ("path_m", "skel_m", "z_fused", "branchiness", "tortuosity", "busy", "veg", "label_frac"):
            if k in c: f[k] = c[k]
        for k, v in c.items():
            if k.startswith(("z_", "frac3_", "bright_frac_")): f[k] = v
        f["straightness"] = float(np.hypot(Rr[-1] - Rr[0], Cc[-1] - Cc[0]) / max(len(Rr) * 3, 1)); feats.append(f)
        if len(feats) % 200 == 0: print(len(feats), "components featurised", flush=True)
    json.dump(feats, open(os.path.join(cd, f"{tag}_features.json"), "w")); print(len(feats), "feature rows ->", os.path.join(cd, f"{tag}_features.json")); return feats
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); run(R, G, sys.argv[2] if len(sys.argv) > 2 else "fused")
