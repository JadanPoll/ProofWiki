import json
import math
from preview_layout import force_layout

data = json.loads(open("cluster_hierarchy.json", encoding="utf-8").read())
tree = data["tree"]
root = data["root"]
top_ids = tree[root]["children"]
top_set = set(top_ids)

seen_pairs = {}
for e in data["interClusterEdges"]:
    a, b, w = e["a"], e["b"], e["w"]
    if a in top_set and b in top_set and a != b:
        key = (a, b) if a < b else (b, a)
        seen_pairs[key] = seen_pairs.get(key, 0) + w
edges = [(a, b, w) for (a, b), w in seen_pairs.items()]

sizes = {cid: tree[cid]["size"] for cid in top_ids}
max_size = max(sizes.values())


def radius_of(cid):
    return 5 + 50 * math.sqrt(sizes[cid] / max_size)


# run for just 5, 20, 100 iterations and print spread each time
for n_iter in [1, 5, 20, 100, 300]:
    pos = force_layout(top_ids, edges, radius_of, iterations=n_iter, seed=42)
    xs = [p[0] for p in pos.values()]
    ys = [p[1] for p in pos.values()]
    spread_x = max(xs) - min(xs)
    spread_y = max(ys) - min(ys)
    # avg distance from origin
    avg_r = sum(math.hypot(x, y) for x, y in pos.values()) / len(pos)
    print(f"iters={n_iter:4d}  spread=({spread_x:.1f},{spread_y:.1f})  avg_dist_from_origin={avg_r:.2f}")
