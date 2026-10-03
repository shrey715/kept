{# hardship_status and hardship_source per golden ID: kept.hardship.combine in SQL over the observations. #}
{# Only customers with a status appear; gold fills the rest with 'none'. #}
-- depends_on: {{ ref('int_hardship_observations') }}
select * from kept_combine_hardship('silver.int_hardship_observations')
