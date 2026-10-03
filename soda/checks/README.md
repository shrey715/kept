# Soda checks (Track A)

Generated, not hand-written: `kept.data.quality.generate_soda_checks(contract)` turns the
quality rules Q1-Q5 in `contracts/c360_customer.odcs.yaml` into SodaCL here. Regenerate on
every contract change; CI fails if the committed checks differ from the generated ones.
