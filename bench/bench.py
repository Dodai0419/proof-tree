"""Time the register audit: upstream audit_evidence.py vs proof_tree.py --audit, same case, same machine.

    python bench/bench.py <path-to-ex-ussr-kinship-research> [runs]
"""
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
upstream = Path(sys.argv[1]) / "scripts" / "audit_evidence.py"
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 20
case = ROOT / "examples" / "sokolov"
cmds = {
    "upstream audit_evidence.py": [sys.executable, "-X", "utf8", str(upstream), "--case-dir", str(case), "--json"],
    "proof_tree.py --audit": [sys.executable, str(ROOT / "proof_tree.py"), str(case), "--audit", "--json"],
    "proof_tree.py (audit + SVG)": [sys.executable, str(ROOT / "proof_tree.py"), str(case), "-o", str(ROOT / "bench" / "_bench.svg")],
}
for name, cmd in cmds.items():
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        subprocess.run(cmd, capture_output=True)
        times.append((time.perf_counter() - t) * 1000)
    print(f"{name:30} median {statistics.median(times):6.1f} ms  (min {min(times):.1f}, {runs} runs)")
(ROOT / "bench" / "_bench.svg").unlink(missing_ok=True)


def code_lines(path, stop=None):
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if stop and line.startswith(stop):
            break
        s = line.strip()
        n += bool(s) and not s.startswith("#")
    return n


print(f"non-blank, non-comment lines: upstream audit {code_lines(upstream)}, "
      f"proof_tree audit {code_lines(ROOT / 'proof_tree.py', '# ---- drawing')}, proof_tree total {code_lines(ROOT / 'proof_tree.py')}")
