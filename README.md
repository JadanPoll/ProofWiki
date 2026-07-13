# ProofWiki Concept Explorer

An interactive, force-directed, multi-resolution ("fractal zoom") explorer
over the entire [ProofWiki](https://proofwiki.org) citation graph — 62,220
theorems/definitions/axioms/symbols/proofs, 400k+ citation edges. Not a
search tool, not a curriculum — a tool for browsing a concept's full web of
relationships at once: what it depends on, everywhere it's cited, its full
prerequisite closure, and its synonyms, all side by side, so recognitional
pattern-matching builds across many contexts simultaneously instead of
reading proofs one at a time.

## Before touching this project — read this first

**[`PROJECT_NOTES.md`](PROJECT_NOTES.md)** is the actual continuity record:
the data model, every non-obvious extraction/rendering decision and why,
findings that cost real iteration to discover (don't re-derive them), known
limitations, and design choices worth preserving. Read it before making
changes — several of its findings look small in isolation but silently
affected a large fraction of the corpus (see e.g. the wikilink-in-heading
classification bug, or the sibling-cluster label collisions).

## Quick start — just use the tool

The deliverable is a single self-contained HTML file:
**[`explorer.html`](explorer.html)** (~14MB, all data inlined, no server, no
external requests). Clone the repo and open it directly in a browser.

## Rebuilding the pipeline

Only needed if you want to regenerate the graph from a fresh ProofWiki dump,
or change extraction/clustering/rendering logic. The large intermediate data
files (`graph_nodes.json`, `graph_edges.json`, `cluster_hierarchy.json`,
`viz_data.json`, the raw XML dump, etc.) are gitignored — they're all fully
regenerable and mostly too large for a git repo (the raw dump alone is
200MB+, past GitHub's 100MB per-file limit).

```bash
pip install -r requirements.txt

# 1. Get the official nightly dump
curl -o proofwiki-dump.xml.gz https://proofwiki.org/xmldump/latest.xml.gz
gunzip -k proofwiki-dump.xml.gz

# 2. Extract + classify every page, build the citation graph
python build_graph.py            # -> graph_nodes.json, graph_edges.json

# 3. Recursive Louvain clustering -- SLOW (minutes), only needed if the
#    edge structure changed (new/removed citation pairs), not for label or
#    attribute-only changes
python cluster_hierarchy.py      # -> cluster_hierarchy.json

# 4. Compact everything into the browser-ready integer-indexed format
python build_viz_data.py         # -> viz_data.json

# 5. Splice viz_data.json into the editable template
python assemble_explorer.py      # -> explorer.html
```

`explorer_template.html` is the actual editable JS/HTML source;
`explorer.html` is a build artifact produced from it and should never be
hand-edited directly.

## File layout

```
explorer_template.html    editable JS/HTML source (canvas rendering, physics, UI)
assemble_explorer.py      splices viz_data.json into the template -> explorer.html
explorer.html             the deliverable -- open this in a browser

build_graph.py            streams the XML dump -> graph_nodes.json, graph_edges.json
cluster_hierarchy.py      recursive Louvain community detection -> cluster_hierarchy.json
build_viz_data.py         compacts everything for the browser -> viz_data.json
extract_pages.py          per-page text extraction (reference/debugging only, not
                           used by the graph builder)
export_graphml.py         optional export to GraphML for external graph tools

count_namespaces.py, count_proof_sections.py, check_defof_gap.py,
validate_sample.py, debug_layout.py, preview_layout.py    one-off analysis/
                           debugging scripts used while building the pipeline
```

## Data model

Node types: Theorem, Definition, Axiom, Symbol, Proof. Edge types: `link`,
`transclusion`, `proof_of`, `subpage_of`, `template_ref` (from ProofWiki's own
citation templates), `see_also`, `generalization`. See `PROJECT_NOTES.md`'s
"Key data model" section for the full detail, including which edge types feed
the strict prerequisite closure vs. which are loose cross-references.
