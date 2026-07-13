import json

nodes = json.loads(open("graph_nodes.json", encoding="utf-8").read())["nodes"]
edges = json.loads(open("graph_edges.json", encoding="utf-8").read())["edges"]
node_type = {n["id"]: n["type"] for n in nodes}


def report(target, max_show=12):
    if target not in node_type:
        print(f"=== {target} === NOT FOUND AS A NODE")
        print()
        return
    before = [e for e in edges if e["source"] == target and e["type"] in ("link", "transclusion") and node_type.get(e["target"]) != "Proof"]
    after = [e for e in edges if e["target"] == target and e["type"] in ("link", "transclusion") and node_type.get(e["source"]) != "Proof"]
    proofs = [e for e in edges if e["type"] == "proof_of" and e["target"] == target]
    print(f"=== {target}  [{node_type[target]}] ===")
    print(f"  before (depends on): {len(before)} -- sample: {[e['target'] for e in before[:max_show]]}")
    print(f"  proof variants: {len(proofs)} -- {[e['source'] for e in proofs[:max_show]]}")
    print(f"  after (cited by): {len(after)} -- sample: {[e['source'] for e in after[:max_show]]}")
    print()


targets = [
    "Fermat's Last Theorem",
    "Fundamental Theorem of Calculus",
    "Axiom:Axiom of Choice",
    "Definition:Group",
    "Cantor's Theorem",
    "Bolzano-Weierstrass Theorem",
    "Definition:Metric Space",
]
for t in targets:
    report(t)
