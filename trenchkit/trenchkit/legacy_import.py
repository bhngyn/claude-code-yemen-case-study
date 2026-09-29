"""One-off adapter: expose the earthwork_scan/ products (2021-2026 Tihama run) in the trenchkit layout so the new stages can run on them.
S2 composites are symlinked; the S1 orbit-6 VV means (which only cover grid columns 3000-9999) are written as full-grid float16 arrays.
usage: python -m trenchkit.legacy_import regions/tihama_hays.json /Volumes/T7/yemen-maps/earthwork_scan"""
import sys, os, json, numpy as np
from .grid import load_region, load_grid
R = load_region(sys.argv[1]); G = load_grid(R); src = sys.argv[2]; H, W = G["height"], G["width"]
d2 = os.path.join(R["dir"], "data", "s2"); d1 = os.path.join(R["dir"], "data", "s1"); os.makedirs(d2, exist_ok=True); os.makedirs(d1, exist_ok=True)
EP = {"before": "2021", "2022": "2022", "2023": "2023", "2024": "2024", "2025": "2025", "after": "2026"}
for old, new in EP.items():
    for t in ("38PKA", "38PKB", "38PLA", "38PLB"):
        s, dst = os.path.join(src, f"comp_{old}_{t}.npz"), os.path.join(d2, f"{new}_{t}.npz")
        if os.path.exists(s) and not os.path.exists(dst): os.symlink(s, dst)
C0 = 3000
for old, new in (("before", "before"), ("after", "after")):
    dst = os.path.join(d1, f"o6_vv_{new}.npy")
    if os.path.exists(dst): continue
    a = np.load(os.path.join(src, f"s1mean_{old}.npy"), mmap_mode="r"); full = np.full((H, W), np.nan, "float16"); full[:, C0:C0 + a.shape[1]] = a; np.save(dst, full); print("wrote", dst)
json.dump({"before": ["2021-01-01", "2022-01-15"], "after": ["2026-01-01", "2026-09-21"], "note": "orbit 6 (descending) VV, ~20 dates per epoch, from earthwork_scan/s1_stack.py; columns < 3000 are nodata"}, open(os.path.join(d1, "legacy.json"), "w"), indent=1)
print("S2 epochs:", sorted({f.split("_")[0] for f in os.listdir(d2) if f.endswith(".npz")}), "| S1:", sorted(f for f in os.listdir(d1) if f.endswith(".npy")))
