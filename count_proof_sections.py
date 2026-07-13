"""ProofWiki's Main Page claims '29,781 Proofs'. That's not a page count --
most theorems embed their proof inline under a '== Proof ==' heading rather
than splitting into a '/Proof N' subpage (subpages only appear when there
are multiple alternative proofs). Count heading-level proof sections across
all ns=0 pages to see if it lines up with the dump we have.
"""
import re
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).parent
XML_PATH = HERE / "proofwiki-dump.xml"
NS = "{http://www.mediawiki.org/xml/export-0.11/}"

# ProofWiki convention: "== Proof ==", "== Proof 1 ==", "=== Proof ===", etc.
PROOF_HEADING_RE = re.compile(r"^=+\s*Proof(\s+\d+)?\s*=+\s*$", re.MULTILINE)

total_proof_headings = 0
pages_with_zero_proofs = 0
pages_scanned = 0

context = ET.iterparse(str(XML_PATH), events=("end",))
for event, elem in context:
    if elem.tag == f"{NS}page":
        ns = elem.findtext(f"{NS}ns")
        if ns == "0":
            redirect_elem = elem.find(f"{NS}redirect")
            if redirect_elem is None:
                revisions = elem.findall(f"{NS}revision")
                text = ""
                if revisions:
                    text_elem = revisions[-1].find(f"{NS}text")
                    text = text_elem.text if text_elem is not None and text_elem.text else ""
                pages_scanned += 1
                n = len(PROOF_HEADING_RE.findall(text))
                total_proof_headings += n
                if n == 0:
                    pages_with_zero_proofs += 1
        elem.clear()

print(f"ns=0 non-redirect pages scanned: {pages_scanned}")
print(f"Total '== Proof ==' style headings found: {total_proof_headings}")
print(f"ns=0 pages with zero proof headings (statement-only/def/other): {pages_with_zero_proofs}")
