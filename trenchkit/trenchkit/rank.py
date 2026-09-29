"""Learned ranker over component features.  Positives = components with label_frac >= 0.5; negatives = label_frac == 0.
Model: standardised features -> L2 logistic regression (interpretable weights) and a gradient-boosting classifier; the report shows both.
Validation: leave-one-label-group-out (each group of the KMZ held out in turn) -> how many label km a new area's trenches would need to be reviewed
(coverage of held-out label km within the top N ranked components) compared with the hand-tuned score.
usage: python -m trenchkit.rank region.json [tag=fused] [--apply model.json]   (train on this region; --apply scores this region's components with a saved model)"""
import sys, os, json, numpy as np
from .grid import load_region
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
SKIP = ("rank", "label", "label_frac", "score")
def matrix(feats, names=None):
    names = names or sorted(k for k in feats[0] if k not in SKIP and isinstance(feats[0][k], (int, float)))
    X = np.array([[f.get(k, 0.0) for k in names] for f in feats], "float64"); X = np.nan_to_num(X); return X, names
def group_of(feats, R, comps_labels=None):
    """which label group each positive component belongs to (majority of the labels it touches)"""
    import cv2
    ld = os.path.join(R["dir"], "labels"); ids = np.load(os.path.join(ld, "labels_ids.npy"), mmap_mode="r"); lines = {l["id"]: l["group"] for l in json.load(open(os.path.join(ld, "labels_lines.json")))}
    comps = {c["label"]: c for c in json.load(open(os.path.join(R["dir"], "candidates", "fused_components.json")))}; out = []
    for f in feats:
        c = comps[f["label"]]; x, y, w, h = c["bbox"]; rc = np.array(c["path_rc"]); sub = np.asarray(ids[y:y + h, x:x + w]); near = cv2.dilate(sub, np.ones((7, 7), "uint8"))
        v = near[np.clip(rc[:, 0] - y, 0, h - 1), np.clip(rc[:, 1] - x, 0, w - 1)]; v = v[v > 0]
        out.append(lines[int(np.bincount(v).argmax())] if len(v) else None)
    return out
def coverage(order, feats, R, N=(25, 50, 100, 200)):
    """label km covered when reviewing the top N of a ranking (km credited by label_frac * path length, capped by label km)"""
    ld = os.path.join(R["dir"], "labels"); km = sum(l["len_km"] for l in json.load(open(os.path.join(ld, "labels_lines.json")))); out = {}
    for n in N: out[n] = min(sum(feats[i]["label_frac"] * feats[i]["path_m"] / 1000 for i in order[:n]) / km, 1.0)
    return out
def fit(X, y, kind):
    mu, sd = X.mean(0), X.std(0) + 1e-9; Xs = (X - mu) / sd
    m = LogisticRegression(C=0.3, class_weight="balanced", max_iter=2000).fit(Xs, y) if kind == "logreg" else HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_depth=4, class_weight="balanced", random_state=0).fit(Xs, y)
    return m, mu, sd
