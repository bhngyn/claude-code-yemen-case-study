"""Line-response ("signature") maps on the region grid, tiled to fit in 8 GB.  Each map is a float16 z-score grid in <region>/maps/ (0 = invalid).
Signatures (region["detect"] overrides the defaults below):
  s1_change   per orbit/pol: dB(after) - dB(before), detrended (301 px), positive-ridge bar bank  -> new rough/bright lines (spoil, berms, cut faces)
  s1_static   dB(after) detrended, positive-ridge bank                                          -> lines that are radar-bright now, whenever they were made
  s2_change   mean(post epochs) - before epoch, signed bank                                       -> persistent optical line change of either sign (bright spoil / dark trench)
  s2_appear   mean over post epochs of the per-epoch signed static line z, minus the before-epoch static z -> a line that is there in every later epoch and was not there before
  fused       for every pixel, max over k of (sum of the k largest z) / sqrt(k)                    -> single-sensor lines survive, joint evidence is rewarded
S1 is co-registered to the S2 grid by phase correlation (integer shift, maps/registration.json).
usage: python -m trenchkit.detect region.json [signature ...]"""
import sys, os, json, time, numpy as np, cv2
from .grid import load_region, load_grid, valid_disk
from .fetch_s2 import mosaic, masks
from .bank import ridge
TILE, STEP = 2500, 10
DEFAULT = {"s1_change": {"L": 61, "widths": [1, 3, 5, 9]}, "s1_static": {"L": 61, "widths": [1, 3, 5]}, "s2_change": {"L": 61, "widths": [1, 3]}, "s2_appear": {"L": 61, "widths": [1, 3]},
           "fuse": ["s1_change", "s2_change", "s1_static", "s2_appear"], "s1_dilate_water_px": 15}
def cfg(R): c = dict(DEFAULT); c.update(R.get("detect", {})); return c
def mdir(R): d = os.path.join(R["dir"], "maps"); os.makedirs(d, exist_ok=True); return d
def post_epochs(R): return [e for e in R["epochs"] if e > R["before"]]
def valid_mask(R, G, force=False):
    p = os.path.join(mdir(R), "valid.npy")
    if os.path.exists(p) and not force: return np.load(p)
    k = lambda n: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (n, n)); water, veg, seam = masks(R, G, list(R["epochs"]))
    v = valid_disk(G, R) & ~cv2.dilate(water.astype("uint8"), k(15)).astype(bool) & ~cv2.dilate(seam.astype("uint8"), k(9)).astype(bool)
    np.save(p, v); np.save(os.path.join(mdir(R), "veg.npy"), veg); return v
def bank_tiled(src, w, L, signed=False):
    H, W = src.shape; OV = L // 2 + 40; pos = np.zeros((H, W), "float16"); neg = np.zeros((H, W), "float16") if signed else None
    for r0 in range(0, H, TILE):
        for c0 in range(0, W, TILE):
            r1, c1 = min(r0 + TILE, H), min(c0 + TILE, W); rr0, cc0 = max(r0 - OV, 0), max(c0 - OV, 0); rr1, cc1 = min(r1 + OV, H), min(c1 + OV, W); sub = src[rr0:rr1, cc0:cc1]
            pos[r0:r1, c0:c1] = ridge(sub, w, L, step=STEP)[r0 - rr0:r1 - rr0, c0 - cc0:c1 - cc0]
            if signed: neg[r0:r1, c0:c1] = ridge(-sub, w, L, step=STEP)[r0 - rr0:r1 - rr0, c0 - cc0:c1 - cc0]
    return pos, neg
def zbank(src, widths, L, valid, signed=False, log=""):
    """max over bar widths of the background-normalised bank response; returns (z float32, argmax width uint8, sign int8 or None, {w: (sigma, median)})"""
    H, W = src.shape; zmax = np.full((H, W), -1e4, "float32"); warg = np.zeros((H, W), "uint8"); sgn = np.zeros((H, W), "int8") if signed else None; scales = {}
    for w in widths:
        t0 = time.time(); pos, neg = bank_tiled(src, w, L, signed)
        for rs in range(0, H, 1000):
            p = pos[rs:rs + 1000].astype("float32")
            if signed: n = neg[rs:rs + 1000].astype("float32"); s = np.where(n > p, -1, 1).astype("int8"); p = np.maximum(p, n); neg[rs:rs + 1000] = s.astype("float16")
            p[~valid[rs:rs + 1000]] = 0; pos[rs:rs + 1000] = p.astype("float16")
        v = pos[valid][::11].astype("float32"); v = v[v != 0]; sig = float(1.4826 * np.median(np.abs(v - np.median(v)))) if len(v) else 1.0; med = float(np.median(v)) if len(v) else 0.0; scales[str(w)] = (sig, med)
        for rs in range(0, H, 1000):
            z = (pos[rs:rs + 1000].astype("float32") - med) / max(sig, 1e-9); z[~valid[rs:rs + 1000]] = -1e4; up = z > zmax[rs:rs + 1000]; zmax[rs:rs + 1000][up] = z[up]; warg[rs:rs + 1000][up] = w
            if signed: sgn[rs:rs + 1000][up] = neg[rs:rs + 1000].astype("int8")[up]
        del pos, neg; print(f"  {log} w={w} sigma={sig:.4f} med={med:.4f} {time.time() - t0:.0f}s", flush=True)
    zmax[~valid] = 0; return zmax, warg, sgn, scales
