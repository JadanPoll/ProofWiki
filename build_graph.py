"""
Build the ProofWiki concept graph directly from the XML dump (not from
wiki_pages/*.txt). Reading 111k individual small files back off disk was
the bottleneck in an earlier version of this script (~9+ minutes, I/O
bound, plausibly Windows Defender scanning every file open); streaming the
dump once with iterparse is the same trick rebuild_corpus.py/extract_pages.py
already use and is far faster. It also sidesteps a real bug the file-based
version had: filenames can't contain ':', so a page titled "Definition:Group"
was written to disk as "Definition_Group.txt", and reconstructing the title
from the filename silently lost the namespace prefix -- every node came out
classified as "Theorem". Reading titles straight from the XML avoids that.

Node types (by namespace prefix on the title):
  Theorem      ns=0, no '/' in title (or a '/' subpage that ISN'T a proof
               variant, e.g. "X/Historical Note" collapses into "X")
  Proof        ns=0, subpage whose final segment looks like a proof variant
               ("Proof", "Proof 1", "Algebraic Proof", "Corollary", ...) --
               kept as its own node and linked to its parent Theorem, since
               "N different ways to prove the same thing" is exactly the
               parallel structure this graph is meant to expose.
  Definition   ns=102 (subpages collapse into the parent concept)
  Axiom        ns=100 (subpages collapse into the parent concept)
  Symbol       ns=104
  Mathematician ns=106
  Book         ns=108
  Category     ns=14

Edges: every [[wikilink]] and {{:Transclusion}} from a page's wikitext to
another page we kept as a node, plus [[Category:X]] tags as a separate
'in_category' edge type.
"""
import json
import re
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
XML_PATH = HERE / "proofwiki-dump.xml"
REDIRECT_MAP_PATH = HERE / "redirect_map.json"
NODES_OUT = HERE / "graph_nodes.json"
EDGES_OUT = HERE / "graph_edges.json"
NS = "{http://www.mediawiki.org/xml/export-0.11/}"

WANTED_NAMESPACES = {"0", "14", "100", "102", "104", "106", "108"}

PROOF_SUFFIX_RE = re.compile(
    r"(proof|corollary|lemma|algebraic proof|classic proof|direct proof|"
    r"proof by induction|proof by contradiction|geometric proof|"
    r"visual proof|alternative proof|general proof|converse)",
    re.IGNORECASE,
)
COLLAPSE_SUFFIX_RE = re.compile(
    r"^(also known as|also see|also defined as|also denoted as|historical note|"
    r"examples?|sources?|notation|technical note|mistake|warning|comment|"
    r"also presented as|linguistic note|variants?|motivation)\b",
    re.IGNORECASE,
)

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
TRANSCLUSION_RE = re.compile(r"\{\{:([^}|]+)")
CATEGORY_LINK_RE = re.compile(r"\[\[Category:([^\]|]+)", re.IGNORECASE)
REDIRECT_RE = re.compile(r"^#REDIRECT\s*:?\s*\[\[([^\]|#]+)", re.IGNORECASE)
# {{Defof|X|...}} and {{Namedfor|X|...}} cite a Definition/Mathematician page
# by template instead of a [[bracket link]] -- confirmed (see check_defof_gap.py)
# that ~46% of Defof uses and 100% of Namedfor uses have NO redundant bracket
# link anywhere else on the page, so skipping these silently drops real edges.
DEFOF_RE = re.compile(r"\{\{Defof\|\s*([^|}]+)")
NAMEDFOR_RE = re.compile(r"\{\{Namedfor\|\s*([^|}]+)")

