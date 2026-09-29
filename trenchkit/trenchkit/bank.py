"""Multi-width oriented bar (matched) filter bank for line-like earthworks in change rasters.
kernel(theta, w, L): centre bar width w px, length L px; flank bars width FW at +-(w/2 + FW/2 + GAP).  All bars are mean filters (sum 1)."""
import numpy as np, cv2
FW, GAP, S = 3, 1, 8
def bar(theta, off, w, L):
    n = int(L + 2 * abs(off) + w + 8); big = np.zeros((n * S, n * S), "float32"); c = n * S / 2
    dx, dy = np.cos(theta), -np.sin(theta); px, py = -dy, dx
    p0 = (c + S * (off * px - L / 2 * dx), c + S * (off * py - L / 2 * dy)); p1 = (c + S * (off * px + L / 2 * dx), c + S * (off * py + L / 2 * dy))
    cv2.line(big, tuple(int(round(v)) for v in p0), tuple(int(round(v)) for v in p1), 1.0, max(int(round(w * S)), 1))
    k = cv2.resize(big, (n, n), interpolation=cv2.INTER_AREA); return k / k.sum()
def ridge(src, w, L, step=10, signed=False, flank_w=FW, gap=GAP):
    """max over orientations of min(centre - flank1, centre - flank2).  signed=False: positive ridges only.  signed=True: ridges and valleys (abs)."""
    off = w / 2 + flank_w / 2 + gap; resp = np.zeros(src.shape, "float32")
    for th in np.deg2rad(np.arange(0, 180, step)):
        c0 = cv2.filter2D(src, -1, bar(th, 0, w, L)); a1 = c0 - cv2.filter2D(src, -1, bar(th, off, flank_w, L)); a2 = c0 - cv2.filter2D(src, -1, bar(th, -off, flank_w, L))
        r = np.where(np.sign(a1) == np.sign(a2), np.minimum(np.abs(a1), np.abs(a2)), 0) if signed else np.minimum(a1, a2)
        np.maximum(resp, r, out=resp)
    return resp
def mad_sigma(v): m = np.median(v); return 1.4826 * np.median(np.abs(v - m)), m

def scale_per_width(src, widths, L, step_theta=0.0, signed=False, sub=5):
    """robust background scale of the single-orientation response for each bar width (background is ~isotropic)."""
    out = {}
    for w in widths:
        off = w / 2 + FW / 2 + GAP; th = step_theta
        c0 = cv2.filter2D(src, -1, bar(th, 0, w, L)); a1 = c0 - cv2.filter2D(src, -1, bar(th, off, FW, L)); a2 = c0 - cv2.filter2D(src, -1, bar(th, -off, FW, L))
        r = np.where(np.sign(a1) == np.sign(a2), np.minimum(np.abs(a1), np.abs(a2)), 0) if signed else np.minimum(a1, a2)
        v = r[::sub, ::sub]; v = v[(v != 0) & np.isfinite(v)]; out[w] = float(1.4826 * np.median(np.abs(v))) if len(v) else 1.0
    return out
def coherent(src, widths, L1, L2, step=10, signed=False, scales=None, wobble=1, keep_stage1=False):
    """Two-stage oriented line filter.  Stage 1: per orientation, max over bar widths of the scale-normalised min-flank response.
    Stage 2: per orientation, mean of stage-1 (max over theta +- wobble steps) along a bar of length L2 at that orientation.  Returns max over orientations
    (and the stage-1 max-over-theta map if keep_stage1)."""
    if scales is None: scales = scale_per_width(src, widths, L1, signed=signed)
    thetas = np.deg2rad(np.arange(0, 180, step)); n = len(thetas); z = []
    for th in thetas:
        best = None
        for w in widths:
            off = w / 2 + FW / 2 + GAP
            c0 = cv2.filter2D(src, -1, bar(th, 0, w, L1)); a1 = c0 - cv2.filter2D(src, -1, bar(th, off, FW, L1)); a2 = c0 - cv2.filter2D(src, -1, bar(th, -off, FW, L1))
            r = (np.where(np.sign(a1) == np.sign(a2), np.minimum(np.abs(a1), np.abs(a2)), 0) if signed else np.minimum(a1, a2)) / scales[w]
            best = r if best is None else np.maximum(best, r)
        z.append(best.astype("float32"))
    out = np.zeros(src.shape, "float32"); s1max = np.max(z, 0) if keep_stage1 else None
    for i, th in enumerate(thetas):
        zz = z[i].copy()
        for k in range(1, wobble + 1): np.maximum(zz, z[(i - k) % n], out=zz); np.maximum(zz, z[(i + k) % n], out=zz)
        np.maximum(out, cv2.filter2D(zz, -1, bar(th, 0, 3, L2)), out=out)
    return (out, s1max) if keep_stage1 else out
