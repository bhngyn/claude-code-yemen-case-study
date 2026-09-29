"""Offline review page for the ranked candidates: per candidate a strip of chips (S2 before / S2 after / S1 change dB / fused z with the line in red /
per-epoch S2 if present), attributes, a verdict box (stored in the browser, exportable as JSON) and a Google-Earth-ready coordinate.
Everything is embedded (data URIs) so the file works offline.   usage: python -m trenchkit.review region.json [tag=fused] [top=100]"""
import sys, os, io, json, base64, html, numpy as np, cv2
from PIL import Image, ImageDraw
from .grid import load_region, load_grid
from .fetch_s2 import mosaic_cached
def uri(a, q=82):
    b = io.BytesIO(); Image.fromarray(a).save(b, "JPEG", quality=q); return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
def norm(a, lo, hi): a = np.nan_to_num(np.asarray(a).astype("float32")); return np.clip((a - lo) / (hi - lo) * 255, 0, 255).astype("uint8")
def crop(arr, y0, x0, s, sh=(0, 0)):
    """s x s window of a 2-D array at (y0 - sh[0], x0 - sh[1]), zero-padded where it leaves the array"""
    H, W = arr.shape[:2]; out = np.zeros((s, s), "float32"); r0, c0 = y0 - sh[0], x0 - sh[1]; rr0, cc0 = max(r0, 0), max(c0, 0); rr1, cc1 = min(r0 + s, H), min(c0 + s, W)
    if rr1 > rr0 and cc1 > cc0: out[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] = np.nan_to_num(np.asarray(arr[rr0:rr1, cc0:cc1]).astype("float32"))
    return out
