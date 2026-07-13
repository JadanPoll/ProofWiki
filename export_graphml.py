"""
Load graph_nodes.json/graph_edges.json into a networkx DiGraph, compute
in-degree (a cheap proxy for "how load-bearing is this concept" -- the more
proofs/definitions that cite it, the more foundational it is) and out-degree
(how many other concepts this one leans on), and write a .graphml file for
offline exploration in Gephi / networkx / any graph tool that isn't a browser.

Betweenness/eigenvector centrality etc. are NOT computed here -- at ~91k
nodes / ~727k edges those are minutes-to-hours in pure Python networkx.
In-degree is enough to answer "what's load-bearing" and is O(E).
"""
import json
from pathlib import Path

import networkx as nx

HERE = Path(__file__).parent
NODES_PATH = HERE / "graph_nodes.json"
EDGES_PATH = HERE / "graph_edges.json"
GRAPHML_OUT = HERE / "proofwiki_graph.graphml"


def main():
    nodes = json.loads(NODES_PATH.read_text(encoding="utf-8"))["nodes"]
    edges = json.loads(EDGES_PATH.read_text(encoding="utf-8"))["edges"]

    G = nx.DiGraph()
    for n in nodes:
        G.add_node(n["id"], type=n["type"], size=n["size"])
    for e in edges:
        if e["source"] in G and e["target"] in G:
            G.add_edge(e["source"], e["target"], type=e["type"])

    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())
    nx.set_node_attributes(G, in_deg, "in_degree")
    nx.set_node_attributes(G, out_deg, "out_degree")

    nx.write_graphml(G, str(GRAPHML_OUT))

    top_load_bearing = sorted(in_deg.items(), key=lambda kv: -kv[1])[:15]
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    print(f"Written: {GRAPHML_OUT}")
    print("\nTop 15 most load-bearing concepts (highest in-degree):")
    for title, d in top_load_bearing:
        t = G.nodes[title]["type"]
        print(f"  {d:5d}  [{t}]  {title}")


if __name__ == "__main__":
    main()