# ---------------------------------------------------------------------------
# THE NEGATIVE SPACE, DOCUMENTED: this pipeline only knows how to turn a
# citation into an edge if it recognizes the SHAPE that citation was written
# in. Every shape below was found by auditing the corpus's actual template
# vocabulary (grep every {{Template|param}} invocation across ns 0/100/102,
# rank by frequency, manually classify each one) -- not by reading a spec,
# because ProofWiki has none. Re-run that audit (see check_proof_coverage.py-
# style scripts in git history, or just re-grep TEMPLATE_RE across the dump)
# whenever this feels incomplete again; assume there ARE more shapes we
# haven't found, since each pass so far has turned up new ones.
#
# COVERED (this file resolves these to real edges):
#   {{Defof}}, {{Namedfor}}                 -- Definition / Mathematician
#   {{NamedforDef}}                         -- Mathematician (supports
#                                              multiple co-attributed people
#                                              via name2=, name3=, ...)
#   {{Link-to-category}} / {{LinkToCategory}} -- Category
#   {{axiom-link}} / {{Open-set-axiom}} / {{Ring-axiom}} / {{Group-axiom}}
#                                            -- NOT resolved to a specific
#                                              target (Group-axiom etc. take
#                                              a NUMBER not a name, e.g.
#                                              {{Group-axiom|1}} = "closure",
#                                              impossible to resolve to a
#                                              title without a lookup table
#                                              we don't have) -- EXCEPT
#                                              axiom-link, which DOES take a
#                                              name and is handled.
#   {{ProofRuleLink}}                       -- bare (ns=0) title, confirmed
#                                              empirically (Definition:Law of
#                                              Excluded Middle does NOT
#                                              exist; the bare title does)
#   {{EuclidDefLink|book|def|Name}}         -- Definition:Name (3rd param)
#   {{Lemma|Parent|N}}                      -- Parent/Lemma N subpage
#
# KNOWN NOT COVERED, DELIBERATELY (not a gap, a judgment call):
#   {{MathWorld}}, {{OEIS}}, {{Mizar}}, {{Pi-base}}, {{KhanAcademy}},
#   {{WP}}                                  -- external (non-ProofWiki)
#                                              references; there is no
#                                              internal node to point to
#   {{NumberPageLink}}, {{ExtractTheorem}}, {{expand}}, {{mergeto}},
#   {{improve}}, {{rename}}, {{questionable}} -- navigation/editorial
#                                              metadata, not citations
#   {{BookLink}}, {{citation}}, {{DateRange}}, {{SourceReview}}
#                                            -- Book/Source citations;
#                                              real, but Book: nodes aren't
#                                              part of the concept/closure
#                                              graph anyway (see CONCEPT_TYPES
#                                              in cluster_hierarchy.py), so
#                                              the payoff is low relative to
#                                              re-auditing effort
#   {{EuclidPropStatement|body=...}}        -- NOT a gap: its body= param is
#                                              literally wikitext containing
#                                              real [[links]], which the
#                                              plain WIKILINK_RE scan below
#                                              already catches regardless of
#                                              being inside a template
#                                              parameter -- regex doesn't
#                                              know or care about template
#                                              boundaries
#   Any template not in this list at all    -- the true unknown unknowns;
#                                              this list is only as complete
#                                              as the last audit, not exhaustive
LINK_TO_CATEGORY_RE = re.compile(r"\{\{Link-?to-?category\|\s*([^|}]+)", re.IGNORECASE)
NAMEDFOR_DEF_RE = re.compile(r"\{\{NamedforDef\|([^}]*)\}\}", re.IGNORECASE)
NAMEDFOR_DEF_NAME_RE = re.compile(r"(?:^\s*|\bname\d*\s*=\s*)([^|}=]+)")
AXIOM_LINK_RE = re.compile(r"\{\{axiom-link\|\s*([^|}]+)", re.IGNORECASE)
PROOF_RULE_LINK_RE = re.compile(r"\{\{ProofRuleLink\|\s*([^|}]+)", re.IGNORECASE)
EUCLID_DEF_LINK_RE = re.compile(r"\{\{EuclidDefLink\|\s*[^|}]+\|\s*[^|}]+\|\s*([^|}]+)", re.IGNORECASE)
LEMMA_LINK_RE = re.compile(r"\{\{Lemma\|\s*([^|}]+)\|\s*([^|}]+)", re.IGNORECASE)
# ~14.7% of theorem-ish pages (3,516 of 23,897) have NO proof anywhere --
# neither embedded nor a separate subpage (open problems like Goldbach's
# Conjecture, unproven assertions). A flat "Theorem" color/shape makes those
# visually identical to the 85% that do have a proof, which is misleading --
# this heading match is how a Theorem node picks up "has_proof": True.
#
# NOT just "Proof" / "Proof N": checked headings containing "proof" that a
# stricter regex would miss and found 5,679 real occurrences across 5,182
# distinct headings -- "Proof of Existence", "Outline of Proof", "Direct
# Proof", "Proof of $(1)$", "Proof of {{Metric-space-axiom|1}}", etc. All
# genuine proof content, just phrased more specifically than bare "Proof".
# Matching the word "proof" anywhere in the heading (rather than requiring
# the heading to BE "Proof") trades a small false-positive risk (a heading
# that merely mentions the word without being one) for avoiding the much
# worse false negative of hiding a real proof from the reader.
PROOF_HEADING_RE = re.compile(r"^=+[^=\n]*\bproofs?\b[^=\n]*=+\s*$", re.MULTILINE | re.IGNORECASE)
# A Proof heading isn't proof of a proof: 2,483 of 30,250 proof-headed pages
# (8.2%) -- including Fermat's Last Theorem -- turned out to be stubs
# pointing at an external paper via {{ProofWanted}}, ProofWiki's own "not
# actually written here" marker. Checked FLT directly: its "== Proof =="
# section is three sentences plus a citation to Wiles' paper, explicitly
# flagged {{ProofWanted|add a broad overview of Wiles proof}} -- not a
# formalized proof by any reasonable definition.
PROOF_WANTED_RE = re.compile(r"\{\{\s*[Pp]roof[ _]?[Ww]anted", re.IGNORECASE)