def build(R, G, tag="fused", top=100, P=260):
    cd = os.path.join(R["dir"], "candidates"); md = os.path.join(R["dir"], "maps"); rd = os.path.join(R["dir"], "review"); os.makedirs(rd, exist_ok=True)
    rf = os.path.join(cd, f"{tag}_components_ranked.json"); learned = os.path.exists(rf); comps = json.load(open(rf if learned else os.path.join(cd, f"{tag}_components.json")))
    key = "rank_learned" if learned else "rank"; comps = sorted(comps, key=lambda c: c[key])[:top]; lab = np.load(os.path.join(cd, f"{tag}_labels.npy"), mmap_mode="r"); F = np.load(os.path.join(md, "fused.npy"), mmap_mode="r")
    wd = os.path.join(R["dir"], "review", "wayback")
    s1 = [(f[:-10], f) for f in sorted(os.listdir(os.path.join(R["dir"], "data", "s1"))) if f.endswith("_after.npy")]
    s1a = {k: np.load(os.path.join(R["dir"], "data", "s1", f), mmap_mode="r") for k, f in s1}; s1b = {k: np.load(os.path.join(R["dir"], "data", "s1", f.replace("_after", "_before")), mmap_mode="r") for k, f in s1}
    reg = json.load(open(os.path.join(md, "registration.json"))) if os.path.exists(os.path.join(md, "registration.json")) else {}
    eps = list(R["epochs"]); S2 = {e: mosaic_cached(R, G, e, "red") for e in eps}; zk = sorted({k[2:] for c in comps for k in c if k.startswith("z_") and "frac3_" + k[2:] in c})
    css = "body{margin:0;background:#15181b;color:#e8e9e6;font:15px/1.45 -apple-system,Helvetica,Arial,sans-serif;padding:0 18px 60px}h1{font-size:22px;margin:20px 0 4px}h2{font-size:18px;margin:34px 0 6px;border-top:2px solid #3a4046;padding-top:12px}.sub{color:#a7ada8;font-size:13px;max-width:1000px}table{border-collapse:collapse;font-size:13px}td,th{padding:3px 9px 3px 0;border-bottom:1px solid #2b3136;text-align:left;vertical-align:top}th{color:#a7ada8;font-weight:600}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.toc{max-width:1200px;overflow-x:auto;margin:10px 0 18px}.toc a{color:#7fd0c8}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 12px}.chip{width:" + str(P) + "px}.chip img{width:100%;display:block;border:1px solid #3a4046}.chip div{font-size:12px;color:#a7ada8;margin-top:2px}textarea{width:100%;max-width:900px;min-height:40px;background:#1e2428;color:#e8e9e6;border:1px solid #3a4046;padding:6px}select,button{background:#1e2428;color:#e8e9e6;border:1px solid #3a4046;padding:4px 8px}.tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:12px;background:#3a7d2e;color:#fff;margin-left:6px}.top{position:fixed;right:14px;bottom:14px;background:#252b30;padding:6px 10px;border-radius:3px;color:#e8e9e6;text-decoration:none}.wbrow{display:flex;gap:8px;flex-wrap:wrap;max-width:1900px}.wb{flex:1 1 560px;max-width:940px}.wb img{width:100%;display:block;border:1px solid #3a4046}.wb .cap{font-size:12px;color:#a7ada8;margin:4px 0}"
    js = "function tr(c,on){document.querySelectorAll('#'+c+' .wb img').forEach(i=>{i.src=on?i.dataset.trace:i.dataset.raw})}function save(c){try{localStorage.setItem('tk_'+c,JSON.stringify({v:document.getElementById(c+'_v').value,n:document.getElementById(c+'_n').value}));mark(c)}catch(e){}}function mark(c){const v=document.getElementById(c+'_v').value;const t=document.getElementById('toc_'+c);if(t)t.textContent=v==='unreviewed'?'':v;}document.querySelectorAll('section').forEach(s=>{try{const d=JSON.parse(localStorage.getItem('tk_'+s.id)||'null');if(d){document.getElementById(s.id+'_v').value=d.v;document.getElementById(s.id+'_n').value=d.n;mark(s.id)}}catch(e){}});function exportAll(){const o={};document.querySelectorAll('section').forEach(s=>{o[s.id]={verdict:document.getElementById(s.id+'_v').value,notes:document.getElementById(s.id+'_n').value,latlon:s.dataset.ll}});const b=new Blob([JSON.stringify(o,null,1)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='" + R["name"] + "_verdicts.json';a.click();}"
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(R['name'])}: earthwork candidates</title><style>{css}</style></head><body><a class='top' href='#top'>top</a>",
           f"<h1 id='top'>{html.escape(R['name'])}: ranked linear-earthwork candidates (top {len(comps)})</h1><div class='sub'>{html.escape(R.get('description', ''))}<br>Chips: Sentinel-2 red composites per epoch ({', '.join(eps)}), Sentinel-1 change (dB, {R['s1']['epochs']['before'][0][:4]} to {R['s1']['epochs']['after'][0][:4]}) per orbit, fused line z with the component in red. Verdicts are stored in this browser; export them as JSON when done.</div>",
           "<p><button onclick='exportAll()'>Export verdicts as JSON</button></p><div class='toc'><table><tr><th class='n'>rank</th><th>lat, lon</th><th class='n'>km</th>" + "".join(f"<th class='n'>{html.escape(k)}</th>" for k in zk) + "<th class='n'>busy</th><th class='n'>label</th>" + ("<th class='n'>p learned</th><th class='n'>hand rank</th>" if learned else "") + "<th>verdict</th></tr>"]
    for c in comps:
        cid = f"r{c[key]}"; out.append(f"<tr><td class='n'><a href='#{cid}'>{c[key]}</a></td><td>{c['lat']:.4f}, {c['lon']:.4f}</td><td class='n'>{c['path_m']/1000:.1f}</td>" + "".join(f"<td class='n'>{c['z_' + k]:.1f}</td>" for k in zk) + f"<td class='n'>{c['busy']:.2f}</td><td class='n'>{c.get('label_frac', 0):.2f}</td>" + (f"<td class='n'>{c.get('p_learned', 0):.2f}</td><td class='n'>{c['rank']}</td>" if learned else "") + f"<td id='toc_{cid}'></td></tr>")
    out.append("</table></div>")
    for c in comps:
        cid = f"r{c[key]}"; x, y, w, h = c["bbox"]; Hg, Wg = F.shape; s = int(min(max(w, h) + 60, 800, Hg, Wg)); x0 = int(np.clip(x + w / 2 - s / 2, 0, Wg - s)); y0 = int(np.clip(y + h / 2 - s / 2, 0, Hg - s))
        chips = []
        for e in eps: chips.append((f"S2 red {e}", uri(cv2.resize(norm(crop(S2[e], y0, x0, s), 0.08, 0.42), (P, P), interpolation=cv2.INTER_AREA))))
        for k in s1a:
            sh = reg.get(k[1:], {}).get("shift", [0, 0]); d = crop(s1a[k], y0, x0, s, sh) - crop(s1b[k], y0, x0, s, sh)
            chips.append((f"S1 change {k} (-3..+3 dB)", uri(cv2.resize(norm(d, -3, 3), (P, P), interpolation=cv2.INTER_AREA))))
        f = cv2.cvtColor(cv2.resize(norm(crop(F, y0, x0, s), 0, 10), (P, P), interpolation=cv2.INTER_AREA), cv2.COLOR_GRAY2RGB); m = cv2.resize((crop(lab, y0, x0, s) == c["label"]).astype("uint8"), (P, P), interpolation=cv2.INTER_NEAREST); f[m.astype(bool)] = (255, 60, 60)
        chips.append(("fused z (0..10), component red", uri(f)))
        tag_ = f"<span class='tag'>labelled trench {c['label_frac']:.0%}</span>" if c.get("label_frac", 0) > 0.3 else ""
        out.append(f"<section id='{cid}' data-ll='{c['lat']:.5f}, {c['lon']:.5f}'><h2>Rank {c[key]}: {c['lat']:.4f}N {c['lon']:.4f}E, {c['path_m']/1000:.1f} km, " + (f"p {c['p_learned']:.2f} (hand rank {c['rank']}, score {c['score']:.1f})" if learned else f"score {c['score']:.1f}") + f" {tag_}</h2>")
        out.append("<table><tr><td>chip box</td><td>" + f"{s * G['res'] / 1000:.1f} km</td></tr>" + "".join(f"<tr><td>{html.escape(k)}</td><td>z {c['z_' + k]:.1f}, share &gt; 3: {c['frac3_' + k]:.2f}</td></tr>" for k in zk) + f"<tr><td>busy / veg / tortuosity / branchiness</td><td>{c['busy']:.2f} / {c['veg']:.2f} / {c['tortuosity']:.2f} / {c['branchiness']:.2f}</td></tr><tr><td>copy for Google Earth</td><td>{c['lat']:.5f}, {c['lon']:.5f}</td></tr></table>")
        out.append("<div class='chips'>" + "".join(f"<div class='chip'><img src='{u}'><div>{html.escape(t)}</div></div>" for t, u in chips) + "</div>")
        wj = os.path.join(wd, f"{cid}.json")
        if os.path.exists(wj):
            W_ = json.load(open(wj)); fr = []
            for role in ("before", "after"):
                if role not in W_["frames"]: continue
                fi = W_["frames"][role]; imgs = {}
                for kind in ("", "_trace"):
                    im = Image.open(os.path.join(wd, f"{cid}_{role}{kind}.jpg")); im.thumbnail((1200, 1200)); b = io.BytesIO(); im.save(b, "JPEG", quality=76); imgs[kind] = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
                fr.append(f"<div class='wb'><div class='cap'>{role}: captured {fi['captured']} ({html.escape(str(fi['sensor']))} {fi['res_m']} m), Wayback release {fi['release']}, z{W_['zoom']}</div><img src='{imgs['_trace']}' data-raw='{imgs['']}' data-trace='{imgs['_trace']}'></div>")
            out.append("<div class='wbrow'>" + "".join(fr) + f"</div><label><input type='checkbox' checked onchange='tr(\"{cid}\",this.checked)'> show detected line on Wayback frames</label>")
        out.append(f"<p>Verdict: <select id='{cid}_v' onchange='save(\"{cid}\")'><option>unreviewed</option><option>trench / earthwork</option><option>berm / wall / compound</option><option>road or track</option><option>field boundary / bund / canal</option><option>natural</option><option>unclear</option></select></p><textarea id='{cid}_n' placeholder='notes' oninput='save(\"{cid}\")'></textarea></section>")
    out.append(f"<script>{js}</script></body></html>"); path = os.path.join(rd, f"{tag}_review.html"); open(path, "w").write("".join(out)); print(path, os.path.getsize(path) // 1024, "KB,", len(comps), "candidates"); return path
if __name__ == "__main__":
    R = load_region(sys.argv[1]); G = load_grid(R); build(R, G, sys.argv[2] if len(sys.argv) > 2 else "fused", int(sys.argv[3]) if len(sys.argv) > 3 else 100)
