"""Quick sanity check: count pages per namespace in the dump, and count
how many ns=0 pages look like proof subpages (title contains '/Proof')."""
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
XML_PATH = HERE / "proofwiki-dump.xml"
NS = "{http://www.mediawiki.org/xml/export-0.11/}"

ns_counts = Counter()
proof_subpage_count = 0
redirect_count = 0
theorem_main_count = 0  # ns=0 pages without '/Proof' in title

context = ET.iterparse(str(XML_PATH), events=("end",))
n = 0
for event, elem in context:
    if elem.tag == f"{NS}page":
        n += 1
        ns = elem.findtext(f"{NS}ns")
        title = elem.findtext(f"{NS}title") or ""
        redirect_elem = elem.find(f"{NS}redirect")
        ns_counts[ns] += 1
        if ns == "0":
            if redirect_elem is not None:
                redirect_count += 1
            elif "/Proof" in title:
                proof_subpage_count += 1
            else:
                theorem_main_count += 1
        elem.clear()

print(f"Total pages: {n}")
print("Pages per namespace:")
for ns, c in sorted(ns_counts.items(), key=lambda x: -x[1]):
    print(f"  ns={ns}: {c}")
print()
print(f"ns=0 redirects: {redirect_count}")
print(f"ns=0 titles containing '/Proof': {proof_subpage_count}")
print(f"ns=0 other (theorem statements, etc.): {theorem_main_count}")
