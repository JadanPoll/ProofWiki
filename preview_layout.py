"""
Static preview: force-layout just the 203 top-level clusters (children of
root) and render as one SVG. No interactivity, no zoom -- just "does the
shape of this graph look right" before building the full interactive
explorer on top of it.
"""
import json
import math
import random
from pathlib import Path

HERE = Path(__file__).parent
CLUSTERS_PATH = HERE / "cluster_hierarchy.json"
OUT_SVG = HERE / "preview_top_level.svg"

TYPE_COLORS = {
    "Theorem": "#3987e5",
    "Definition": "#199e70",
    "Axiom": "#c98500",
    "Symbol": "#008300",
    "Proof": "#9085e9",
}


def force_layout(node_ids, edges, radius_of, iterations=500, seed=42):
    """Explicit force-directed layout (repulsion + log-weighted spring
    attraction + centering + damping), written out plainly rather than
    relying on nx.spring_layout's weight semantics -- which, tried first,
    let a handful of very-high-weight edges collapse the whole graph to a
    single overlapping point at the center (see git history / preview v1).
    This is also the reference implementation to port to JS for the live
    interactive simulation, so it's deliberately simple and inspectable.
    """
    rnd = random.Random(seed)
    pos = {nid: [math.cos(a := rnd.uniform(0, 2 * math.pi)) * 300, math.sin(a) * 300] for nid in node_ids}
    vel = {nid: [0.0, 0.0] for nid in node_ids}

    edge_list = [(a, b, math.log1p(w)) for a, b, w in edges]
    max_w = max((w for _, _, w in edge_list), default=1.0)

    REPULSION_K = 12000.0
    SPRING_K = 0.02
    CENTER_K = 0.002
    DAMPING = 0.82
    MAX_FORCE = 400.0
    MAX_SPEED = 60.0

    for _ in range(iterations):
        force = {nid: [0.0, 0.0] for nid in node_ids}

        for i, a in enumerate(node_ids):
            ax, ay = pos[a]
            for b in node_ids[i + 1:]:
                bx, by = pos[b]
                dx, dy = ax - bx, ay - by
                dist = math.hypot(dx, dy)
                if dist < 1e-3:
                    angle = rnd.uniform(0, 2 * math.pi)
                    dx, dy = math.cos(angle), math.sin(angle)
                    dist = 1.0
                # Floor the distance used in 1/dist^2 -- with 200+ nodes
                # placed at random initial angles, near-coincident pairs are
                # inevitable (birthday paradox), and unclamped 1/dist^2
                # spikes to a huge force at small separation, which blew the
                # whole simulation up to billions of units within 1 tick.
                min_sep = radius_of(a) + radius_of(b) + 4
                eff_dist = max(dist, min_sep * 0.5)
                f = REPULSION_K * (radius_of(a) * radius_of(b)) ** 0.5 / (eff_dist * eff_dist)
                if dist < min_sep:
                    f += (min_sep - dist) * 8  # hard-ish separation so bubbles don't overlap
                f = min(f, MAX_FORCE)
                fx, fy = f * dx / dist, f * dy / dist
                force[a][0] += fx
                force[a][1] += fy
                force[b][0] -= fx
                force[b][1] -= fy

        for a, b, w in edge_list:
            ax, ay = pos[a]
            bx, by = pos[b]
            dx, dy = bx - ax, by - ay
            dist = math.sqrt(dx * dx + dy * dy) or 1e-3
            rest = (radius_of(a) + radius_of(b)) * 2.2
            strength = SPRING_K * (w / max_w)
            f = strength * (dist - rest)
            fx, fy = f * dx / dist, f * dy / dist
            force[a][0] += fx
            force[a][1] += fy
            force[b][0] -= fx
            force[b][1] -= fy

        for nid in node_ids:
            x, y = pos[nid]
            force[nid][0] -= x * CENTER_K
            force[nid][1] -= y * CENTER_K

        for nid in node_ids:
            vx = (vel[nid][0] + force[nid][0]) * DAMPING
            vy = (vel[nid][1] + force[nid][1]) * DAMPING
            speed = math.hypot(vx, vy)
            if speed > MAX_SPEED:
                vx, vy = vx / speed * MAX_SPEED, vy / speed * MAX_SPEED
            vel[nid][0], vel[nid][1] = vx, vy
            pos[nid][0] += vx
            pos[nid][1] += vy

    return pos


def main():
    data = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
    tree = data["tree"]
    root = data["root"]
    top_ids = tree[root]["children"]
    top_set = set(top_ids)

    edges = []
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

    pos_raw = force_layout(top_ids, edges, radius_of, iterations=500, seed=42)
    pos = {cid: tuple(v) for cid, v in pos_raw.items()}
    radius = radius_of

    def dominant_type(cid):
        tc = tree[cid]["typeCounts"]
        return max(tc.items(), key=lambda kv: kv[1])[0]

    W, H = 1400, 1000
    xs = [pos[c][0] for c in top_ids]
    ys = [pos[c][1] for c in top_ids]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    pad = 70

    def sx(x):
        return pad + (x - xmin) / (xmax - xmin) * (W - 2 * pad)

    def sy(y):
        return pad + (y - ymin) / (ymax - ymin) * (H - 2 * pad)

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui,-apple-system,sans-serif">',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="#0a0d12"/>',
    ]

    # edges first (under bubbles)
    for a, b, w in edges:
        x1, y1 = sx(pos[a][0]), sy(pos[a][1])
        x2, y2 = sx(pos[b][0]), sy(pos[b][1])
        opacity = min(0.5, 0.05 + math.log1p(w) * 0.04)
        svg_parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#5a6478" stroke-width="1" opacity="{opacity:.3f}"/>')

    labeled = sorted(top_ids, key=lambda c: -tree[c]["size"])[:35]
    labeled_set = set(labeled)

    for cid in top_ids:
        cx, cy = sx(pos[cid][0]), sy(pos[cid][1])
        r = radius(cid)
        color = TYPE_COLORS[dominant_type(cid)]
        label = tree[cid]["label"]
        size = tree[cid]["size"]
        svg_parts.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{color}" fill-opacity="0.55" '
            f'stroke="{color}" stroke-width="1.2"><title>{label} ({size} concepts)</title></circle>'
        )
        if cid in labeled_set and r > 12:
            fs = min(15, max(8, r * 0.32))
            svg_parts.append(
                f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="{fs:.1f}" fill="#eef0f4" '
                f'text-anchor="middle" dominant-baseline="middle" opacity="0.9">{label}</text>'
            )

    svg_parts.append("</svg>")
    OUT_SVG.write_text("\n".join(svg_parts), encoding="utf-8")
    print(f"Top-level bubbles: {len(top_ids)}")
    print(f"Inter-bubble edges: {len(edges)}")
    print(f"Written: {OUT_SVG}")


if __name__ == "__main__":
    main()