# A transitive prerequisite closure (BFS over "cites") turned out to explode
# to thousands of nodes within 2-3 hops for almost any non-trivial theorem,
# because ordinary wikilinks don't distinguish "I need this to state/prove
# the theorem" from "related, see also" -- one loose cross-reference at any
# hop drags its whole branch into the closure. Splitting each page's text by
# section and tagging links found under a non-prerequisite header (reusing
# COLLAPSE_SUFFIX_RE's keyword set, since it's the same "this is meta, not
# core content" judgment) as a separate 'see_also' edge type fixes this at
# the source: the strict edge types now only capture genuine dependencies.
SECTION_HEADER_RE = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.MULTILINE)

# Two sub-categories carved out of the generic "nonstrict" bucket because
# each carries real, distinct structured information that a flat see_also
# edge was throwing away:
#   - "Also known as" / "Also defined as" / "Also presented as": genuine
#     synonym lists (bold-wrapped wikilinks name the alias -- see
#     Definition:Abelian Group/Also known as: '''commutative group''').
#     Deliberately excludes "Also denoted as", which is about NOTATION
#     ($\gen{G,\circ}$-style symbols), not alternate names.
#   - "Generalizations" / "Special cases": a genuine specialization/
#     generalization relationship, not a loose cross-reference.
ALIAS_HEADING_RE = re.compile(r"^(also known as|also defined as|also presented as)\b", re.IGNORECASE)
GENERALIZATION_HEADING_RE = re.compile(r"^(generalizations?|generalisations?|special cases?)\b", re.IGNORECASE)
# Bold is the real structural foothold marking an alias name -- whether or
# not it's ALSO a link is incidental. 7.6% of alias-family subpages (245 of
# 3,243) have zero bold-LINKED matches but do have plain bold text: Axiom:
# Peano's Axioms/Also defined as bolds '''primal element''' with no link at
# all; Definition:Arborescence/Also known as bolds '''$r$-arborescence'''
# (LaTeX, not a link). BOLD_RE matches any bold span; if its content is
# ENTIRELY a single wikilink, resolve it to a real node (structured alias),
# otherwise keep the plain text as a string alias.
BOLD_RE = re.compile(r"'''(.+?)'''")
PURE_LINK_RE = re.compile(r"^\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]$")


