"""kept.hardship.combine as a DuckDB table macro, so gold can combine the hardship observations of
a million customers in SQL. tests/data/test_hardship_sql.py checks it against the Python `combine`
on random observations: change the rules there first (Track C owns them), then here.

    select * from kept_combine_hardship('silver.int_hardship_observations')

The table needs: golden_customer_id, source, signal, observed_at, confirmed_by, cleared_by.
Registered on every dbt connection by kept.data.dbt_udfs.
"""

from __future__ import annotations

import duckdb

COMBINE_MACRO = """
create or replace macro kept_combine_hardship(obs_table) as table
with obs as (select * from query_table(obs_table)),
cleared as (  -- only an observation with cleared_by clears, and only those at or before it
    select golden_customer_id, max(observed_at) as cleared_at from obs
    where cleared_by is not null group by golden_customer_id
),
live as (
    select o.*,
           -- CONFIRMED needs a person or a programme (combine._confirms)
           case when o.confirmed_by is not null
                     or (o.source in ('agent', 'account_programme') and o.signal = 'clear')
                then 2 else 1 end as rnk,
           -- HardshipSource declaration order breaks same-time ties
           case o.source when 'agent' then 0 when 'customer_form' then 1 when 'account_programme' then 2
                         when 'model' then 3 when 'llm' then 4 else 5 end as ord
    from obs o left join cleared c using (golden_customer_id)
    where o.signal <> 'none' and (c.cleared_at is null or o.observed_at > c.cleared_at)
)
select golden_customer_id,
       case when max(rnk) = 2 then 'confirmed' else 'possible' end as hardship_status,
       -- the source of the observation that set the final status: highest rank, latest, lowest order
       arg_max(source, struct_pack(rnk := rnk, at := observed_at, ord := -ord)) as hardship_source
from live group by golden_customer_id
"""


def register(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(COMBINE_MACRO)
