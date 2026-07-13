"""
Build a multi-resolution cluster hierarchy over the concept graph using
recursive Louvain community detection, so the visualization can render the
whole ~90k-node graph as a small number of "bubbles" at the top level (cheap
long-range force simulation between bubbles), and only force-simulate real
nodes locally once the user zooms into a bubble small enough to render live
(cheap short-range simulation over a few hundred nodes at most).

Why Louvain on the citation graph instead of ProofWiki's own Category tags:
the category tag graph turned out to be a tangled DAG (5,997 categories with
multiple parents, 8,262 apparent "roots" that are mostly orphaned leaf tags,
one mega-branch holding 63% of all categories) -- not usable as a clean
hierarchy. Louvain finds communities from actual link density instead, which
is more reliable; we still use category tags afterward, just to *label* each
computed cluster with its most common field-of-mathematics tag, purely for
human-readable bubble names.

Recursion: any community above LEAF_MAX_SIZE gets Louvain re-run on its
induced subgraph to split it further, until every leaf community is small
enough to force-simulate live in a browser, or a max depth is hit.
"""
import json
from collections import Counter
from pathlib import Path

import networkx as nx

HERE = Path(__file__).parent
NODES_PATH = HERE / "graph_nodes.json"
EDGES_PATH = HERE / "graph_edges.json"
CLUSTERS_OUT = HERE / "cluster_hierarchy.json"

CONCEPT_TYPES = {"Theorem", "Definition", "Axiom", "Symbol", "Proof"}
STRUCTURAL_EDGE_TYPES = {"link", "transclusion", "proof_of", "subpage_of", "template_ref", "see_also", "generalization"}
LEAF_MAX_SIZE = 220
MAX_DEPTH = 4


