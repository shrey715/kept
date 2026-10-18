# Ranking promise asks by their own value

Written by `scripts/promise_ranking_compare.py` from two scorings of the same cases at the same time, with and without `kept score --rank-promises`.

## What it does

Today a call that can carry a sized ask becomes a promise request or a payment plan, which score like the call (they borrow its model). With the switch on, an ask is valued as **P(right party reached at the slot) x P(promise made | reached) x P(kept | promise)**, the three pieces coming from the best-hour model (or the overall reach rate), the observed rate of promises on reached outbound calls over the 60 days before the promise model's cutoff, and the promise model for this sizing. `ranking.score_actions` takes it through `p_kept_given_promise`.

## What it changes

96,000 cards. Promise requests and payment plans: 241 without the switch, 0 with it. Cards that change action: **241** (0.3%).

| Action without the switch | Action with it | Cards |
|---|---|---:|
| payment plan | call | 220 |
| promise request | call | 21 |

## Why it is off

Nothing offline can say whether the new values are better. The bank never randomised, or even recorded, a promise ask as an action: its calls are one treatment, and a promise made or kept is an outcome of the call, so conditioning on it (the calls that ended in a promise) would compare customers, not asks. The doubly robust comparison of promise asks against calls on the clean outcome (`causal.policy_value`) needs an ask arm with overlap; there is none. The chain also counts only the payments that come through a kept promise, while the call it replaces is paid through any route, so it can only rank an ask below the call. Valued that way, asks lose to plain calls wherever they would have been proposed; whether that is right depends on how much an ask adds to a call, which is exactly what is unmeasured. A pilot cell (asks on half of the calls that can carry one) would measure it.

Default: off (`--rank-promises` or `KEPT_RANK_PROMISES=1`). Raw counts: `{"changed": 241, "cards": 96000}`.
