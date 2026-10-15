"""Layer 4: models and decisioning (Track D). Pipeline order (design §6):

1 rules.hard_stops        cease/insolvency/bankruptcy/deceased -> rule card
2 rules.permission_gate   consent, local hours, 7-day cap
3 rules.hardship_override hardship -> protective actions only (outside the model)
4 uplift                  LightGBM T-learner on paid_14d, Qini
5 sizing                  promise due on payday, within spare cash
6 ranking                 uplift x balance - cost - burden, within capacity
7 explain                 TreeSHAP top 3 -> fixed sentences; no LLM text
then tiers -> human approval -> release (recheck) -> execute and log
"""
