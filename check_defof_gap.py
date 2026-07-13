"""CHECK C: is {{Defof|X}} / {{Namedfor|X}} usually redundant with an explicit
[[Definition:X]] / [[Mathematician:X]] bracket link elsewhere on the same
page (so my link-only extraction isn't losing anything), or does it
introduce edges my current WIKILINK_RE/TRANSCLUSION_RE regexes never see?
Check across the WHOLE corpus, not one hand-picked example.
"""
import re
from xml.etree import ElementTree as ET

NS = "{http://www.mediawiki.org/xml/export-0.11/}"
DEFOF_RE = re.compile(r"\{\{Defof\|\s*([^|}]+)")
NAMEDFOR_RE = re.compile(r"\{\{Namedfor\|\s*([^|}]+)")
WIKILINK_TARGETS_RE = re.compile(r"\[\[([^\]|#]+)")

pages_with_defof = 0
defof_uses = 0
defof_uncovered_uses = 0
pages_with_uncovered_defof = 0

pages_with_namedfor = 0
namedfor_uses = 0
namedfor_uncovered_uses = 0

context = ET.iterparse("proofwiki-dump.xml", events=("end",))
n = 0
for event, elem in context:
    if elem.tag == f"{NS}page":
        ns = elem.findtext(f"{NS}ns")
        if ns == "0":
            revs = elem.findall(f"{NS}revision")
            text = ""
            if revs:
                te = revs[-1].find(f"{NS}text")
                text = te.text if te is not None and te.text else ""

            existing_links = set(WIKILINK_TARGETS_RE.findall(text))
            existing_links_norm = {t.strip().replace("_", " ") for t in existing_links}

            defofs = DEFOF_RE.findall(text)
            if defofs:
                pages_with_defof += 1
                defof_uses += len(defofs)
                page_has_uncovered = False
                for d in defofs:
                    target = "Definition:" + d.strip()
                    if target not in existing_links_norm:
                        defof_uncovered_uses += 1
                        page_has_uncovered = True
                if page_has_uncovered:
                    pages_with_uncovered_defof += 1

            namedfors = NAMEDFOR_RE.findall(text)
            if namedfors:
                pages_with_namedfor += 1
                namedfor_uses += len(namedfors)
                for person in namedfors:
                    target = "Mathematician:" + person.strip()
                    if target not in existing_links_norm:
                        namedfor_uncovered_uses += 1

            n += 1
        elem.clear()

with open("_defof_check_result.txt", "w", encoding="utf-8") as out:
    out.write(f"ns=0 pages scanned: {n}\n\n")
    out.write(f"Pages using {{{{Defof}}}}: {pages_with_defof}\n")
    out.write(f"Total Defof uses: {defof_uses}\n")
    out.write(f"Defof uses with NO matching [[Definition:X]] bracket link anywhere on the same page: {defof_uncovered_uses} ({100*defof_uncovered_uses/max(defof_uses,1):.1f}%)\n")
    out.write(f"Pages with at least one uncovered Defof (i.e. a real missed edge): {pages_with_uncovered_defof}\n\n")
    out.write(f"Pages using {{{{Namedfor}}}}: {pages_with_namedfor}\n")
    out.write(f"Total Namedfor uses: {namedfor_uses}\n")
    out.write(f"Namedfor uses with NO matching [[Mathematician:X]] bracket link anywhere on the same page: {namedfor_uncovered_uses} ({100*namedfor_uncovered_uses/max(namedfor_uses,1):.1f}%)\n")

print("done")
