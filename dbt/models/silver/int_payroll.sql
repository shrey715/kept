{# Payroll evidence from the deposit account with the latest payroll deposit; drives Kept sizing. #}
select
    x.golden_customer_id,
    arg_max(d.expected_next_payroll_date, d.last_payroll_date) as expected_next_payroll_date,
    arg_max('deposit:' || d.deposit_account_id, d.last_payroll_date) as expected_next_payroll_date_source,
    coalesce(arg_max(d.payroll_frequency_detected, d.last_payroll_date), 'unknown') as payroll_frequency_detected
from {{ ref('deposit_accounts') }} d
join {{ source('identity', 'int_crosswalk') }} x
    on x.source_system = 'deposit' and x.source_key = d.src_customer_ref and x.valid_to is null
where d.expected_next_payroll_date is not null
group by x.golden_customer_id
