"""
Assemble the final compact payload for the fractal-zoom visualization
artifact. Everything has to be inlined into a single self-contained HTML
file (no server, no external fetch), so this aggressively compacts:

  - titles stored once in a lookup array; everything else references nodes
    by integer index instead of repeating the string title
  - only intra-leaf-cluster edges are kept at node granularity (that's all
    the local "zoomed into one bubble" simulation ever needs); cross-cluster
    structure is already captured by the aggregated interClusterEdges from
    cluster_hierarchy.json, which is small (cluster-count-squared at worst,
    but Louvain keeps cross-cluster edges sparse by construction)
  - cluster tree re-keyed to small integers too

Output: viz_data.json, meant to be embedded verbatim as a <script> JSON
blob in the artifact HTML.
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
NODES_PATH = HERE / "graph_nodes.json"
EDGES_PATH = HERE / "graph_edges.json"
CLUSTERS_PATH = HERE / "cluster_hierarchy.json"
OUT_PATH = HERE / "viz_data.json"

TYPE_CODES = {"Theorem": 0, "Definition": 1, "Axiom": 2, "Symbol": 3, "Proof": 4}
EDGE_TYPE_CODES = {
    "link": 0, "transclusion": 1, "proof_of": 2, "subpage_of": 3, "template_ref": 4,
    "see_also": 5, "generalization": 6,
}
# Which edge types represent a genuine dependency vs. a loose cross-reference
# (see build_graph.py's classify_sections for why this distinction exists --
# a naive transitive closure over ALL edges explodes to thousands of nodes
# within a few hops once it touches a hub concept via an "Also see" link).
# "generalization" (Generalizations/Special cases) is a real relationship
# but not a prerequisite one -- a theorem's generalization isn't something
# you need to already know to follow ITS proof -- so it's excluded from the
# closure the same way see_also is, but kept as its own distinct edge type
# rather than folded into generic see_also.
STRICT_EDGE_TYPES = {"link", "transclusion", "proof_of", "subpage_of", "template_ref"}


def main():
    nodes = json.loads(NODES_PATH.read_text(encoding="utf-8"))["nodes"]
    clusters = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))

    leaf_membership = clusters["leafMembership"]  # title -> "cN"
    tree = clusters["tree"]

    # only nodes that made it into the concept graph (i.e. have a leaf cluster)
    kept_nodes = [n for n in nodes if n["id"] in leaf_membership]
    title_to_idx = {n["id"]: i for i, n in enumerate(kept_nodes)}

    # re-key cluster ids "cN" -> small ints, in a stable (BFS-ish) order
    cluster_ids = list(tree.keys())
    cluster_to_idx = {cid: i for i, cid in enumerate(cluster_ids)}

    titles = [n["id"] for n in kept_nodes]
    node_type_codes = [TYPE_CODES[n["type"]] for n in kept_nodes]
    node_sizes = [n["size"] for n in kept_nodes]
    node_leaf_cluster = [cluster_to_idx[leaf_membership[n["id"]]] for n in kept_nodes]
    # Sparse (nodeIdx, aliasNodeIdx) pairs rather than a dense per-node array
    # -- most nodes have zero aliases, so a dense array would mostly be
    # empty lists. Alias targets that resolve outside the concept graph
    # (e.g. a Mathematician/Book page, which shouldn't happen but isn't
    # guaranteed not to) are silently dropped rather than erroring.
    alias_pairs = []
    alias_name_pairs = []  # (nodeIdx, "plain name") -- bold but unlinked, no node to point to
    for i, n in enumerate(kept_nodes):
        for alias_title in n.get("aliases", []):
            j = title_to_idx.get(alias_title)
            if j is not None:
                alias_pairs.append([i, j])
        for name in n.get("alias_names", []):
            alias_name_pairs.append([i, name])
    # Only meaningful for Theorem nodes (a proof-or-not distinction doesn't
    # apply to Axioms, which are accepted without proof by definition) --
    # 1 for everything else so non-Theorem types never get visually flagged.
    node_has_proof = [1 if n["type"] != "Theorem" else (1 if n.get("has_proof") else 0) for n in kept_nodes]

    out_tree = []
    for cid in cluster_ids:
        e = tree[cid]
        # type composition as a compact 5-int array [Theorem,Definition,Axiom,Symbol,Proof]
        # counts, so the browser can color a cluster bubble by its dominant
        # concept type without re-aggregating over all descendant leaf nodes.
        tc = [0, 0, 0, 0, 0]
        for type_name, count in e["typeCounts"].items():
            tc[TYPE_CODES[type_name]] = count
        out_tree.append({
            "i": cluster_to_idx[cid],
            "p": cluster_to_idx[e["parent"]] if e["parent"] is not None else -1,
            "label": e["label"],
            "size": e["size"],
            "leaf": e["leaf"],
            "children": [cluster_to_idx[c] for c in e["children"]],
            "tc": tc,
        })

    inter_cluster_edges = [
        {"a": cluster_to_idx[e["a"]], "b": cluster_to_idx[e["b"]], "w": e["w"]}
        for e in clusters["interClusterEdges"]
    ]

    # intra-leaf-cluster edges (typed) for the local force simulation, PLUS a
    # full deduplicated citation index (untyped, cluster-agnostic) so the
    # explorer can answer "show me every context this concept appears in" --
    # a node's citations mostly land in OTHER clusters (Definition:Group has
    # 1223 citing pages scattered across many fields of math), so intra-only
    # edges can't support that at all; this is the actual point of the tool.
    intra_edges = []
    seen_intra = set()
    full_pairs = {}  # (si, ti) -> is_strict (True if ANY edge between them is a strict type)
    with EDGES_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)["edges"]
    for e in raw:
        et = e["type"]
        if et not in EDGE_TYPE_CODES:
            continue
        s, t = e["source"], e["target"]
        si, ti = title_to_idx.get(s), title_to_idx.get(t)
        if si is None or ti is None:
            continue
        pair = (si, ti)
        is_strict = et in STRICT_EDGE_TYPES
        full_pairs[pair] = full_pairs.get(pair, False) or is_strict
        if node_leaf_cluster[si] != node_leaf_cluster[ti]:
            continue
        key = (si, ti, EDGE_TYPE_CODES[et])
        if key in seen_intra:
            continue
        seen_intra.add(key)
        intra_edges.append([si, ti, EDGE_TYPE_CODES[et]])

    # third element: 1 if this pair has at least one strict (genuine
    # dependency) edge, 0 if every edge between them is see_also-only
    full_edges = [[si, ti, 1 if strict else 0] for (si, ti), strict in full_pairs.items()]
    strict_count = sum(1 for _, _, s in full_edges if s)

    payload = {
        "titles": titles,
        "nodeType": node_type_codes,
        "nodeSize": node_sizes,
        "nodeCluster": node_leaf_cluster,
        "nodeHasProof": node_has_proof,
        "tree": out_tree,
        "root": cluster_to_idx[clusters["root"]],
        "interClusterEdges": inter_cluster_edges,
        "intraEdges": intra_edges,
        "fullEdges": full_edges,
        "aliasPairs": alias_pairs,
        "aliasNamePairs": alias_name_pairs,
        "typeNames": ["Theorem", "Definition", "Axiom", "Symbol", "Proof"],
        "edgeTypeNames": ["link", "transclusion", "proof_of", "subpage_of", "template_ref", "see_also", "generalization"],
    }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Nodes: {len(titles)}")
    print(f"Clusters: {len(out_tree)}")
    print(f"Inter-cluster edges: {len(inter_cluster_edges)}")
    print(f"Intra-leaf-cluster edges: {len(intra_edges)}")
    print(f"Full citation pairs: {len(full_edges)} ({strict_count} strict, {len(full_edges) - strict_count} see_also-only)")
    print(f"Alias pairs (resolvable): {len(alias_pairs)}")
    print(f"Alias name pairs (string-only): {len(alias_name_pairs)}")
    print(f"Written: {OUT_PATH} ({OUT_PATH.stat().st_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
