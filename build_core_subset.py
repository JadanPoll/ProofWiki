"""
Curate a "load-bearing core" subgraph small enough to force-simulate live in
a browser (target: ~1500-2500 nodes). The full graph (91k nodes / 727k
edges) can't be rendered interactively client-side -- this picks the
concepts that actually matter for "what do I need to know to follow any
given proof": the most-cited Axioms/Definitions/Theorems/Symbols, plus every
Proof variant belonging to a Theorem that makes the cut (so parallel proof
strategies stay visible for the theorems that matter).

Category/Book/Mathematician namespaces are NOT included as graph nodes --
Category becomes a per-node "cluster" attribute instead (its most-specific
in_category tag), which is what actually gives the "topological separation
by field of mathematics" look without diluting the concept graph with 23k
bookkeeping nodes. Mathematician/Book are attribution/citation metadata, not
prerequisite structure, so they're dropped entirely from this view (they're
still in the full graph_nodes.json / proofwiki_graph.graphml for anyone who
wants them).
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
NODES_PATH = HERE / "graph_nodes.json"
EDGES_PATH = HERE / "graph_edges.json"
OUT_PATH = HERE / "core_graph.json"

CONCEPT_TYPES = {"Theorem", "Definition", "Axiom", "Symbol"}
CORE_SIZE = 900  # top-N concept nodes by in-degree


def main():
    nodes = json.loads(NODES_PATH.read_text(encoding="utf-8"))["nodes"]
    edges = json.loads(EDGES_PATH.read_text(encoding="utf-8"))["edges"]

    node_type = {n["id"]: n["type"] for n in nodes}
    node_size = {n["id"]: n["size"] for n in nodes}

    in_degree = {}
    for e in edges:
        if e["type"] in ("link", "transclusion", "proof_of", "subpage_of"):
            in_degree[e["target"]] = in_degree.get(e["target"], 0) + 1

    # first-seen in_category target per source = its most-specific/primary category
    primary_category = {}
    for e in edges:
        if e["type"] == "in_category" and e["source"] not in primary_category:
            primary_category[e["source"]] = e["target"]

    concept_nodes = [
        (nid, in_degree.get(nid, 0))
        for nid, t in node_type.items()
        if t in CONCEPT_TYPES
    ]
    concept_nodes.sort(key=lambda kv: -kv[1])
    core_ids = {nid for nid, _ in concept_nodes[:CORE_SIZE]}

    # pull in every Proof variant of a Theorem that made the cut
    proof_of_target = {
        e["source"]: e["target"] for e in edges if e["type"] == "proof_of"
    }
    for src, tgt in proof_of_target.items():
        if tgt in core_ids:
            core_ids.add(src)

    kept_edges = [
        e for e in edges
        if e["source"] in core_ids and e["target"] in core_ids
        and e["type"] in ("link", "transclusion", "proof_of", "subpage_of")
    ]

    id_list = sorted(core_ids)
    id_index = {nid: i for i, nid in enumerate(id_list)}

    out_nodes = []
    for nid in id_list:
        out_nodes.append({
            "id": nid,
            "type": node_type[nid],
            "size": node_size.get(nid, 0),
            "inDeg": in_degree.get(nid, 0),
            "category": primary_category.get(nid, ""),
        })
    out_edges = [
        {"s": id_index[e["source"]], "t": id_index[e["target"]], "type": e["type"]}
        for e in kept_edges
    ]

    OUT_PATH.write_text(
        json.dumps({"nodes": out_nodes, "edges": out_edges}, ensure_ascii=False),
        encoding="utf-8",
    )

    from collections import Counter
    print(f"Core nodes: {len(out_nodes)}")
    for t, c in Counter(n["type"] for n in out_nodes).most_common():
        print(f"  {t}: {c}")
    print(f"Core edges: {len(out_edges)}")
    print(f"Written: {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
