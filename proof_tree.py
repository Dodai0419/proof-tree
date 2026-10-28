#!/usr/bin/env python3
"""proof-tree: draw a family tree where every line shows how well it is proven.

    python proof_tree.py examples/petrenko -o docs/petrenko.svg
    python proof_tree.py examples/petrenko --audit [--json] [--strict]

Input is a case folder in the ex-ussr-kinship-research register format
(person-, artifact-, claims- and relationship-register.csv, optional final-report.md).
The audit is a port of that project's scripts/audit_evidence.py (same checks, English text).
The sheet follows the dimensional-drawing house rules: monochrome, statuses told apart
by line weight and dashes, unknowns shown as [TBD], living people redacted.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import textwrap
from collections import Counter
from html import escape
from pathlib import Path

REQUIRED = {
    "artifact-register.csv": {"artifact_id", "independence_group", "directness", "originality", "related_claim_ids", "status"},
    "claims-register.csv": {"claim_id", "artifact_ids", "supporting_independence_groups", "contradicting_artifact_ids", "status", "rationale"},
    "relationship-register.csv": {"relationship_id", "person_a_id", "person_b_id", "claim_ids", "supporting_artifact_ids",
                                  "contradicting_artifact_ids", "independence_groups", "status", "rationale"},
    "person-register.csv": {"person_id"},
}
CORROBORATED = {"corroborated", "strongly-corroborated"}
STATUSES = {"", "hypothesis", "single-source", "corroborated", "strongly-corroborated", "contradicted", "unresolved"}
OPEN = ("hypothesis", "single-source", "unresolved", "contradicted", "empty")
DIRECT_COPIES = {"original", "image-of-original", "official-extract"}
UNKNOWN_PROVENANCE = {"", "unknown", "неизвестно", "не установлено"}
REPORT_MARKERS = ("[неразборчиво]", "[предположительно")  # upstream report markers: "illegible", "presumably"
HEADING = re.compile(r"^#{2,6}\s")


def ids(value):
    return [p.strip() for p in (value or "").replace(",", ";").split(";") if p.strip()]


def read_case(case: Path):
    data, errors = {}, []
    for name, need in REQUIRED.items():
        path = case / name
        if not path.is_file():
            errors.append(f"Missing required file: {name}")
            data[name] = []
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                errors.append(f"{name}: no header row")
                data[name] = []
                continue
            if need - set(reader.fieldnames):
                errors.append(f"{name}: missing columns: {', '.join(sorted(need - set(reader.fieldnames)))}")
            data[name] = [{k: (v or "").strip() for k, v in row.items()} for row in reader]
    return data, errors


def groups_of(artifact_ids, arts):
    return {arts[a]["independence_group"].strip().casefold() for a in artifact_ids
            if a in arts and arts[a].get("independence_group", "").strip()}


def has_direct(artifact_ids, arts):
    return any(r.get("directness", "").casefold() == "direct" and r.get("originality", "").casefold() in DIRECT_COPIES
               and r.get("provenance_level", "").strip().casefold() not in UNKNOWN_PROVENANCE
               and (r.get("source_url_or_path", "").strip() or r.get("archival_reference", "").strip())
               for r in (arts.get(a, {}) for a in artifact_ids))


def corroboration(rid, status, groups, rationale, contradicting, backing, arts, w):
    if status in CORROBORATED:
        if len(groups) < 2:
            w.append(f"{rid}: status {status}, but independent groups found: {len(groups)}")
        if not rationale:
            w.append(f"{rid}: {status} without a rationale")
        if contradicting:
            w.append(f"{rid}: status {status}, but contradicting artifacts are listed; explain whether the conflict is resolved")
    if status == "strongly-corroborated" and not has_direct(backing, arts):
        w.append(f"{rid}: strongly-corroborated without one direct record with provenance and a locator of the original")


def audit_report(text, known, statuses):
    errors = []
    for prefix, have in sorted(known.items()):
        for cited in sorted(set(re.findall(rf"(?<![\w-]){re.escape(prefix)}\d+(?!\w)", text)) - have):
            errors.append(f"final-report.md: cites {cited}, which is not in the registers")
    valid, section, checked = STATUSES - {""}, "", False
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if HEADING.match(s):
            section, checked = next((w for w in re.findall(r"[\w-]+", s) if w in statuses), ""), False
        elif s.startswith("|"):
            cells = [c.strip().strip("`") for c in s.strip("|").split("|")]
            found = [c for c in cells[1:] if c in valid]
            if cells[0] in statuses and found and statuses[cells[0]] not in found:
                errors.append(f"final-report.md:{n}: {cells[0]} is {found[0]} in the report, {statuses[cells[0]] or 'empty'} in the registers")
        elif section and not checked and (m := re.match(r"^\*\*[^*]+:\*\*\s*`?([\w-]+)`?", s)) and m.group(1) in valid:
            checked = True
            if m.group(1) != statuses[section]:
                errors.append(f"final-report.md:{n}: {section} is {m.group(1)} in the report, {statuses[section] or 'empty'} in the registers")
    return errors, {name: text.count(k) for name, k in zip(("illegible", "presumably"), REPORT_MARKERS)}


def audit(case: Path, data=None, read_errors=()):
    if data is None:
        data, read_errors = read_case(case)
    errors, w = list(read_errors), []
    arts_l, claims_l, rels, persons = (data[k] for k in REQUIRED)
    for rows, field, label in ((arts_l, "artifact_id", "artifact"), (claims_l, "claim_id", "claim"),
                               (rels, "relationship_id", "relationship"), (persons, "person_id", "person")):
        dup = sorted(k for k, c in Counter(r.get(field, "") for r in rows if r.get(field, "")).items() if c > 1)
        if dup:
            errors.append(f"Duplicate {label} IDs: {', '.join(dup)}")
        w += [f"{field}: empty ID on line {i}" for i, r in enumerate(rows, 2) if not r.get(field, "")]
    arts = {r["artifact_id"]: r for r in arts_l if r.get("artifact_id")}
    claims = {r["claim_id"]: r for r in claims_l if r.get("claim_id")}
    pids = {r["person_id"] for r in persons if r.get("person_id")}

    for aid, r in arts.items():
        if not r.get("independence_group", "").strip():
            w.append(f"{aid}: no independence_group")
        errors += [f"{aid}: unknown person_id {p}" for p in ids(r.get("person_ids")) if p not in pids]
        errors += [f"{aid}: unknown related claim_id {c}" for c in ids(r.get("related_claim_ids")) if c not in claims]

    for cid, r in claims.items():
        st = r.get("status", "")
        if st not in STATUSES:
            w.append(f"{cid}: unknown status {st!r}")
        errors += [f"{cid}: unknown subject_person_id {p}" for p in ids(r.get("subject_person_ids")) if p not in pids]
        ref, contra = ids(r.get("artifact_ids")), ids(r.get("contradicting_artifact_ids"))
        errors += [f"{cid}: unknown artifact_id {a}" for a in ref + contra if a not in arts]
        groups = groups_of(ref, arts)
        errors += [f"{cid}: independence_group {g} is declared, but none of its artifact_ids belongs to it"
                   for g in sorted(set(ids(r.get("supporting_independence_groups")))) if g.casefold() not in groups]
        if st in CORROBORATED and len(groups) < 2:
            w.append(f"{cid}: status {st}, but independent groups found: {len(groups)}")
        if st in CORROBORATED and not r.get("rationale"):
            w.append(f"{cid}: {st} without a rationale")
        if st in CORROBORATED and contra:
            w.append(f"{cid}: status {st}, but contradicting artifacts are listed; explain whether the conflict is resolved")
        if st == "single-source" and len(groups) > 1:
            w.append(f"{cid}: several independent groups but still single-source; check for a conflict or a gap")
        if st == "strongly-corroborated" and not has_direct(ref, arts):
            w.append(f"{cid}: strongly-corroborated without one direct record with provenance and a locator of the original")

    for r in rels:
        rid, st = r.get("relationship_id", "<no ID>"), r.get("status", "")
        if st not in STATUSES:
            w.append(f"{rid}: unknown status {st!r}")
        errors += [f"{rid}: unknown {f} {r[f]}" for f in ("person_a_id", "person_b_id") if r.get(f) and r[f] not in pids]
        errors += [f"{rid}: unknown claim_id {c}" for c in ids(r.get("claim_ids")) if c not in claims]
        errors += [f"{rid}: unknown artifact_id {a}" for a in ids(r.get("supporting_artifact_ids")) + ids(r.get("contradicting_artifact_ids")) if a not in arts]
        # A group counts only when an artifact stands behind it, directly or through claim_ids.
        backing, contra = ids(r.get("supporting_artifact_ids")), set(ids(r.get("contradicting_artifact_ids")))
        for c in ids(r.get("claim_ids")):
            if c in claims:
                backing += ids(claims[c].get("artifact_ids"))
                contra.update(ids(claims[c].get("contradicting_artifact_ids")))
        groups = groups_of(backing, arts)
        errors += [f"{rid}: independence_group {g} is declared, but no artifact of the relationship belongs to it"
                   for g in sorted(set(ids(r.get("independence_groups")))) if g.casefold() not in groups]
        corroboration(rid, st, groups, r.get("rationale"), contra, backing, arts, w)

    markers = {}
    if (case / "final-report.md").is_file():
        known = {p: set() for p in ("A-", "C-", "R-", "P-")}
        for rows, field in ((arts_l, "artifact_id"), (claims_l, "claim_id"), (rels, "relationship_id"), (persons, "person_id")):
            for r in rows:
                v = r.get(field, "")
                if v and v.rstrip("0123456789") != v:
                    known.setdefault(v.rstrip("0123456789"), set()).add(v)
        statuses = {c: r.get("status", "") for c, r in claims.items()}
        statuses.update((r["relationship_id"], r.get("status", "")) for r in rels if r.get("relationship_id"))
        rep_err, markers = audit_report((case / "final-report.md").read_text(encoding="utf-8-sig"), known, statuses)
        errors += rep_err
    summary = {"claims_by_status": dict(Counter(r.get("status", "") or "empty" for r in claims_l)),
               "relationships_by_status": dict(Counter(r.get("status", "") or "empty" for r in rels)),
               "report_markers": markers}
    counts = {"persons": len(persons), "artifacts": len(arts_l), "claims": len(claims_l), "relationships": len(rels)}
    return {"case_dir": str(case), "counts": counts, "summary": summary, "errors": errors, "warnings": w}


# ---- drawing ----------------------------------------------------------------------------------
# status -> (stroke width, dash pattern, short label); weights and dashes only, never colour.
STYLE = {
    "strongly-corroborated": (2.8, "", "STRONG"),
    "corroborated": (1.7, "", "CORROBORATED"),
    "single-source": (1.1, "7 4", "SINGLE SOURCE"),
    "hypothesis": (0.9, "1.5 3.5", "HYPOTHESIS"),
    "contradicted": (1.4, "", "CONTRADICTED"),
    "": (0.8, "14 3 3 3", "[TBD]"),
}
BW, BH, GAPX, ROWH, PAD = 200, 64, 90, 150, 48
FONT = "Arimo,'Helvetica Neue',Helvetica,Arial,sans-serif"
CSS = (f"text{{font-family:{FONT};fill:#111}}.u{{text-transform:uppercase;letter-spacing:.07em}}"
       ".lbl{font-size:9.5px;fill:#7a7a7a}.box{fill:#fff;stroke:#111;stroke-width:1.4}.living{fill:#f3f3f3;stroke:#7a7a7a;"
       "stroke-width:1;stroke-dasharray:4 3}.tag{font-size:9px;fill:#444;paint-order:stroke;stroke:#fff;stroke-width:4px}")


def style(status):
    return STYLE.get(status if status in STYLE else "", STYLE[""])


def layout(persons, rels):
    order = [p["person_id"] for p in persons if p.get("person_id")]
    parents = [(r["person_a_id"], r["person_b_id"]) for r in rels if r.get("relationship_type") == "parent-of"]
    parents += [(r["person_b_id"], r["person_a_id"]) for r in rels if r.get("relationship_type") == "child-of"]
    spouses = [(r["person_a_id"], r["person_b_id"]) for r in rels if r.get("relationship_type") in ("spouse-of", "married-to")]
    parents = [(a, b) for a, b in parents if a in order and b in order]
    spouses = [(a, b) for a, b in spouses if a in order and b in order]
    gen = dict.fromkeys(order, 0)
    for _ in range(len(order) + 1):  # longest-path generations; bounded so a cycle cannot hang
        changed = False
        for a, b in parents:
            if gen[b] < gen[a] + 1:
                gen[b], changed = gen[a] + 1, True
        for a, b in spouses:
            if gen[a] != gen[b]:
                gen[a] = gen[b] = max(gen[a], gen[b]); changed = True
        if not changed:
            break
    pos, rows = {}, {}
    for p in order:
        rows.setdefault(gen[p], []).append(p)
    width = max(len(r) for r in rows.values()) * (BW + GAPX) - GAPX if rows else BW
    for g in sorted(rows):
        row = rows[g]
        if g:  # children sit under the mean x of their parents
            key = {p: sum(pos[a][0] for a, b in parents if b == p and a in pos) /
                   max(1, sum(1 for a, b in parents if b == p and a in pos)) for p in row}
            row.sort(key=lambda p: key[p] if any(b == p for _, b in parents) else 1e9)
        for a, b in spouses:  # keep couples side by side
            if a in row and b in row:
                row.remove(b); row.insert(row.index(a) + 1, b)
        x0 = (width - (len(row) * (BW + GAPX) - GAPX)) / 2
        for i, p in enumerate(row):
            pos[p] = (x0 + i * (BW + GAPX), g * ROWH)
    return pos, width, (max(gen.values()) + 1 if gen else 1) * ROWH - (ROWH - BH)


def edge_path(kind, a, b, k, j=0, n=1):
    """k: edge index (spreads a parent's drops), j of n: this edge among the child's parents."""
    (ax, ay), (bx, by) = a, b
    if kind == "spouse":
        y = ay + BH / 2
        x1, x2 = (ax + BW, bx) if ax < bx else (bx + BW, ax)
        return f"M{x1:.1f} {y:.1f}H{x2:.1f}", ((x1 + x2) / 2, y - 7)
    mid = ay + BH + (by - ay - BH) / 2 + (j - (n - 1) / 2) * 12
    sx, ex = ax + BW / 2 + (k % 3 - 1) * 10, bx + BW / 2 + (j - (n - 1) / 2) * 16
    return f"M{sx:.1f} {ay + BH:.1f}V{mid:.1f}H{ex:.1f}V{by:.1f}", (ex, by - 10 - 13 * (n - 1 - j))


def render(case: Path, result=None):
    data, read_errors = read_case(case)
    result = result or audit(case, data, read_errors)
    persons, rels = data["person-register.csv"], data["relationship-register.csv"]
    pos, w, h = layout(persons, rels)
    notes = result["errors"] + result["warnings"]
    flagged = {}
    for i, n in enumerate(notes, 1):
        flagged.setdefault(n.split(":")[0], i)
    ox, oy = PAD + 250, PAD + 96  # left column holds the legend and notes
    note_lines = sum(len(textwrap.wrap(n, 43)) + 0.3 for n in notes)
    W, H = max(ox + w + PAD, 1100), max(oy + h + PAD + 30, oy + 230 + 15 * note_lines + PAD)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}">',
           f"<style>{CSS}</style>", f'<rect width="{W:.0f}" height="{H:.0f}" fill="#fff"/>',
           f'<rect x="12" y="12" width="{W - 24:.0f}" height="{H - 24:.0f}" fill="none" stroke="#111" stroke-width="1.2"/>']
    rs = result["summary"]["relationships_by_status"]
    proven = sum(rs.get(s, 0) for s in CORROBORATED)
    title = f"KINSHIP SHEET · {case.resolve().name.upper()}"
    out.append(f'<text x="{PAD}" y="{PAD + 10}" class="u" font-size="26" font-weight="700">{escape(title)}</text>')
    figs = [("P", "persons", result["counts"]["persons"]), ("R", "relationships", result["counts"]["relationships"]),
            ("A", "artifacts", result["counts"]["artifacts"]), ("R+", "proven links", f"{proven}/{len(rels)}"),
            ("N", "audit notes", len(notes))]
    for i, (var, label, val) in enumerate(figs):
        x = PAD + i * 150
        out.append(f'<text x="{x}" y="{PAD + 38}" class="u lbl">{var} · {label}</text>'
                   f'<text x="{x}" y="{PAD + 60}" font-size="20">{escape(str(val))}</text>')
    out.append(f'<line x1="{PAD}" y1="{PAD + 74}" x2="{W - PAD}" y2="{PAD + 74}" stroke="#d0d0d0"/>')
    # legend
    ly = oy + 10
    out.append(f'<text x="{PAD}" y="{ly}" class="u" font-size="11.5" font-weight="700">Line = evidence</text>')
    for i, st in enumerate(STYLE):
        sw, dash, label = STYLE[st]
        y = ly + 24 + i * 22
        out.append(f'<path d="M{PAD} {y}h56" stroke="#111" stroke-width="{sw}" stroke-dasharray="{dash}" fill="none"/>')
        if st == "contradicted":
            out.append(f'<path d="M{PAD + 24} {y - 5}l8 10M{PAD + 32} {y - 5}l-8 10" stroke="#111" stroke-width="1.2"/>')
        out.append(f'<text x="{PAD + 66}" y="{y + 3.5}" class="u" font-size="10">{label}</text>')
    ny = ly + 24 + len(STYLE) * 22 + 18
    out.append(f'<text x="{PAD}" y="{ny}" class="u" font-size="11.5" font-weight="700">Audit notes</text>')
    if not notes:
        out.append(f'<text x="{PAD}" y="{ny + 20}" font-size="10.5">No errors or warnings.</text>')
    line = ny + 4
    for i, n in enumerate(notes, 1):
        for part in textwrap.wrap(f"{i}. {n}", 46, subsequent_indent="   "):
            line += 15
            out.append(f'<text x="{PAD}" y="{line}" font-size="10" xml:space="preserve">{escape(part)}</text>')
        line += 4
    # edges first, boxes on top
    incoming = {}
    for r in rels:
        child = r.get("person_a_id") if r.get("relationship_type") == "child-of" else r.get("person_b_id")
        if r.get("relationship_type") in ("parent-of", "child-of"):
            incoming.setdefault(child, []).append(r.get("relationship_id"))
    for k, r in enumerate(rels):
        kind = {"parent-of": "parent", "child-of": "child", "spouse-of": "spouse", "married-to": "spouse"}.get(r.get("relationship_type"))
        a, b = r.get("person_a_id"), r.get("person_b_id")
        if kind is None or a not in pos or b not in pos:
            continue
        if kind == "child":
            a, b = b, a
        pa, pb = (ox + pos[a][0], oy + pos[a][1]), (ox + pos[b][0], oy + pos[b][1])
        mine = incoming.get(b, []) if kind != "spouse" else []
        j = mine.index(r.get("relationship_id")) if r.get("relationship_id") in mine else 0
        d, (tx, ty) = edge_path(kind, pa, pb, k, j, max(1, len(mine)))
        sw, dash, label = style(r.get("status", ""))
        out.append(f'<path d="{d}" fill="none" stroke="#111" stroke-width="{sw}" stroke-dasharray="{dash}"/>')
        if r.get("status") == "contradicted":
            out.append(f'<path d="M{tx - 4} {ty - 12}l8 10M{tx + 4} {ty - 12}l-8 10" stroke="#111" stroke-width="1.4"/>')
        if kind == "spouse":  # the gap between partners is short: ID only, the line style carries the status
            out.append(f'<text x="{tx}" y="{ty}" class="u tag" text-anchor="middle">{escape(r.get("relationship_id", ""))}</text>')
        else:
            out.append(f'<text x="{tx + 6}" y="{ty}" class="u tag">{escape(r.get("relationship_id", "") + " · " + label)}</text>')
        if r.get("relationship_id") in flagged:
            cx, cy = (tx, ty - 16) if kind == "spouse" else (tx - 10, ty - 3)
            out.append(f'<circle cx="{cx}" cy="{cy}" r="7" fill="#fff" stroke="#111" stroke-width=".9"/>'
                       f'<text x="{cx}" y="{cy + 3}" font-size="9" text-anchor="middle">{flagged[r["relationship_id"]]}</text>')
    for p in persons:
        pid = p.get("person_id")
        if pid not in pos:
            continue
        x, y = ox + pos[pid][0], oy + pos[pid][1]
        living = p.get("living_status", "").casefold() == "living"
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{BW}" height="{BH}" rx="6" class="{"living" if living else "box"}"/>')
        name = "LIVING" if living else p.get("preferred_label") or "[TBD]"
        name = name if len(name) <= 27 else name[:26] + "…"
        b, dd = p.get("birth_estimate") or "[TBD]", p.get("death_estimate") or "[TBD]"
        out.append(f'<text x="{x + 10:.1f}" y="{y + 16:.1f}" class="u lbl">{escape(pid)}'
                   f'{" · " + escape(p.get("candidate_status", "").upper()) if p.get("candidate_status") == "candidate" else ""}</text>')
        out.append(f'<text x="{x + 10:.1f}" y="{y + 35:.1f}" font-size="12.5" font-weight="600">{escape(name)}</text>')
        sub = "details withheld" if living else f"b. {b}   d. {dd}"
        out.append(f'<text x="{x + 10:.1f}" y="{y + 53:.1f}" font-size="10.5" fill="#444" xml:space="preserve">{escape(sub)}</text>')
    out.append(f'<text x="{W - PAD}" y="{H - 24}" class="u lbl" text-anchor="end">proof-tree · registers: ex-ussr-kinship-research format · '
               f'style: dimensional-drawing</text></svg>')
    return "\n".join(out)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to the ANSI code page
    ap = argparse.ArgumentParser(description="Draw an evidence-graded family tree from kinship registers.")
    ap.add_argument("case_dir")
    ap.add_argument("-o", "--out", help="SVG path (default: <case_dir>/proof-tree.svg)")
    ap.add_argument("--audit", action="store_true", help="only run the register audit")
    ap.add_argument("--json", action="store_true", help="print the audit as JSON")
    ap.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    a = ap.parse_args(argv)
    case = Path(a.case_dir).expanduser().resolve()
    if not case.is_dir():
        print(f"Error: case folder not found: {case}", file=sys.stderr)
        return 2
    result = audit(case)
    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        c, s = result["counts"], result["summary"]
        print(f"Case: {case}\nRecords: persons={c['persons']}, artifacts={c['artifacts']}, claims={c['claims']}, relationships={c['relationships']}")
        for label, key in (("claims", "claims_by_status"), ("relationships", "relationships_by_status")):
            cnt = s[key]
            print(f"- {label}: {', '.join(f'{k}={cnt[k]}' for k in sorted(cnt)) or 'none'}; not corroborated: {sum(cnt.get(k, 0) for k in OPEN)}")
        for head, items in (("ERRORS", result["errors"]), ("WARNINGS", result["warnings"])):
            if items:
                print(f"\n{head}:\n" + "\n".join(f"- {i}" for i in items))
    if not a.audit:
        out = Path(a.out) if a.out else case / "proof-tree.svg"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(case, result), encoding="utf-8")
        print(f"\nwrote {out}")
    return 1 if result["errors"] or (a.strict and result["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