def main():
    nodes = json.loads(NODES_PATH.read_text(encoding="utf-8"))["nodes"]
    edges = json.loads(EDGES_PATH.read_text(encoding="utf-8"))["edges"]

    node_type = {n["id"]: n["type"] for n in nodes if n["type"] in CONCEPT_TYPES}

    # First-category-wins picked an eponymous self-referential category (e.g.
    # page "Union is Associative" tagged with its own "Category:Union is
    # Associative") as the "primary" category for 16.8% of tagged nodes --
    # useless as a cluster label since it just restates the page's own name.
    # Collect every category per node and prefer the first NON-eponymous one.
    categories_by_node = {}
    for e in edges:
        if e["type"] == "in_category" and e["source"] in node_type:
            categories_by_node.setdefault(e["source"], []).append(e["target"])

    def is_eponymous(node_id, category_title):
        base = node_id.split(":", 1)[-1].split("/")[0]
        return category_title.removeprefix("Category:") == base

    # Structural/meta categories that say nothing about subject matter --
    # confirmed by frequency audit to be near-universal tags (almost any
    # theorem can have a Historical Note or a Linguistic Note) that would
    # otherwise win "most common category" for large, subject-diverse
    # clusters purely by volume, not relevance.
    GENERIC_CATEGORIES = {"Historical Notes", "Linguistic Notes"}

    def is_generic(category_title):
        return category_title.removeprefix("Category:") in GENERIC_CATEGORIES

    primary_category = {}
    for node_id, cats in categories_by_node.items():
        usable = [c for c in cats if not is_eponymous(node_id, c) and not is_generic(c)]
        chosen = usable[0] if usable else (cats[0] if cats else None)
        if chosen:
            primary_category[node_id] = chosen.removeprefix("Category:")

    G = nx.Graph()
    G.add_nodes_from(node_type.keys())
    weight_counter = Counter()
    for e in edges:
        if e["type"] in STRUCTURAL_EDGE_TYPES and e["source"] in node_type and e["target"] in node_type:
            a, b = e["source"], e["target"]
            if a == b:
                continue
            key = (a, b) if a < b else (b, a)
            weight_counter[key] += 1
    for (a, b), w in weight_counter.items():
        G.add_edge(a, b, weight=w)

    print(f"Concept graph for clustering: {G.number_of_nodes()} nodes, {G.number_of_edges()} weighted edges")

    cluster_seq = [0]

    def new_id():
        cluster_seq[0] += 1
        return f"c{cluster_seq[0]}"

    def label_for(members):
        cats = Counter(primary_category.get(m) for m in members if primary_category.get(m))
        if cats:
            top_cat, top_n = cats.most_common(1)[0]
            return top_cat
        # fallback: no category info -- name it after its type composition
        types = Counter(node_type[m] for m in members)
        return f"{types.most_common(1)[0][0]} cluster"

    tree = {}  # cluster_id -> node dict
    leaf_membership = {}  # graph node id -> leaf cluster_id
    cluster_members = {}  # cluster_id -> node_ids, kept only for the disambiguation pass below (not serialized)

    def build(node_ids, depth, parent_id):
        cid = new_id()
        sub = G.subgraph(node_ids)
        entry = {
            "id": cid,
            "parent": parent_id,
            "label": label_for(node_ids),
            "size": len(node_ids),
            "typeCounts": dict(Counter(node_type[m] for m in node_ids)),
            "children": [],
            "leaf": False,
        }
        tree[cid] = entry
        cluster_members[cid] = node_ids

        if len(node_ids) <= LEAF_MAX_SIZE or depth >= MAX_DEPTH:
            entry["leaf"] = True
            for m in node_ids:
                leaf_membership[m] = cid
            return entry

        try:
            communities = nx.community.louvain_communities(sub, weight="weight", seed=0)
        except Exception as ex:
            print(f"  Louvain failed at depth {depth} on {len(node_ids)} nodes ({ex}); treating as leaf")
            entry["leaf"] = True
            for m in node_ids:
                leaf_membership[m] = cid
            return entry

        communities = [c for c in communities if c]
        if len(communities) <= 1:
            # didn't actually split further -- treat as leaf even if large
            entry["leaf"] = True
            for m in node_ids:
                leaf_membership[m] = cid
            return entry

        for comm in communities:
            child = build(set(comm), depth + 1, cid)
            entry["children"].append(child["id"])
        return entry

    root = build(set(node_type.keys()), 0, None)

    # label_for() only ever sees one cluster's own members, so it has no way
    # to notice that a sibling landed on the same label (e.g. two different
    # size-1 communities that both fall back to "Theorem cluster", or two
    # unrelated communities that both happen to be dominated by the
    # "Specific Numbers" category) -- confirmed via direct inspection of a
    # prior run: 100 sibling-groups / 367 clusters sharing a label
    # tree-wide, some pairs differing by orders of magnitude in size (one
    # "Specific Numbers" cluster had 7617 members, another had 1) while
    # rendering as indistinguishable same-named bubbles. Disambiguate here:
    # any cluster whose label collides with a sibling's gets its single most
    # central member (by weighted degree within its own induced subgraph)
    # appended. Siblings are disjoint node sets by construction (Louvain
    # partitions, no overlap), so the appended member can never collide
    # between two colliding siblings -- this always produces distinct text.
    def top_member(node_ids):
        if len(node_ids) == 1:
            return next(iter(node_ids))
        degrees = G.subgraph(node_ids).degree(weight="weight")
        return max(degrees, key=lambda kv: kv[1])[0]

    children_by_parent = {}
    for cid, e in tree.items():
        children_by_parent.setdefault(e["parent"], []).append(cid)

    renamed = 0
    for parent, kids in children_by_parent.items():
        by_label = {}
        for cid in kids:
            by_label.setdefault(tree[cid]["label"], []).append(cid)
        for label, group in by_label.items():
            if len(group) < 2:
                continue
            for cid in group:
                rep = top_member(cluster_members[cid])
                tree[cid]["label"] = f"{label} — {rep}"
                renamed += 1
    print(f"Disambiguated {renamed} sibling clusters that shared a label with another sibling")

    # aggregate cross-cluster edge weights at every level (siblings share a parent)
    def leaf_of(nid, target_depth_ids):
        pass  # not used; see below

    # For bubble-level forces we need, for each parent cluster, the weighted
    # edge count between each pair of its direct children. Do this by walking
    # every structural edge once and, for each level of the tree, mapping
    # both endpoints up to their ancestor at that level.
    ancestors_cache = {}

    def ancestor_chain(cid):
        if cid in ancestors_cache:
            return ancestors_cache[cid]
        chain = []
        cur = cid
        while cur is not None:
            chain.append(cur)
            cur = tree[cur]["parent"]
        chain.reverse()  # root ... leaf
        ancestors_cache[cid] = chain
        return chain

    inter_cluster_weight = Counter()  # (cluster_a, cluster_b) at matching depth -> weight
    for (a, b), w in weight_counter.items():
        la, lb = leaf_membership.get(a), leaf_membership.get(b)
        if la is None or lb is None or la == lb:
            continue
        chain_a, chain_b = ancestor_chain(la), ancestor_chain(lb)
        depth = min(len(chain_a), len(chain_b))
        for d in range(depth):
            ca, cb = chain_a[d], chain_b[d]
            if ca == cb:
                continue
            key = (ca, cb) if ca < cb else (cb, ca)
            inter_cluster_weight[key] += w

    CLUSTERS_OUT.write_text(
        json.dumps({
            "root": root["id"],
            "tree": tree,
            "leafMembership": leaf_membership,
            "interClusterEdges": [{"a": a, "b": b, "w": w} for (a, b), w in inter_cluster_weight.items()],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    depths = Counter()
    for cid, e in tree.items():
        depths[len(ancestor_chain(cid)) - 1] += 1
    leaf_sizes = [e["size"] for e in tree.values() if e["leaf"]]
    print(f"\nTotal clusters: {len(tree)}")
    print(f"Clusters per depth: {dict(sorted(depths.items()))}")
    print(f"Leaf clusters: {len(leaf_sizes)}  (sizes: min={min(leaf_sizes)}, max={max(leaf_sizes)}, "
          f"median={sorted(leaf_sizes)[len(leaf_sizes)//2]})")
    print(f"Written: {CLUSTERS_OUT} ({CLUSTERS_OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