def extract_bold_aliases(text, canonical, node, resolve_link):
    """Bold marks an alias name whether or not it's also a link. If a bold
    span's entire content is a single wikilink, resolve it to a real node
    (a structured cross-reference); otherwise keep its plain text as a
    string alias name (strip any partial wikilink markup down to display
    text first, e.g. an incidental "[[X|y]]" fragment inside a longer bold
    span that isn't itself a pure link)."""
    for m in BOLD_RE.finditer(text):
        content = m.group(1).strip()
        pure = PURE_LINK_RE.match(content)
        if pure:
            resolved = resolve_link(pure.group(1))
            if resolved and resolved[0] != canonical:
                node.setdefault("aliases", set()).add(resolved[0])
            continue
        display = re.sub(r"\[\[(?:[^\]|#]*\|)?([^\]]+)\]\]", r"\1", content).strip()
        # unexpanded template markup ({{{1}}}, {{Foo}}) is never a real name
        if display and "{{" not in display and "}}" not in display \
                and display.lower() != canonical.split(":", 1)[-1].lower():
            node.setdefault("alias_names", set()).add(display)


HEADING_LINK_RE = re.compile(r"^\[\[(?:[^\]|#]*\|)?([^\]]+)\]\]$")


def heading_display_text(heading):
    """Headings are very often written as a wikilink to a subpage rather
    than plain text -- e.g. "== [[Definition:Group/Also denoted as|Also
    denoted as]] ==" -- and a raw '^' match against COLLAPSE_SUFFIX_RE/
    ALIAS_HEADING_RE/GENERALIZATION_HEADING_RE fails immediately since the
    text starts with "[[D..." not the actual heading word. Checked the
    scale: of 42,851 wikilinked headings across ns 0/100/102, 12,651
    (29.5%) were being misclassified as strict content this way -- 8,190
    should have collapsed as metadata, 4,445 were missed alias sections.
    Stripping to display text before classifying fixes all of it at once."""
    m = HEADING_LINK_RE.match(heading)
    return m.group(1).strip() if m else heading


def classify_sections(text):
    """Return (strict_text, alias_text, generalization_text, other_nonstrict_text)."""
    matches = list(SECTION_HEADER_RE.finditer(text))
    if not matches:
        return text, "", "", ""
    strict_parts = [text[:matches[0].start()]]
    alias_parts = []
    generalization_parts = []
    other_parts = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        heading = heading_display_text(m.group(2).strip())
        if ALIAS_HEADING_RE.match(heading):
            alias_parts.append(body)
        elif GENERALIZATION_HEADING_RE.match(heading):
            generalization_parts.append(body)
        elif COLLAPSE_SUFFIX_RE.match(heading):
            other_parts.append(body)
        else:
            strict_parts.append(body)
    return "".join(strict_parts), "".join(alias_parts), "".join(generalization_parts), "".join(other_parts)


NS_PREFIXES = {
    "Definition:": "Definition",
    "Axiom:": "Axiom",
    "Symbols:": "Symbol",
    "Mathematician:": "Mathematician",
    "Book:": "Book",
    "Category:": "Category",
}
# Types whose subpages get the collapse-metadata-else-keep-as-variant treatment.
# Mathematician/Book/Category titles are used as-is -- ProofWiki doesn't nest
# meaningful sub-content under those namespaces the way it does for the rest.
SUBPAGE_AWARE_TYPES = {"Theorem", "Definition", "Axiom", "Symbol"}


