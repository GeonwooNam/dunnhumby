-- 목적: 마케팅축 핵심 결과를 재현·검산 가능한 CSV로 내보낸다.

COPY (SELECT * FROM audit_marketing_risk_definition ORDER BY sample_definition)
TO 'marketing_axis_outputs/risk_definition_audit.csv' (FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_marketing_risk_cohort
    WHERE is_stage2_target = 1
    ORDER BY household_key
)
TO 'marketing_axis_outputs/stage2_risk_cohort.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_marketing_reach_funnel ORDER BY step_order)
TO 'marketing_axis_outputs/reach_funnel.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_marketing_campaign_reach_detail ORDER BY START_DAY, CAMPAIGN)
TO 'marketing_axis_outputs/campaign_reach_detail.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM audit_campaign18_baseline_balance ORDER BY campaign18_assigned)
TO 'marketing_axis_outputs/campaign18_baseline_balance.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_campaign18_raw_group ORDER BY metric, campaign18_assigned)
TO 'marketing_axis_outputs/campaign18_raw_group.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_campaign18_raw_difference ORDER BY metric)
TO 'marketing_axis_outputs/campaign18_raw_difference.csv' (FORMAT CSV, HEADER);

COPY (
    SELECT *
    FROM mart_campaign18_stratum_detail
    ORDER BY metric, engagement_stratum, campaign18_assigned
)
TO 'marketing_axis_outputs/campaign18_stratum_detail.csv' (FORMAT CSV, HEADER);

COPY (SELECT * FROM mart_campaign18_adjusted_difference ORDER BY metric)
TO 'marketing_axis_outputs/campaign18_adjusted_difference.csv' (FORMAT CSV, HEADER);