def predict(m, mu, sd, X): return m.predict_proba((X - mu) / sd)[:, 1]
def run(R, tag="fused"):
    cd = os.path.join(R["dir"], "candidates"); feats = json.load(open(os.path.join(cd, f"{tag}_features.json"))); X, names = matrix(feats); lf = np.array([f.get("label_frac", 0) for f in feats])
    POS = R.get("rank", {}).get("pos_frac", 0.3); y = (lf >= POS).astype(int); use = (lf >= POS) | (lf == 0); grp = group_of(feats, R); groups = sorted({g for g in grp if g})
    print(f"{len(feats)} components, {y.sum()} positives (label_frac >= {POS}), {int((lf == 0).sum())} negatives ({int(((lf > 0) & (lf < POS)).sum())} ambiguous excluded), {len(names)} features; label groups: {groups}")
    base = list(np.argsort([-f["rank"] * -1 for f in feats]))     # existing rank order
    base = sorted(range(len(feats)), key=lambda i: feats[i]["rank"])
    print("\nLeave-one-group-out: label km of the held-out group covered by the top N (only that group's km count), hand score vs learned")
    ldk = {l["group"]: 0 for l in json.load(open(os.path.join(R["dir"], "labels", "labels_lines.json")))}
    for l in json.load(open(os.path.join(R["dir"], "labels", "labels_lines.json"))): ldk[l["group"]] += l["len_km"]
    res = {}
    for g in groups:
        test = np.array([gg == g for gg in grp]); train = use & ~test & np.array([gg != g for gg in grp]); km = ldk[g]
        def cov(order, N=(25, 50, 100, 200)): return {n: min(sum(feats[i]["label_frac"] * feats[i]["path_m"] / 1000 for i in order[:n] if grp[i] == g) / km, 1.0) for n in N}
        # ranking for the test: all non-training components (held-out positives + every negative) so precision pressure is realistic
        cand = [i for i in range(len(feats)) if not (train[i] and y[i] == 1)]
        row = {"hand": cov(sorted(cand, key=lambda i: feats[i]["rank"]))}; probs = {}
        for kind in ("logreg", "gbm"):
            m, mu, sd = fit(X[train], y[train], kind); p = predict(m, mu, sd, X[cand]); probs[kind] = p; row[kind] = cov([cand[i] for i in np.argsort(-p)])
        row["blend"] = cov([cand[i] for i in np.argsort(-(0.5 * probs["logreg"] + 0.5 * probs["gbm"]))])
        res[g] = row; print(f"  {g:22s} ({km:5.1f} km): " + " | ".join(f"{k:6s} " + " ".join(f"@{n}={v:.2f}" for n, v in d.items()) for k, d in row.items()))
    tot = {k: sum(res[g][k][100] * ldk[g] for g in groups) / sum(ldk[g] for g in groups) for k in ("hand", "logreg", "gbm", "blend")}
    print("held-out label km covered in the top 100, km-weighted over the groups:", {k: round(v, 3) for k, v in tot.items()})
    use_learned = y[use].sum() >= 20 and tot["blend"] > 1.05 * tot["hand"]
    print("RANKING USED:", "learned blend (beats the hand score out of sample)" if use_learned else "hand score (learned ranker not validated: too few positives or no out-of-sample gain)")
    # final models on everything, saved with the feature names for use in other regions
    models = {}
    for kind in ("logreg", "gbm"):
        m, mu, sd = fit(X[use], y[use], kind); p = predict(m, mu, sd, X); models[kind] = p
        if kind == "logreg":
            w = sorted(zip(m.coef_[0], names), key=lambda t: -abs(t[0])); print("\nlogistic weights (standardised features), strongest first:"); [print(f"  {n:28s} {c:+.2f}") for c, n in w[:18]]
            json.dump({"names": names, "mu": mu.tolist(), "sd": sd.tolist(), "coef": m.coef_[0].tolist(), "intercept": float(m.intercept_[0]), "region": R["name"], "positives": int(y[use].sum()), "negatives": int((y[use] == 0).sum())}, open(os.path.join(cd, f"{tag}_ranker_logreg.json"), "w"), indent=1)
    order = np.argsort(-(0.5 * models["logreg"] + 0.5 * models["gbm"]))
    print("\nIn-sample (optimistic) coverage of all label km, hand score vs learned blend:", {k: round(v, 3) for k, v in coverage(base, feats, R).items()}, {k: round(v, 3) for k, v in coverage(list(order), feats, R).items()})
    comps = json.load(open(os.path.join(cd, f"{tag}_components.json"))); pmap = {f["label"]: (float(models["logreg"][i]), float(models["gbm"][i])) for i, f in enumerate(feats)}
    for c in comps: c["p_logreg"], c["p_gbm"] = pmap.get(c["label"], (0, 0)); c["p_learned"] = 0.5 * (c["p_logreg"] + c["p_gbm"]); c["ranking_used"] = "learned" if use_learned else "hand"
    comps.sort(key=lambda c: (-c["p_learned"] if use_learned else c["rank"]))
    for i, c in enumerate(comps): c["rank_learned"] = i + 1
    json.dump(comps, open(os.path.join(cd, f"{tag}_components_ranked.json"), "w")); json.dump({"cv": res, "top100_total": tot, "ranking_used": "learned" if use_learned else "hand", "pos_frac": POS}, open(os.path.join(cd, f"{tag}_rank_cv.json"), "w"), indent=1); print("->", os.path.join(cd, f"{tag}_components_ranked.json"))
def apply(R, model_path, tag="fused"):
    cd = os.path.join(R["dir"], "candidates"); feats = json.load(open(os.path.join(cd, f"{tag}_features.json"))); M = json.load(open(model_path)); X, _ = matrix(feats, M["names"])
    z = ((X - np.array(M["mu"])) / np.array(M["sd"])) @ np.array(M["coef"]) + M["intercept"]; p = 1 / (1 + np.exp(-z))
    comps = json.load(open(os.path.join(cd, f"{tag}_components.json"))); pmap = {f["label"]: float(p[i]) for i, f in enumerate(feats)}
    for c in comps: c["p_learned"] = pmap.get(c["label"], 0)
    comps.sort(key=lambda c: -c["p_learned"]); [c.__setitem__("rank_learned", i + 1) for i, c in enumerate(comps)]
    json.dump(comps, open(os.path.join(cd, f"{tag}_components_ranked.json"), "w")); print("applied", model_path, "->", os.path.join(cd, f"{tag}_components_ranked.json"))
if __name__ == "__main__":
    R = load_region(sys.argv[1]); a = sys.argv[2:]
    if "--apply" in a: apply(R, a[a.index("--apply") + 1], a[0] if a and a[0] != "--apply" else "fused")
    else: run(R, a[0] if a else "fused")