def classify(title: str):
    base_type = None
    for prefix, ntype in NS_PREFIXES.items():
        if title.startswith(prefix):
            base_type = ntype
            break
    if base_type is None:
        if ":" in title.split("/")[0]:
            return None, None  # other namespace prefixes we didn't extract
        base_type = "Theorem"

    if base_type not in SUBPAGE_AWARE_TYPES or "/" not in title:
        return base_type, title

    parent, suffix = title.rsplit("/", 1)
    if COLLAPSE_SUFFIX_RE.match(suffix):
        # metadata subpage (Also known as / Examples / Historical Note / ...):
        # fold into the parent concept rather than treating it as distinct content.
        return classify(parent)
    if base_type == "Theorem" and PROOF_SUFFIX_RE.search(suffix):
        return "Proof", title
    # A genuine content variant (alternate formulation/definition/proof/symbol
    # alias) -- keep it as its own node of the same type; the caller links it
    # to its immediate parent so the "multiple ways to say/prove/notate this"
    # structure stays visible instead of getting flattened away.
    return base_type, title


def iter_wanted_pages():
    context = ET.iterparse(str(XML_PATH), events=("end",))
    for event, elem in context:
        if elem.tag == f"{NS}page":
            ns = elem.findtext(f"{NS}ns")
            title = elem.findtext(f"{NS}title")
            if ns in WANTED_NAMESPACES:
                revisions = elem.findall(f"{NS}revision")
                text = None
                if revisions:
                    text_elem = revisions[-1].find(f"{NS}text")
                    text = text_elem.text if text_elem is not None else None
                yield title, (text or "")
            elem.clear()


