# silver (Track A)

One model per cleaned source table. Rules (reference implementation and tests in
`src/kept/data/clean.py` and `src/kept/data/traps.py`):

- names, mixed DOB formats, phones (E.164), postal codes
- latest snapshot per account; card `dpd` not `cycles_delinquent`; bureau percentiles within scale
- rows that can't be parsed go to `quarantine.<table>` with a reason
