import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import proof_tree  # noqa: E402

EXAMPLES = ROOT / "examples"
UPSTREAM = json.loads((ROOT / "tests" / "fixtures" / "upstream_audit.json").read_text(encoding="utf-8"))["cases"]


class AuditMatchesUpstream(unittest.TestCase):
    """Same findings, in the same order, as ex-ussr-kinship-research audit_evidence.py."""

    def test_each_case(self):
        for case, want in UPSTREAM.items():
            with self.subTest(case=case):
                got = proof_tree.audit(EXAMPLES / case)
                self.assertEqual([m.split(":")[0] for m in got["errors"]], want["error_ids"])
                self.assertEqual([m.split(":")[0] for m in got["warnings"]], want["warning_ids"])
                self.assertEqual(got["counts"], want["counts"])
                self.assertEqual(got["summary"]["claims_by_status"], want["claims_by_status"])
                self.assertEqual(got["summary"]["relationships_by_status"], want["relationships_by_status"])
                self.assertEqual(list(got["summary"]["report_markers"].values()), want["report_markers"])


class AuditRules(unittest.TestCase):
    def case(self, rel_rows, art_group="g1"):
        tmp = Path(tempfile.mkdtemp())
        head = {name: (EXAMPLES / "petrenko" / name).read_text(encoding="utf-8").splitlines()[0] for name in proof_tree.REQUIRED}
        rows = {
            "person-register.csv": ["P-0001" + "," * 15, "P-0002" + "," * 15],
            "artifact-register.csv": [f"A-0001,,t,url,,,,,,,P-0001,,,archive,direct,image-of-original,{art_group},clear,,,,,"],
            "claims-register.csv": [],
            "relationship-register.csv": rel_rows,
        }
        for name, lines in rows.items():
            (tmp / name).write_text("\n".join([head[name], *lines]) + "\n", encoding="utf-8")
        return proof_tree.audit(tmp)

    def test_declared_group_needs_an_artifact(self):
        r = self.case(["R-0001,P-0001,parent-of,P-0002,biological,,A-0001,,g1;g2,single-source,low,x"])
        self.assertEqual(r["errors"], ["R-0001: independence_group g2 is declared, but no artifact of the relationship belongs to it"])

    def test_corroborated_needs_two_groups(self):
        r = self.case(["R-0001,P-0001,parent-of,P-0002,biological,,A-0001,,g1,corroborated,high,x"])
        self.assertIn("R-0001: status corroborated, but independent groups found: 1", r["warnings"])

    def test_unknown_person(self):
        r = self.case(["R-0001,P-0001,parent-of,P-0404,biological,,A-0001,,g1,single-source,low,x"])
        self.assertIn("R-0001: unknown person_b_id P-0404", r["errors"])


class Sheet(unittest.TestCase):
    def setUp(self):
        self.svg = proof_tree.render(EXAMPLES / "petrenko")
        self.tree = ET.fromstring(self.svg)

    def test_every_drawable_relationship_is_labelled(self):
        for rid in (f"R-{i:04d}" for i in range(1, 11)):
            self.assertIn(rid, self.svg)

    def test_monochrome(self):
        for colour in set(re.findall(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", self.svg)):
            full = colour if len(colour) == 6 else "".join(c * 2 for c in colour)
            self.assertTrue(full[0:2] == full[2:4] == full[4:6], f"#{colour} is not a grey")

    def test_status_is_line_weight_not_colour(self):
        widths = {float(p.get("stroke-width")) for p in self.tree.iter("{http://www.w3.org/2000/svg}path") if p.get("stroke-width")}
        self.assertGreaterEqual(len(widths), 5)

    def test_living_people_are_redacted_and_unknowns_are_tbd(self):
        self.assertIn("details withheld", self.svg)
        self.assertNotIn("Living descendant", self.svg)
        self.assertIn("d. [TBD]", self.svg)

    def test_cycle_does_not_hang(self):
        persons = [{"person_id": "P-1"}, {"person_id": "P-2"}]
        rels = [{"relationship_type": "parent-of", "person_a_id": "P-1", "person_b_id": "P-2"},
                {"relationship_type": "parent-of", "person_a_id": "P-2", "person_b_id": "P-1"}]
        pos, _, _ = proof_tree.layout(persons, rels)
        self.assertEqual(set(pos), {"P-1", "P-2"})


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        return subprocess.run([sys.executable, str(ROOT / "proof_tree.py"), *args], capture_output=True, env=env, timeout=60)

    def test_writes_svg_and_exit_codes_match_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            for case, want in UPSTREAM.items():
                out = Path(tmp) / f"{case}.svg"
                r = self.run_cli(str(EXAMPLES / case), "-o", str(out))
                self.assertEqual(r.returncode, want["exit"], r.stderr.decode("utf-8", "replace"))
                r.stdout.decode("utf-8")  # UTF-8 even when the console code page is not
                ET.parse(out)

    def test_strict_fails_on_warnings(self):
        self.assertEqual(self.run_cli(str(EXAMPLES / "petrenko"), "--audit", "--strict").returncode, 1)


if __name__ == "__main__":
    unittest.main()
