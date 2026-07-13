"""
Extract ProofWiki's dump into per-page text files, namespace-aware.

Unlike the OSDev wiki (single flat namespace), ProofWiki titles already carry
their namespace as a text prefix for non-main namespaces (e.g. the literal
page title for a Definition-namespace page is "Definition:Group", not just
"Group"), so a single flat wiki_pages/ directory is safe -- there's no cross-
namespace collision the way "Group" (theorem) and "Definition:Group" would
never collide on disk.

We still guard against the same Windows case-insensitive-filesystem collision
bug found in the OSDev extraction (e.g. two titles differing only by case
silently overwriting each other), using the same strategy: first substantial
variant wins the clean filename, extra substantial variants get a
" (variant N)" suffix, and redirect-only variants get folded into
redirect_map.json instead of writing a stub file.

Namespaces extracted (the ones relevant to the proof concept graph):
  0   (no prefix)     Theorems + embedded/subpage Proofs
  14  Category:       Field-of-mathematics groupings
  100 Axiom:          Foundational axioms
  102 Definition:     Formal definitions
  104 Symbols:        Notation glossary
  106 Mathematician:  Attribution / "named after" linkage
  108 Book:           Source citations
"""
import json
import re
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
XML_PATH = HERE / "proofwiki-dump.xml"
PAGES_DIR = HERE / "wiki_pages"
REDIRECT_MAP_PATH = HERE / "redirect_map.json"
TITLE_MANIFEST_PATH = HERE / "page_titles.json"
NS = "{http://www.mediawiki.org/xml/export-0.11/}"

WANTED_NAMESPACES = {"0", "14", "100", "102", "104", "106", "108"}

REDIRECT_RE = re.compile(r"^#REDIRECT\s*:?\s*\[\[([^\]|#]+)", re.IGNORECASE)


def safe_filename(title: str, suffix: str = "") -> str:
    name = re.sub(r'[\\/:*?"<>|]', "_", title)
    return name[:180] + suffix + ".txt"


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
                yield title, ns, (text or "")
            elem.clear()


def is_redirect(text: str):
    m = REDIRECT_RE.match(text.strip())
    return m.group(1).strip() if m else None


def main():
    groups = defaultdict(list)  # lower_title -> [(title, ns, text), ...] in XML order
    ns_totals = defaultdict(int)
    for title, ns, text in iter_wanted_pages():
        groups[title.lower()].append((title, ns, text))
        ns_totals[ns] += 1

    if PAGES_DIR.exists():
        for f in PAGES_DIR.glob("*.txt"):
            f.unlink()
    else:
        PAGES_DIR.mkdir()

    redirect_map = {}
    title_manifest = {}  # on-disk filename stem -> real MediaWiki title (with ':', etc. intact)
    written = 0
    collision_groups_resolved = 0
    disambiguated = 0

    for lower_title, variants in groups.items():
        substantial = [(t, ns, x) for (t, ns, x) in variants if not is_redirect(x) and len(x.strip()) > 0]
        redirects = [(t, ns, x) for (t, ns, x) in variants if is_redirect(x)]

        if len(variants) > 1:
            collision_groups_resolved += 1

        if substantial:
            primary_title, primary_ns, primary_text = substantial[0]
            fname = safe_filename(primary_title)
            PAGES_DIR.joinpath(fname).write_text(primary_text, encoding="utf-8")
            title_manifest[fname[:-4]] = primary_title
            written += 1
            for i, (t, ns, x) in enumerate(substantial[1:], start=2):
                fname = safe_filename(t, f" (variant {i})")
                PAGES_DIR.joinpath(fname).write_text(x, encoding="utf-8")
                title_manifest[fname[:-4]] = t
                written += 1
                disambiguated += 1
            for t, ns, x in redirects:
                redirect_map[t] = primary_title
        else:
            first_title, first_ns, first_text = variants[0]
            fname = safe_filename(first_title)
            PAGES_DIR.joinpath(fname).write_text(first_text, encoding="utf-8")
            title_manifest[fname[:-4]] = first_title
            written += 1
            for t, ns, x in variants:
                target = is_redirect(x)
                if target:
                    redirect_map[t] = target

    def resolve(title, depth=0):
        if depth > 5 or title not in redirect_map:
            return title
        return resolve(redirect_map[title], depth + 1)

    resolved_map = {t: resolve(t) for t in redirect_map}
    REDIRECT_MAP_PATH.write_text(json.dumps(resolved_map, indent=2, ensure_ascii=False), encoding="utf-8")
    TITLE_MANIFEST_PATH.write_text(json.dumps(title_manifest, ensure_ascii=False), encoding="utf-8")

    print("Pages extracted per namespace (includes redirects):")
    for ns, c in sorted(ns_totals.items()):
        print(f"  ns={ns}: {c}")
    print(f"\nCase-insensitive collision groups encountered: {collision_groups_resolved}")
    print(f"Genuine parallel-article disambiguations: {disambiguated}")
    print(f"Total files written: {written}")
    print(f"Redirect map entries: {len(resolved_map)} -> {REDIRECT_MAP_PATH}")
    print(f"Title manifest entries: {len(title_manifest)} -> {TITLE_MANIFEST_PATH}")


if __name__ == "__main__":
    main()