def save(R, name, z, extra=None):
    d = mdir(R); np.save(os.path.join(d, name + ".npy"), z.astype("float16"))
    for k, v in (extra or {}).items(): np.save(os.path.join(d, f"{name}_{k}.npy"), v)
    print("saved", name, flush=True)
def s1_pairs(R):
    d = os.path.join(R["dir"], "data", "s1"); out = []
    for f in sorted(os.listdir(d)):
        if f.endswith("_after.npy") and f.startswith("o"): o, pol = f[:-10].split("_"); out.append((o[1:], pol))
    return out
def hp(a): a = np.nan_to_num(a.astype("float32")); return a - cv2.GaussianBlur(a, (0, 0), 3)
def coregister(R, G, o, pol, maxshift=4):
    """integer (dy, dx) roll that moves the S1 'after' mean onto the S2 'after' composite.  Raw SAR/optical intensities do not correlate, but their
    LINE maps do (roads, tracks, bunds, wadi banks appear in both), so: on a 7x7 lattice of 600 px windows, build the signed bar-filter line response
    (w=3, L=31) of both sensors and sweep integer shifts of +-maxshift px for the best summed correlation.  region["s1"]["shift"][f"o{o}_{pol}"] overrides.
    Stored in maps/registration.json."""
    p = os.path.join(mdir(R), "registration.json"); reg = json.load(open(p)) if os.path.exists(p) else {}
    if f"{o}_{pol}" in reg: return tuple(reg[f"{o}_{pol}"]["shift"])
    ov = R.get("s1", {}).get("shift", {}).get(f"o{o}_{pol}")
    if ov: reg[f"{o}_{pol}"] = {"shift": list(ov), "source": "region config"}; json.dump(reg, open(p, "w"), indent=1); return tuple(ov)
    a = np.load(os.path.join(R["dir"], "data", "s1", f"o{o}_{pol}_after.npy"), mmap_mode="r"); H, W = a.shape; M = maxshift; S = int(min(600, max(128, min(H, W) // 3))); pairs = []
    def lines_(x): x = np.nan_to_num(x.astype("float32")); x -= cv2.blur(x, (101, 101)); r = np.maximum(ridge(x, 3, 31, step=15), ridge(-x, 3, 31, step=15)); r -= r.mean(); return r / (r.std() + 1e-9)
    for r in np.linspace(M, H - S - M, 7).astype(int):
        for c in np.linspace(M, W - S - M, 7).astype(int):
            x = np.asarray(a[r - M:r + S + M, c - M:c + S + M]).astype("float32")
            if np.isfinite(x).mean() < 0.95: continue
            y = mosaic(R, G, R["after"], "red", window=(r, r + S, c, c + S))
            if np.isfinite(y).mean() < 0.95: continue
            pairs.append((lines_(np.clip(x, -30, 5)), lines_(y)))
    if len(pairs) < 3: print(f"coregister o{o} {pol}: only {len(pairs)} usable windows, assuming (0, 0)"); shift, table = (0, 0), {}
    else:
        table = {}
        for dy in range(-M, M + 1):
            for dx in range(-M, M + 1):
                table[f"{dy},{dx}"] = float(np.mean([np.mean(xs[M + dy:M + dy + S, M + dx:M + dx + S] * ys) for xs, ys in pairs]))     # S1 content at (r+dy, c+dx) compared with S2 at (r, c)
        best = max(table, key=table.get); dy, dx = map(int, best.split(",")); shift = (-dy, -dx)                                          # roll S1 by -(dy, dx) to align
    reg[f"{o}_{pol}"] = {"shift": list(shift), "n_windows": len(pairs), "corr_table": table}; json.dump(reg, open(p, "w"), indent=1)
    if table: print(f"coregister o{o} {pol}: roll S1 by (dy, dx) = {shift} from {len(pairs)} windows; corr best {table[best]:.3f} vs unshifted {table['0,0']:.3f}", flush=True)
    return shift
def s1_load(R, G, o, pol, ep, shift):
    a = np.load(os.path.join(R["dir"], "data", "s1", f"o{o}_{pol}_{ep}.npy"), mmap_mode="r"); x = np.asarray(a).astype("float32")
    if shift != (0, 0): x = np.roll(x, shift, axis=(0, 1))
    return x
def detrend(x, valid, k=301):
    x[~np.isfinite(x)] = 0; x[~valid] = 0; x -= cv2.blur(x, (k, k)); x[~valid] = 0; return x
def sig_s1_change(R, G, valid, c):
    for o, pol in s1_pairs(R):
        sh = coregister(R, G, o, pol); a = s1_load(R, G, o, pol, "after", sh); b = s1_load(R, G, o, pol, "before", sh); d = a - b; del a, b
        v = valid & np.isfinite(d); d = np.clip(detrend(d, v), -8, 8); z, w, _, sc = zbank(d, c["s1_change"]["widths"], c["s1_change"]["L"], v, log=f"s1_change o{o} {pol}")
        save(R, f"s1_change_o{o}_{pol}", z, {"w": w}); json.dump(sc, open(os.path.join(mdir(R), f"s1_change_o{o}_{pol}_scales.json"), "w")); del d, z, w
def sig_s1_static(R, G, valid, c):
    for o, pol in s1_pairs(R):
        sh = coregister(R, G, o, pol); a = s1_load(R, G, o, pol, "after", sh); v = valid & np.isfinite(a); a = np.clip(a, -30, 5); a = detrend(a, v)
        z, w, _, sc = zbank(a, c["s1_static"]["widths"], c["s1_static"]["L"], v, log=f"s1_static o{o} {pol}"); save(R, f"s1_static_o{o}_{pol}", z, {"w": w}); del a, z, w
def sig_s2_change(R, G, valid, c, band="red"):
    post = post_epochs(R); acc = mosaic(R, G, post[0], band); cnt = np.isfinite(acc).astype("uint8"); acc = np.nan_to_num(acc)
    for e in post[1:]: m = mosaic(R, G, e, band); ok = np.isfinite(m); acc[ok] += m[ok]; cnt += ok; del m
    b = mosaic(R, G, R["before"], band); v = valid & (cnt >= max(1, len(post) - 1)) & np.isfinite(b); D = np.where(v, acc / np.maximum(cnt, 1) - np.nan_to_num(b), 0).astype("float32"); del acc, b
    D -= np.median(D[v][::7]); D[~v] = 0
    busy = cv2.blur((np.abs(D) > 0.04).astype("float32"), (61, 61)) > 0.20; np.save(os.path.join(mdir(R), "busy.npy"), busy); del busy      # farmland / dense change
    z, w, s, sc = zbank(D, c["s2_change"]["widths"], c["s2_change"]["L"], v, signed=True, log=f"s2_change {band}"); save(R, f"s2_change_{band}", z, {"w": w, "sign": s}); del D, z
def sig_s2_appear(R, G, valid, c, band="red"):
    post = post_epochs(R); acc = None
    for e in [R["before"]] + post:
        x = mosaic(R, G, e, band); v = valid & np.isfinite(x); x = np.nan_to_num(x); x[~v] = 0; x -= cv2.blur(x, (101, 101)); x[~v] = 0
        z, _, _, _ = zbank(x, c["s2_appear"]["widths"], c["s2_appear"]["L"], v, signed=True, log=f"s2_static {e}"); del x
        if e == R["before"]: acc = -z
        else: acc += z / len(post)
        del z
    save(R, f"s2_appear_{band}", acc)
def fuse(R, names, out="fused"):
    d = mdir(R); arrs = [np.load(os.path.join(d, n + ".npy"), mmap_mode="r") for n in names]; H, W = arrs[0].shape; F = np.zeros((H, W), "float16")
    for rs in range(0, H, 500):
        Z = np.stack([np.asarray(a[rs:rs + 500]).astype("float32") for a in arrs]); Z = -np.sort(-Z, axis=0); cs = np.cumsum(Z, 0) / np.sqrt(np.arange(1, len(arrs) + 1))[:, None, None]
        F[rs:rs + 500] = cs.max(0).astype("float16")
    np.save(os.path.join(d, out + ".npy"), F); json.dump({"inputs": names}, open(os.path.join(d, out + "_inputs.json"), "w")); print("fused", names, "->", out, flush=True)
def fuse_inputs(R, c):
    d = mdir(R); want = c["fuse"]; names = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".npy") and any(f.startswith(w) for w in want) and not any(f.endswith(s) for s in ("_w.npy", "_sign.npy")): names.append(f[:-4])
    return names
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); c = cfg(R); which = sys.argv[2:] or ["s1_change", "s2_change", "s1_static", "s2_appear", "fuse"]; valid = valid_mask(R, G); t0 = time.time()
    for s in which:
        print(f"== {s} ({time.time() - t0:.0f}s)", flush=True)
        if s == "s1_change": sig_s1_change(R, G, valid, c)
        elif s == "s1_static": sig_s1_static(R, G, valid, c)
        elif s == "s2_change": sig_s2_change(R, G, valid, c)
        elif s == "s2_appear": sig_s2_appear(R, G, valid, c)
        elif s == "fuse": fuse(R, fuse_inputs(R, c))
    print(f"detect done {time.time() - t0:.0f}s")
