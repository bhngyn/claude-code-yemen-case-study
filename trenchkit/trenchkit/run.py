"""Driver: run the stages in order for a region (each stage skips work it has already done).
usage: python -m trenchkit.run region.json [--labels file.kmz] [--stages fetch_s2,fetch_s1,detect,fuse,features,rank,review,wayback] [--top 100] [--wayback-top 40] [--model ranker.json]"""
import sys, os, subprocess, argparse
ap = argparse.ArgumentParser(); ap.add_argument("region"); ap.add_argument("--labels"); ap.add_argument("--stages", default="fetch_s2,fetch_s1,detect,fuse,features,rank,review"); ap.add_argument("--top", default="100"); ap.add_argument("--wayback-top", default="40"); ap.add_argument("--model")
a = ap.parse_args(); py = sys.executable; env = dict(os.environ, PYTHONPATH=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def stage(mod, *args):
    print(f"\n===== {mod} {' '.join(args)} =====", flush=True); r = subprocess.run([py, "-m", f"trenchkit.{mod}", a.region, *args], env=env)
    if r.returncode: sys.exit(f"{mod} failed ({r.returncode})")
stage("grid")
if a.labels: stage("labels", a.labels)
for s in a.stages.split(","):
    if s == "rank": stage("rank", *(["fused", "--apply", a.model] if a.model else ["fused"]))
    elif s == "review": stage("review", "fused", a.top)
    elif s == "wayback": stage("wayback", "fused", a.wayback_top)
    elif s == "evaluate": stage("evaluate")
    else: stage(s)
print("\nall stages done")
