# ProofWiki Concept Explorer — Project Notes

**Read this file first in any new session.** This project was built in a chat session
rooted in a *different* directory (`Desktop/OSDev`) by mistake, so nothing about it
lives in that session's auto-memory — this file is the actual continuity record.

## What this is

An interactive, force-directed, multi-resolution ("fractal zoom") explorer over the
entire ProofWiki citation graph — 62,220 theorems/definitions/axioms/symbols/proofs,
727k+ edges. Built for a specific learning goal (the user's words): *"the revelation
was I couldn't go through that many proofs doing it linearly — I need to see why an
idea is relevant in all its contexts side by side, traverse by taxonomy, use the rich
context of appearance to force the intuition to fill in."* Not a search tool, not a
curriculum — a tool for browsing a concept's full web of relationships at once,
building recognitional pattern-matching across many contexts simultaneously rather
than reading proofs one at a time.

The deliverable is a single self-contained HTML file:
**`c:\Users\nathan37\Desktop\ProofWiki\explorer.html`** (~14MB, all data inlined, no
server, no external requests — just open it in a browser).

## Pipeline architecture (run in this order to rebuild)

```
proofwiki-dump.xml            <- official nightly dump: https://proofwiki.org/xmldump/latest.xml.gz
      |
extract_pages.py              -> wiki_pages/*.txt, redirect_map.json, page_titles.json
      |  (per-page text files; NOT used by the graph builder anymore, kept for reference/debugging)
      |
build_graph.py                -> graph_nodes.json, graph_edges.json
      |  (streams the XML directly via iterparse -- fast; classifies every page into
      |   Theorem/Definition/Axiom/Symbol/Proof/Mathematician/Book/Category, extracts
      |   citation edges, aliases, has_proof flags -- see "Key data model" below)
      |
cluster_hierarchy.py          -> cluster_hierarchy.json          [SLOW -- Louvain, ~minutes]
      |  (recursive community detection -- only needs re-running if EDGE STRUCTURE
      |   changes, i.e. new (source,target) pairs appear/disappear. Relabeling an
      |   existing edge's TYPE does not require re-running this, since clustering
      |   only cares about STRUCTURAL_EDGE_TYPES set membership, not exact label.)
      |
build_viz_data.py             -> viz_data.json (~13.5MB)
      |  (compacts everything into integer-indexed arrays for the browser: titles,
      |   nodeType, nodeCluster, tree, fullEdges, aliasPairs, aliasNamePairs, etc.)
      |
assemble_explorer.py           -> explorer.html
      |  (splices viz_data.json into explorer_template.html's `const DATA = ...`
      |   placeholder. Both this script and the editable template now live
      |   directly in this project directory -- the template is the actual
      |   editable JS/HTML source; explorer.html is a build artifact, never
      |   hand-edited.)
```

### Template location resolved

`explorer_template.html` and `assemble_explorer.py` live directly in this project
directory now (`c:/Users/nathan37/Desktop/ProofWiki/`) -- an earlier version of this
file warned they only existed in a since-expired scratchpad from the session that
first built this tool (rooted in `Desktop/OSDev` by mistake); that recovery already
happened. Edit `explorer_template.html` directly, then rebuild with
`python assemble_explorer.py`.

## Key data model

Node types (`nodeType` int code): 0=Theorem, 1=Definition, 2=Axiom, 3=Symbol, 4=Proof.
Rendered as circle/square/diamond/triangle/hexagon respectively (color-independent
identity channel) for individual concepts; cluster bubbles stay circles with a
composition-proportional multi-color ring instead (single dominant-color fill was
hiding rare types like Axiom, which is only 0.46% of all nodes and almost never wins
a cluster's "dominant type" vote).

Edge types: `link`, `transclusion`, `proof_of`, `subpage_of`, `template_ref` (from
`{{Defof}}`/`{{Namedfor}}`/`{{NamedforDef}}`/`{{axiom-link}}`/`{{ProofRuleLink}}`/
`{{EuclidDefLink}}`/`{{Lemma}}` template citations), `see_also` (loose cross-references
under Also-see/Sources/etc.), `generalization` (Generalizations/Special cases sections).

**Strict vs. non-strict** matters a lot: `STRICT_EDGE_TYPES` (link, transclusion,
proof_of, subpage_of, template_ref) feed the "Depends on" panel and the transitive
prerequisite closure. `see_also`/`generalization` don't — they're real relationships
but not prerequisites, and mixing them into the closure caused it to explode to
thousands of nodes within 2-3 hops (see "Big findings" below).

Aliases: `aliasPairs` (resolvable, bold-linked synonyms -> another real node) and
`aliasNamePairs` (bold but unlinked plain-text names, e.g. "primal element" —
no node to point to).

`has_proof`: per-Theorem-node flag, true if a real proof exists anywhere (embedded
`==Proof==`-family heading OR a separate `/Proof N` subpage), excluding pages that
only have a `{{ProofWanted}}` stub. ~66% of theorems have one. Rendered as solid vs.
dashed outline.

## Big findings this session (don't re-derive these — they cost real iteration)

1. **Filenames can't contain `:`** — `Definition:Group` written to disk as
   `Definition_Group.txt` silently loses the namespace prefix if you reconstruct
   titles from filenames. Fixed by reading titles straight from the XML, never
   round-tripping through the filesystem for the graph builder.

2. **`{{Defof}}`/`{{Namedfor}}` are NOT redundant with bracket links** — 46% of
   `Defof` uses and 100% of `Namedfor` uses have no corresponding `[[link]]`
   anywhere else on the page. Assuming "some page has both" and testing on one
   example was wrong; had to check the whole corpus.

3. **A `{{ProofWanted}}` marker means "no real proof here" even if the section has
   substantial prose** — Fermat's Last Theorem's "Proof" section is three sentences
   citing Wiles' paper, explicitly flagged `{{ProofWanted}}`. Heading presence alone
   overclaims; check for this template.

4. **Proof headings aren't just "Proof"/"Proof N"** — 5,182 distinct real variants
   exist ("Proof of Existence", "Direct Proof", "Proof of $(1)$", etc.). Match the
   word "proof" anywhere in the heading, not an exact heading match.

5. **THE BIG ONE: heading classification must strip wikilink markup before matching.**
   A heading like `== [[Definition:Group/Also denoted as|Also denoted as]] ==` was
   being matched RAW against classification regexes, which obviously fails since the
   text starts with `[[D...` not "also denoted as". This affected **29.5% of all
   wikilinked headings corpus-wide** (12,651 of 42,851) — 8,190 wrongly-strict
   headings that should have collapsed as metadata, 4,445 missed alias sections.
   Found via a **negative-intersection audit**: enumerate every heading's
   classification bucket, then manually inspect what's landing in the "default/
   catch-all" bucket for anything suspicious. **This methodology is the single most
   valuable technique used this session — when adding new extraction rules, always
   audit the residual/unmatched set afterward, don't just spot-check examples that
   happen to work.**

6. **Naive transitive closure explodes — and it's not noise, it's real.** Even after
   fixing strict/see_also separation, walking "cites" transitively still hit
   thousands of nodes by hop 5-6 for every theorem tested. Tried pruning by
   "hub" in-degree first — didn't work at all (graph has too many redundant paths,
   pruning a hub just reroutes around it). What actually works: **stop BFS
   adaptively right before any hop would add more than ~500 new nodes** (a
   per-hop width threshold, not a fixed depth) — this is the real signature of
   crossing from "specific to this theorem" into "shared mathematical foundations"
   (Set/Element/Mapping). Lands at 249-526 nodes / 3-4 hops for every theorem tested,
   adapting per-concept rather than using one guessed constant.

7. **Bold text's meaning is context-dependent, not deterministic.** On a normal
   Definition page, bold marks self-reference (`A '''group''' is...`). Under an
   "Also known as" section, bold marks a genuine synonym. Same markup, opposite
   meaning depending on which section it's in — this is why "the wiki has consistent
   style" doesn't mean "one deterministic rule with no exceptions."

8. **Template-citation-shortcuts are a whole category, not just Defof/Namedfor** —
   `{{Link-to-category}}` (8,302 uses!), `{{NamedforDef}}`, `{{axiom-link}}`,
   `{{ProofRuleLink}}`, `{{EuclidDefLink}}`, `{{Lemma|Parent|N}}` were all
   undiscovered gaps found via a full template-frequency audit (grep every
   `{{Template|param}}` invocation, rank by frequency, manually classify each).
   Deliberately NOT extracted: `{{MathWorld}}`/`{{OEIS}}`/`{{Mizar}}`/etc. (external,
   no internal node), `{{NumberPageLink}}`/`{{ExtractTheorem}}` (navigation/editorial,
   not citations), `{{BookLink}}`/citation templates (real but Book: nodes aren't
   part of the concept/closure graph, low payoff). See the big comment block in
   `build_graph.py` right above `LINK_TO_CATEGORY_RE` for the full covered/not-covered
   list — **keep that comment current if you add more templates.**

## Known open items / limitations (honest, not yet fixed)

- Cluster boundaries were NOT re-verified after the last two rounds of edge
  additions (the 6 new templates added ~8,900 genuinely NEW edges, ~1.5% of total —
  probably negligible effect on Louvain communities, but not re-run to confirm,
  unlike the heading-relabeling fix which was mathematically guaranteed zero-impact).
- `{{Defof}}`/`{{axiom-link}}`-style resolution only handles the shapes found so
  far. Assume more template shapes exist; re-run the template-frequency audit
  periodically (see finding #8's script pattern).
- Book:/Mathematician: citation edges are real but deliberately not fully mined
  (BookLink, citation-family templates) since those nodes aren't part of the
  concept/closure graph — low priority unless the tool's scope changes.

## What's built and working (verified, not just implemented)

- Full extraction/graph/cluster/viz pipeline, rebuildable end to end.
- Fractal zoom: top-level "galaxy" of ~200 clusters -> click to zoom into a
  cluster -> leaf level shows real force-simulated concept nodes.
- Isolated-cluster bucketing ("Miscellaneous" group) at every zoom level so
  disconnected components don't create lattice sprawl — confirmed 99.7% of the
  graph is one giant connected component, ~180 nodes are true isolates/micro-islands,
  all correctly bucketed; 0% of nodes are isolated *within* their own leaf cluster
  (Louvain wouldn't group a node into a community it shares no edge with).
  Global connectivity checked directly with networkx, not assumed.
- Click a node -> detail panel: type, has_proof status, "Also known as" aliases,
  "Depends on" (strict, 1-hop), "Appears in" (all contexts, 1-hop), full adaptive
  prerequisite closure with a "push past the foundation" expand control.
  "Appears in" is the actual answer to "see this concept across all its contexts" —
  it's NOT limited to the same cluster (a naive same-cluster-only version was
  built first and was wrong for exactly this reason — Definition:Group's 1,223
  citations are scattered across nearly the whole graph).
  Reference sidebar ("In view"), sorted by centrality (global citation count, not
  local edge count), hover-links to canvas, VS Code-ish folder grouping (see
  limitation above).
  Search jumps straight to any of the 62,220 concepts through the real cluster tree.
- Legend type-filter actually filters (was dead code for one round — found and fixed).
- Selecting a node highlights its directly-connected edges in bright accent color
  on top of everything else.
- Click-to-zoom-then-immediately-zoom-back-out race condition fixed (two separate
  event handlers were fighting over the same click).
- **Reference-sidebar folder grouping is a real recursive tree** (fixed from the
  single-level `lastIndexOf("/")` version that duplicated 2+-level-deep
  intermediate nodes — see `buildPrefixTree`/`nodeToRows`/`renderRows` in
  `explorer_template.html`). Builds one trie per render, visits each node exactly
  once, collapses singleton-child chains back to a flat full-label row (matching
  the old behavior for the common non-shared-prefix case), forms an expandable
  group at any depth where 2+ distinct rows share a prefix. Verified with a
  standalone Node script (no browser) reproducing the exact `Law of Cosines/Proof
  3/Acute Triangle` case from the bug report — every label now renders exactly
  once at the correct nesting depth.
- **Right-click node annotations**: mark a concept "uninteresting" (greys it out
  on canvas — flat grey fill/stroke, excluded from the scarce top-14 label
  budget, still clickable) or attach a free-text note (small red square marker
  on canvas, opposite corner from the gold "visited" dot so the two never get
  confused). Both editable from the canvas right-click menu OR the detail
  panel's "Mark uninteresting" checkbox / "Add note" button — same `setAnnot()`
  call either way, so the two UIs always stay in sync. A sidebar checkbox
  ("Hide uninteresting") fully filters dimmed nodes out via the existing
  `bodyTypeActive` mechanism instead of just greying them.
  Persisted to `localStorage` under key `proofwiki-explorer-annotations-v1`,
  keyed by node TITLE (not index, since indices aren't stable across a pipeline
  rebuild) — survives page reloads and browser restarts, since the whole point
  of marking something interesting is seeing it again next session. Verified
  with a standalone Node script exercising set/persist/reload/garbage-collect
  (an entry is deleted once both `dim` is false and the note is empty/whitespace,
  so storage never accumulates dead entries).
- **Sidebar row layout fixed**: `#refpanel-list li` used `justify-content:
  space-between` across 3 flex children (toggle, name, count) — with a short
  name in a wide sidebar this threw the label away from its indent/toggle
  instead of keeping them adjacent, making nesting depth unreadable. Fixed by
  giving the name span `flex:1; min-width:0` instead (absorbs remaining width,
  pins count to the true right edge, toggle stays glued to the label). Also
  gave the "virtual" group header (a shared prefix with no real node of its
  own) the same flex/ellipsis treatment — it was previously raw `textContent`
  with no truncation at all. Indent step also bumped 12px -> 18px (`INDENT_STEP`)
  — 12px read as "not indented" at this font size. The collapse toggle's
  clickable area was also just the bare 1-2 character arrow glyph, easy to miss
  entirely; it's now a proper 16x16px padded hit target with a hover highlight
  (`.rl-toggle`), and for "virtual" group headers (no real node backing them,
  so no competing navigate-on-click behavior to protect) the WHOLE row now
  toggles too, not just the arrow.
- **Cluster labels can collide between siblings — fixed in the pipeline, not
  just the template.** `label_for()` in `cluster_hierarchy.py` picks a
  cluster's most-common ProofWiki category (or a generic "{Type} cluster"
  fallback) with zero visibility into what label a sibling cluster landed on.
  Confirmed via direct inspection: 100 sibling-groups / 367 cluster instances
  shared an identical label tree-wide before the fix (e.g. 15 separate size-1
  clusters all labeled literally "Theorem cluster"; 46 separate clusters all
  labeled "Specific Numbers", sizes ranging from 1 to 7617) — same displayed
  name, wildly different concept counts, sitting right next to each other as
  siblings in the same view. Fixed with a post-build disambiguation pass: any
  cluster whose label collides with a sibling's gets its single most-central
  member (highest weighted degree in its own induced subgraph) appended, e.g.
  `"Set Difference — Definition:Set Difference"`. Siblings are disjoint node
  sets by construction (Louvain communities don't overlap), so the appended
  member can never collide between two colliding siblings — guaranteed distinct
  text. Re-ran the full pipeline (`cluster_hierarchy.py` -> `build_viz_data.py`
  -> `assemble_explorer.py`) since this needed real Louvain reclustering context
  (`cluster_members`) not present in the old JSON; 379 clusters were renamed,
  0 collisions remain (verified directly against the rebuilt
  `cluster_hierarchy.json`, tree-wide, not spot-checked).
- **Canvas label truncation now suffix-aware**: the old `txt.slice(0, maxChars
  -1)` always cut from character 0, so sibling titles sharing a long prefix
  (e.g. `"X/Proof 1"` vs `"X/Proof 2"` — extremely common here, ProofWiki
  subpages are named exactly this way) truncated to *identical* visible text on
  small bubbles, reading as "two nodes with the same name" even though the
  underlying data has zero duplicate titles (checked directly against all
  62,220). Fixed to keep the final `/`-segment intact and eat into the front
  instead, so the part that actually distinguishes siblings stays visible.
- **Cluster bubbles staying plain circles (never shape-coded even when highly
  homogeneous) is deliberate, confirmed with the user** — shape identity is
  reserved for individual leaf concepts; a cluster's composition ring is the
  intended signal for "what's inside," not a forced single shape.
- **Sidebar folder tree rewritten to a real nested `<ul>/<li>` structure —
  the flat-list-with-computed-pixel-indentation approach was the actual root
  cause of three straight rounds of folder bugs, not one-off mistakes to keep
  patching.** After indentation and collapse-hit-target fixes still didn't
  resolve reported problems, checked how mature implementations actually do
  this (`jstree` — the most widely-used JS tree library; `justinchmura/
  js-treeview`, a minimal vanilla reference): both build genuine nested
  containers per level (a parent `<li>` holds its own child `<ul>`), get
  indentation for free from that nesting via a single CSS `padding-left` per
  level (no `depth * N` arithmetic in JS), and treat expand/collapse as a
  local operation — only that node's own children container gets built/shown/
  hidden, never a full-list rebuild. The old version fought against the DOM
  instead of using it: one flat `<ul>`, manually computed `paddingLeft` per
  row, and a full `renderRefList()` rebuild of the *entire* sidebar on every
  single toggle click. Rewrote to match the proven pattern: `buildTreeInto()`
  recurses into real `<li><ul class="rl-children">` nesting; each group's
  children `<ul>` is built once (lazily, on first expand) and thereafter just
  toggles a `.collapsed` class. `buildPrefixTree`/`nodeToRows` (the actual
  tree-shape logic, already unit-tested) are unchanged by this — only the DOM
  construction/event-wiring layer was rebuilt.
- Sidebar sort order: folders before files (VS Code/Finder/jstree convention),
  centrality-descending within each bucket — was sorting everything by
  centrality alone, which interleaved folders and plain items arbitrarily.
- **Force simulation (`simStep`) picked up two ideas from d3-force's actual
  source** (the standard for this exact problem — force-directed graph
  layout — read directly from `d3/d3-force` on GitHub rather than
  re-deriving): (1) an alpha/cooling schedule — alpha starts at 1, decays
  exponentially toward 0 every tick (`alpha += (0-alpha)*ALPHA_DECAY`,
  ALPHA_DECAY derived the same way d3-force derives it, settles in ~300 ticks
  by construction) and scales every force's contribution to velocity, so the
  layout settles in a bounded, predictable time instead of relying purely on
  velocity damping to happen to reach equilibrium (which had no guaranteed
  settle time). Reheated (`reheat()`, alpha=1) on view rebuild / physics
  slider changes; a gentler floor (`alpha = Math.max(alpha, 0.3)`) while
  manually dragging a node, matching d3-force's own "alphaTarget(0.3) during
  drag" idiom, so the rest of the layout responds smoothly without a jarring
  full re-explosion. (2) Link-force degree bias — a hub with many edges now
  moves less per-edge than a peripheral node with one or two (each side's
  share of a spring correction is proportional to the OTHER side's degree,
  `edgeDegree` recomputed per view in `recomputeEdgeDegree()`), since
  repositioning a hub disturbs every one of its edges simultaneously while a
  peripheral node only disturbs this one. Without this, hub concepts (e.g.
  Definition:Group, 1000+ citations) got yanked around by every incident
  spring with equal, full-strength force, which is backwards. Verified both
  in isolation with a standalone Node script (alpha settles in exactly ~300
  ticks and decays monotonically; equal-degree edges reproduce the *exact*
  old symmetric behavior with zero regression, confirming this only changes
  anything for edges actually touching a hub). Deliberately did NOT port
  d3-force's Barnes-Hut quadtree for the repulsion force (its main claim to
  fame) — checked actual cluster sizes first (`LEAF_MAX_SIZE=220`, ~199
  top-level clusters) and confirmed the current O(n²) pairwise loop is a few
  tens of thousands of ops per frame at worst, nowhere near a real bottleneck
  at this scale, so a quadtree would be complexity spent on a problem we
  don't have. Also deliberately did NOT copy d3-force's absolute force
  constants (repulsion=30, velocityDecay=0.6, etc.) — those are tuned for a
  completely different force scale than ours; only the cooling *structure*
  and the link-bias *idea* were portable, not the numbers.

## Design choices worth remembering

- Dark "observatory/star-chart" visual theme, deliberately single-theme (no light
  mode) since the subject — a constellation of interlinked math knowledge — suits
  a committed dark visualization aesthetic, per the artifact-design skill's
  allowance for deliberate single-world commitments.
- Categorical palette: Theorem=blue, Definition=aqua/teal, Axiom=amber, Symbol=green,
  Proof=violet — from the validated dataviz-skill categorical palette, first 5 of 8
  slots, CVD-safe ordering preserved.
- "Visited" tracking (small gold dot on canvas nodes + search results) — borrowed
  from the visited-hyperlink convention / access-gated-discovery principle in the
  user's own prior OSDev visualization project design notes
  (`c:/Users/nathan37/Desktop/OSDev/visualizations/DESIGN_ARCHITECTURE_INSIGHTS.md`
   — worth reading that file directly if extending this tool further; it has a lot
   of hard-won UI/cognition principles: no manufactured variance, identity vs.
   richness as separate channels, color-is-earned-not-ambient, etc.)

## Comparable prior art (researched, not reinvented blind)

Closest existing tools are all for *formal* proof assistants (Lean/Coq/Metamath),
not natural-language wikis: Lean Atlas (most feature-rich — 12+ filter axes,
"Compass" algorithm for minimal semantic-dependency pruning), lean-graph (click-node-
for-docs, similar interaction model), Metamath's proof visualizers. NaturalProofs
(NeurIPS 2021) uses the *identical* ProofWiki corpus but as a flat ML training
dataset with zero visualization/exploration tooling — confirms the raw material has
been mined before, but nobody built an explorer from it. This combination (ProofWiki
+ Louvain multi-resolution clustering + force-directed semantic zoom) appears to be
genuinely novel, even though each individual technique is well-trodden elsewhere.

## If continuing in a new session

1. Read this file.
2. Check whether `explorer_template.html` was successfully copied out of the old
   session's scratchpad into this directory (see "IMPORTANT: recover the template"
   above) — if not, it may be lost, and the JS/HTML would need to be rebuilt from
   scratch referencing this file's description of what it does.
3. `explorer.html` (the current build artifact) already reflects everything in
   "Big findings" and "What's built" above — it's up to date as of this write.
4. Full rebuild command sequence (only if data/extraction logic changes):
   `python build_graph.py && python cluster_hierarchy.py && python build_viz_data.py`
   then splice `viz_data.json` into `explorer_template.html`'s `const DATA = ...`
   placeholder (see `assemble_explorer.py` pattern above) to produce `explorer.html`.
   Skip `cluster_hierarchy.py` (the slow step) if you're only changing edge *labels*
   or node *attributes*, not which (source,target) pairs exist.
