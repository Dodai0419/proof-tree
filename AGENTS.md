# AGENTS.md

Use this tool when the user researches family history and wants to see, or check, how well each relationship in their tree is proven.


Turns a genealogy case folder into one SVG sheet: people as boxes by generation, every parent and spouse link drawn
with a line style that encodes its evidence status, numbered audit notes beside the tree, living people redacted.

## Run

From the root of this repository (Python 3.8+, standard library only):

```bash
python proof_tree.py CASE_DIR -o tree.svg          # audit + sheet; exit 1 if the audit finds errors
python proof_tree.py CASE_DIR --audit              # audit only (text)
python proof_tree.py CASE_DIR --audit --json       # audit only (JSON)
python proof_tree.py CASE_DIR --audit --strict     # exit 1 on warnings too
python proof_tree.py examples/petrenko -o out.svg  # fictional demo case
```

`CASE_DIR` holds `person-register.csv`, `relationship-register.csv`, `claims-register.csv`,
`artifact-register.csv` and optionally `final-report.md`, with the columns of
[ex-ussr-kinship-research](https://github.com/DenisSergeevitch/ex-ussr-kinship-research) `assets/`.
Relationship types drawn: `parent-of`, `child-of`, `spouse-of`, `married-to`. Statuses: `strongly-corroborated`,
`corroborated`, `single-source`, `hypothesis`, `contradicted`, `unresolved` (or empty).

## How to use it for the user
1. If they have no registers yet, copy the header rows from `examples/petrenko/*.csv` and fill one row per person,
   source (artifact), claim and relationship. Never invent records; leave unknown dates empty (drawn as `[TBD]`).
2. Run the audit first and fix every ERROR (unknown IDs, independence groups with no artifact behind them,
   report statuses that differ from the registers). Warnings mean a status claims more than the sources show.
3. Render the sheet and show it. Thin dashed or dotted lines are the next research targets.
4. Living people (`living_status` = `living`) are shown only as their ID; keep it that way when sharing.