def main():
    redirect_map = json.loads(REDIRECT_MAP_PATH.read_text(encoding="utf-8"))

    # Pass 1: classify every title so link resolution knows what's a real node.
    title_to_type = {}
    for title, text in iter_wanted_pages():
        if REDIRECT_RE.match(text.strip()):
            continue
        node_type, canonical = classify(title)
        if node_type:
            title_to_type.setdefault(canonical, node_type)

    def resolve_link(raw_target: str):
        target = raw_target.strip().replace("_", " ")
        target = redirect_map.get(target, target)
        node_type, canonical = classify(target)
        if node_type is None or canonical not in title_to_type:
            return None
        return canonical, title_to_type[canonical]

    # Pass 2: build nodes + edges.
    nodes = {}
    edges = []
    edge_seen = set()

    def add_edge(src, tgt, etype):
        key = (src, tgt, etype)
        if key in edge_seen or src == tgt:
            return
        edge_seen.add(key)
        edges.append({"source": src, "target": tgt, "type": etype})

    for title, text in iter_wanted_pages():
        if REDIRECT_RE.match(text.strip()):
            continue
        node_type, canonical = classify(title)
        if node_type is None:
            continue

        node = nodes.setdefault(canonical, {"type": node_type, "size": 0})
        node["size"] += len(text)
        if node_type == "Theorem" and PROOF_HEADING_RE.search(text) and not PROOF_WANTED_RE.search(text):
            node["has_proof"] = True

        if canonical == title and "/" in title and (node_type in SUBPAGE_AWARE_TYPES or node_type == "Proof"):
            # Not collapsed into its parent -- it's a kept content variant
            # (alternate proof/formulation/definition/symbol alias). Link it
            # to its immediate parent concept.
            parent_raw = title.rsplit("/", 1)[0]
            parent_raw = redirect_map.get(parent_raw, parent_raw)
            parent_type, parent_canonical = classify(parent_raw)
            if parent_type is not None:
                nodes.setdefault(parent_canonical, {"type": parent_type, "size": 0})
                edge_type = "proof_of" if node_type == "Proof" else "subpage_of"
                add_edge(canonical, parent_canonical, edge_type)

        strict_text, alias_text, generalization_text, other_nonstrict_text = classify_sections(text)

        for m in WIKILINK_RE.finditer(strict_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "link")
        for m in WIKILINK_RE.finditer(other_nonstrict_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "see_also")
        for m in WIKILINK_RE.finditer(generalization_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "generalization")
        for m in WIKILINK_RE.finditer(alias_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

        for m in TRANSCLUSION_RE.finditer(strict_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "transclusion")
        for m in TRANSCLUSION_RE.finditer(other_nonstrict_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "see_also")
        for m in TRANSCLUSION_RE.finditer(generalization_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "generalization")
        for m in TRANSCLUSION_RE.finditer(alias_text):
            resolved = resolve_link(m.group(1))
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

        # Bold under Also-known-as/Also-defined-as/Also-presented-as marks
        # genuine synonyms (Definition:Abelian Group/Also known as: '''
        # [[Definition:Commutative Group|commutative group]]''', or plain
        # '''primal element''' with no link at all); self-references (the
        # term restating its own page) are excluded since they're not an
        # alias of anything. Note: this can't detect explicit negation in
        # prose -- Definition:Empty Set/Also known as bolds '''null set'''
        # while explicitly saying that name is "discouraged... there is
        # another concept for null set which ought not to be confused with
        # this." A handful of extracted aliases will be related-but-distinct
        # concepts, not true synonyms; treat this as a strong hint, not
        # ground truth.
        extract_bold_aliases(alias_text, canonical, node, resolve_link)

        # The heading check above only catches an INLINE "== Also known as ==”
        # section. Far more common (3,243 pages vs. 118 caught above) is a
        # dedicated SUBPAGE -- e.g. Definition:Abelian Group/Also known as --
        # whose own top heading is typically just "== Definition ==" (the
        # "Also known as" label only appears in the PARENT's transclusion
        # line, never inside the subpage's own text), so the heading-based
        # classifier misses it entirely and files it as ordinary strict
        # content instead. Checking the page's own title suffix catches this:
        # such a subpage's non-Sources content (already isolated in
        # strict_text by classify_sections, since only its "== Sources =="
        # heading matches COLLAPSE_SUFFIX_RE) IS the alias prose.
        if "/" in title and ALIAS_HEADING_RE.match(title.rsplit("/", 1)[1]):
            extract_bold_aliases(strict_text, canonical, node, resolve_link)

        for m in CATEGORY_LINK_RE.finditer(text):
            cat_title = "Category:" + m.group(1).strip().replace("_", " ")
            if cat_title in title_to_type:
                add_edge(canonical, cat_title, "in_category")

        for m in DEFOF_RE.finditer(strict_text):
            resolved = resolve_link("Definition:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "template_ref")
        for m in DEFOF_RE.finditer(other_nonstrict_text):
            resolved = resolve_link("Definition:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "see_also")
        for m in NAMEDFOR_RE.finditer(strict_text):
            resolved = resolve_link("Mathematician:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "template_ref")
        for m in NAMEDFOR_RE.finditer(other_nonstrict_text):
            resolved = resolve_link("Mathematician:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

        # {{NamedforDef}} is {{Namedfor}} for Definition pages, and supports
        # MULTIPLE co-attributed people via name2=, name3=, ... rather than
        # just one positional param -- NAMEDFOR_DEF_NAME_RE pulls every name
        # (the first positional one plus every numbered "nameN=") out of the
        # whole captured template body.
        for whole, etype in ((strict_text, "template_ref"), (other_nonstrict_text, "see_also")):
            for tmpl in NAMEDFOR_DEF_RE.finditer(whole):
                for nm in NAMEDFOR_DEF_NAME_RE.finditer(tmpl.group(1)):
                    name = nm.group(1).strip()
                    if not name or "=" in name:
                        continue
                    resolved = resolve_link("Mathematician:" + name)
                    if resolved:
                        add_edge(canonical, resolved[0], etype)

        for whole, etype in ((strict_text, "in_category"), (other_nonstrict_text, "in_category")):
            for m in LINK_TO_CATEGORY_RE.finditer(whole):
                cat_title = "Category:" + m.group(1).strip()
                if cat_title in title_to_type:
                    add_edge(canonical, cat_title, "in_category")

        for m in AXIOM_LINK_RE.finditer(strict_text):
            resolved = resolve_link("Axiom:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "template_ref")
        for m in AXIOM_LINK_RE.finditer(other_nonstrict_text):
            resolved = resolve_link("Axiom:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

        for m in PROOF_RULE_LINK_RE.finditer(strict_text):
            resolved = resolve_link(m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "template_ref")
        for m in PROOF_RULE_LINK_RE.finditer(other_nonstrict_text):
            resolved = resolve_link(m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

        for m in EUCLID_DEF_LINK_RE.finditer(strict_text):
            resolved = resolve_link("Definition:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "template_ref")
        for m in EUCLID_DEF_LINK_RE.finditer(other_nonstrict_text):
            resolved = resolve_link("Definition:" + m.group(1).strip())
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

        for m in LEMMA_LINK_RE.finditer(strict_text):
            target = f"{m.group(1).strip()}/Lemma {m.group(2).strip()}"
            resolved = resolve_link(target)
            if resolved:
                add_edge(canonical, resolved[0], "template_ref")
        for m in LEMMA_LINK_RE.finditer(other_nonstrict_text):
            target = f"{m.group(1).strip()}/Lemma {m.group(2).strip()}"
            resolved = resolve_link(target)
            if resolved:
                add_edge(canonical, resolved[0], "see_also")

    # A theorem with a separate /Proof N subpage only shows up as "has_proof"
    # via the proof_of edge pointing back at it, not via its own text -- fold
    # that in now, then default every Theorem node without either signal to
    # explicitly False (rather than leaving the key absent) so the payload
    # step doesn't have to guess what a missing key means.
    for e in edges:
        if e["type"] == "proof_of" and e["target"] in nodes:
            nodes[e["target"]]["has_proof"] = True
    for node in nodes.values():
        if node["type"] == "Theorem":
            node.setdefault("has_proof", False)
        if "aliases" in node:
            node["aliases"] = sorted(node["aliases"])
        if "alias_names" in node:
            node["alias_names"] = sorted(node["alias_names"])

    NODES_OUT.write_text(
        json.dumps({"nodes": [{"id": k, **v} for k, v in nodes.items()]}, ensure_ascii=False),
        encoding="utf-8",
    )
    EDGES_OUT.write_text(json.dumps({"edges": edges}, ensure_ascii=False), encoding="utf-8")

    type_counts = Counter(v["type"] for v in nodes.values())
    edge_type_counts = Counter(e["type"] for e in edges)
    print(f"Nodes: {len(nodes)}")
    for t, c in type_counts.most_common():
        print(f"  {t}: {c}")
    print(f"Edges: {len(edges)}")
    for t, c in edge_type_counts.most_common():
        print(f"  {t}: {c}")
    theorem_nodes = [v for v in nodes.values() if v["type"] == "Theorem"]
    with_proof = sum(1 for v in theorem_nodes if v.get("has_proof"))
    with_aliases = sum(1 for v in nodes.values() if v.get("aliases"))
    total_aliases = sum(len(v["aliases"]) for v in nodes.values() if v.get("aliases"))
    with_alias_names = sum(1 for v in nodes.values() if v.get("alias_names"))
    total_alias_names = sum(len(v["alias_names"]) for v in nodes.values() if v.get("alias_names"))
    print(f"\nTheorem nodes with a proof (embedded or subpage): {with_proof} / {len(theorem_nodes)}")
    print(f"Nodes with at least one resolvable alias (bold+linked): {with_aliases} ({total_aliases} total)")
    print(f"Nodes with at least one string-only alias (bold, unlinked): {with_alias_names} ({total_alias_names} total)")
    print(f"Written: {NODES_OUT.name}, {EDGES_OUT.name}")


if __name__ == "__main__":
    main()
