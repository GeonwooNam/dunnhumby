-- 목적: 상품 반응 프로필을 고객의 고정 선호상품 가중치와 결합한다.
-- 입력: mart_product_response_profile,
--       customer_axis.work_customer_preference/work_customer_department/
--       work_analysis_customer
-- 출력: mart_customer_product_fit, mart_customer_product_fit_summary,
--       mart_customer_product_strategy_summary
-- 주의: 동일 패널에서 탐색한 상품 반응을 다시 연결한 전략 후보표이며,
--       고객 반응의 독립 검증 또는 인과효과 추정이 아니다.

CREATE OR REPLACE TABLE work_primary_customer_preference_relation AS
SELECT
    p.household_key,
    p.PRODUCT_ID,
    p.home_store_id,
    p.DEPARTMENT,
    p.preference_rank,
    p.preference_weight_top20 AS preference_weight,
    CASE
        WHEN d.is_preferred_department = 1 THEN 'preferred_top3'
        ELSE 'other_purchased'
    END AS department_relation
FROM customer_axis.work_customer_preference AS p
JOIN customer_axis.work_analysis_customer AS a USING (household_key)
JOIN customer_axis.work_customer_department AS d
  ON p.household_key = d.household_key
 AND p.DEPARTMENT = d.DEPARTMENT
WHERE a.is_primary_analysis = 1;

CREATE OR REPLACE TABLE work_customer_product_response_match AS
SELECT
    p.*,
    c.comparison,
    r.eligible_stores,
    r.support_tier,
    r.median_spv_difference,
    r.median_bpr_difference,
    r.positive_spv_store_pct,
    r.positive_bpr_store_pct,
    r.is_repeated_sales_positive,
    r.is_repeated_penetration_positive,
    r.is_repeated_any_positive,
    r.response_type,
    s.min_state_weeks AS home_store_min_state_weeks,
    s.spv_difference AS home_store_spv_difference,
    s.bpr_difference AS home_store_bpr_difference
FROM work_primary_customer_preference_relation AS p
CROSS JOIN (
    VALUES
        ('display_only_vs_none'),
        ('mailer_only_vs_none'),
        ('both_vs_none'),
        ('both_vs_additive')
) AS c(comparison)
LEFT JOIN mart_product_response_profile AS r
  ON p.PRODUCT_ID = r.PRODUCT_ID
 AND c.comparison = r.comparison
LEFT JOIN mart_product_store_response_detail AS s
  ON p.PRODUCT_ID = s.PRODUCT_ID
 AND p.home_store_id = s.STORE_ID
 AND c.comparison = s.comparison
 AND s.min_state_weeks >= 3;

CREATE OR REPLACE TABLE work_customer_department_product_response_match AS
SELECT
    p.household_key,
    p.DEPARTMENT,
    p.PRODUCT_ID,
    p.home_store_id,
    p.department_product_weight AS preference_weight,
    CASE
        WHEN p.is_preferred_department = 1 THEN 'preferred_top3'
        ELSE 'other_purchased'
    END AS department_relation,
    c.comparison,
    r.eligible_stores,
    r.support_tier,
    r.median_spv_difference,
    r.median_bpr_difference,
    r.positive_spv_store_pct,
    r.positive_bpr_store_pct,
    r.is_repeated_sales_positive,
    r.is_repeated_penetration_positive,
    r.is_repeated_any_positive,
    r.response_type,
    s.min_state_weeks AS home_store_min_state_weeks,
    s.spv_difference AS home_store_spv_difference,
    s.bpr_difference AS home_store_bpr_difference
FROM customer_axis.work_customer_department_product AS p
JOIN customer_axis.work_analysis_customer AS a USING (household_key)
CROSS JOIN (
    VALUES
        ('display_only_vs_none'),
        ('mailer_only_vs_none'),
        ('both_vs_none'),
        ('both_vs_additive')
) AS c(comparison)
LEFT JOIN mart_product_response_profile AS r
  ON p.PRODUCT_ID = r.PRODUCT_ID
 AND c.comparison = r.comparison
LEFT JOIN mart_product_store_response_detail AS s
  ON p.PRODUCT_ID = s.PRODUCT_ID
 AND p.home_store_id = s.STORE_ID
 AND c.comparison = s.comparison
 AND s.min_state_weeks >= 3
WHERE a.is_primary_analysis = 1;

CREATE OR REPLACE TABLE mart_customer_product_fit AS
SELECT
    household_key,
    comparison,
    COUNT(*) AS preferred_products,
    SUM(preference_weight) AS total_preference_weight,
    COUNT(*) FILTER (WHERE support_tier IS NOT NULL) AS profiled_products,
    SUM(CASE WHEN support_tier IS NOT NULL THEN preference_weight ELSE 0 END)
        AS profiled_weight,
    COUNT(*) FILTER (WHERE support_tier = 'multi_store_repeated')
        AS multistore_profiled_products,
    SUM(CASE WHEN support_tier = 'multi_store_repeated'
             THEN preference_weight ELSE 0 END) AS multistore_profiled_weight,
    SUM(CASE WHEN is_repeated_sales_positive = 1
             THEN preference_weight ELSE 0 END) AS sales_positive_weight,
    SUM(CASE WHEN is_repeated_penetration_positive = 1
             THEN preference_weight ELSE 0 END) AS penetration_positive_weight,
    SUM(CASE WHEN is_repeated_any_positive = 1
             THEN preference_weight ELSE 0 END) AS any_positive_weight,
    SUM(CASE WHEN is_repeated_sales_positive = 1
              AND is_repeated_penetration_positive = 1
             THEN preference_weight ELSE 0 END) AS joint_positive_weight,
    COUNT(*) FILTER (WHERE home_store_min_state_weeks IS NOT NULL)
        AS home_store_profiled_products,
    SUM(CASE WHEN home_store_min_state_weeks IS NOT NULL
             THEN preference_weight ELSE 0 END) AS home_store_profiled_weight,
    SUM(CASE WHEN home_store_spv_difference > 0
             THEN preference_weight ELSE 0 END) AS home_store_sales_positive_weight,
    SUM(CASE WHEN home_store_bpr_difference > 0
             THEN preference_weight ELSE 0 END)
        AS home_store_penetration_positive_weight,
    SUM(CASE WHEN support_tier = 'multi_store_repeated'
             THEN preference_weight * median_spv_difference ELSE 0 END)
        / NULLIF(SUM(CASE WHEN support_tier = 'multi_store_repeated'
                          THEN preference_weight ELSE 0 END), 0)
        AS weighted_median_spv_difference,
    SUM(CASE WHEN support_tier = 'multi_store_repeated'
             THEN preference_weight * median_bpr_difference ELSE 0 END)
        / NULLIF(SUM(CASE WHEN support_tier = 'multi_store_repeated'
                          THEN preference_weight ELSE 0 END), 0)
        AS weighted_median_bpr_difference
FROM work_customer_product_response_match
GROUP BY 1, 2;

CREATE OR REPLACE TABLE mart_customer_product_fit_summary AS
SELECT
    comparison,
    COUNT(*) AS households,
    AVG(profiled_weight) AS avg_profiled_weight,
    MEDIAN(profiled_weight) AS median_profiled_weight,
    AVG(multistore_profiled_weight) AS avg_multistore_profiled_weight,
    MEDIAN(multistore_profiled_weight) AS median_multistore_profiled_weight,
    AVG(sales_positive_weight) AS avg_sales_positive_weight,
    AVG(penetration_positive_weight) AS avg_penetration_positive_weight,
    AVG(any_positive_weight) AS avg_any_positive_weight,
    AVG(joint_positive_weight) AS avg_joint_positive_weight,
    AVG(home_store_profiled_weight) AS avg_home_store_profiled_weight,
    AVG(home_store_sales_positive_weight)
        AS avg_home_store_sales_positive_weight,
    AVG(home_store_penetration_positive_weight)
        AS avg_home_store_penetration_positive_weight,
    100.0 * AVG(CASE WHEN any_positive_weight > 0 THEN 1.0 ELSE 0.0 END)
        AS households_with_any_positive_product_pct,
    100.0 * AVG(CASE WHEN joint_positive_weight > 0 THEN 1.0 ELSE 0.0 END)
        AS households_with_joint_positive_product_pct
FROM mart_customer_product_fit
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE mart_customer_fit_support_sensitivity AS
WITH thresholds AS (
    SELECT min_weeks FROM range(1, 6) AS t(min_weeks)
), eligible AS (
    SELECT t.min_weeks, d.*
    FROM thresholds AS t
    JOIN mart_product_store_response_detail AS d
      ON d.min_state_weeks >= t.min_weeks
), product_summary AS (
    SELECT
        min_weeks,
        comparison,
        PRODUCT_ID,
        COUNT(*) AS eligible_stores,
        MEDIAN(spv_difference) AS median_spv_difference,
        MEDIAN(bpr_difference) AS median_bpr_difference,
        100.0 * AVG(CASE WHEN is_positive_spv = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_spv_store_pct,
        100.0 * AVG(CASE WHEN is_positive_bpr = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_bpr_store_pct
    FROM eligible
    WHERE comparison IN (
        'display_only_vs_none', 'mailer_only_vs_none', 'both_vs_none'
    )
    GROUP BY 1, 2, 3
), classified AS (
    SELECT
        *,
        CASE
            WHEN eligible_stores >= 3
             AND (
                 (median_spv_difference > 0 AND positive_spv_store_pct >= 60)
                 OR
                 (median_bpr_difference > 0 AND positive_bpr_store_pct >= 60)
             )
            THEN 1 ELSE 0
        END AS is_repeated_any_positive
    FROM product_summary
), primary_preference AS (
    SELECT
        p.household_key,
        p.PRODUCT_ID,
        p.preference_weight_top20 AS preference_weight
    FROM customer_axis.work_customer_preference AS p
    JOIN customer_axis.work_analysis_customer AS a USING (household_key)
    WHERE a.is_primary_analysis = 1
), customer_threshold AS (
    SELECT
        h.household_key,
        t.min_weeks,
        c.comparison,
        SUM(CASE WHEN s.PRODUCT_ID IS NOT NULL
                 THEN p.preference_weight ELSE 0 END) AS profiled_weight,
        SUM(CASE WHEN s.eligible_stores >= 3
                 THEN p.preference_weight ELSE 0 END) AS multistore_profiled_weight,
        SUM(CASE WHEN s.is_repeated_any_positive = 1
                 THEN p.preference_weight ELSE 0 END) AS any_positive_weight
    FROM (SELECT DISTINCT household_key FROM primary_preference) AS h
    CROSS JOIN thresholds AS t
    CROSS JOIN (
        VALUES
            ('display_only_vs_none'),
            ('mailer_only_vs_none'),
            ('both_vs_none')
    ) AS c(comparison)
    JOIN primary_preference AS p USING (household_key)
    LEFT JOIN classified AS s
      ON p.PRODUCT_ID = s.PRODUCT_ID
     AND t.min_weeks = s.min_weeks
     AND c.comparison = s.comparison
    GROUP BY 1, 2, 3
)
SELECT
    min_weeks,
    comparison,
    COUNT(*) AS households,
    AVG(profiled_weight) AS avg_profiled_weight,
    AVG(multistore_profiled_weight) AS avg_multistore_profiled_weight,
    AVG(any_positive_weight) AS avg_any_positive_weight,
    100.0 * AVG(CASE WHEN any_positive_weight > 0 THEN 1.0 ELSE 0.0 END)
        AS households_with_any_positive_product_pct
FROM customer_threshold
GROUP BY 1, 2
ORDER BY 2, 1;

CREATE OR REPLACE TABLE mart_customer_product_strategy_summary AS
WITH household_department AS (
    SELECT
        household_key,
        DEPARTMENT,
        comparison,
        department_relation,
        SUM(preference_weight) AS department_weight,
        SUM(CASE WHEN support_tier IS NOT NULL
                 THEN preference_weight ELSE 0 END) AS profiled_weight,
        SUM(CASE WHEN support_tier = 'multi_store_repeated'
                 THEN preference_weight ELSE 0 END) AS multistore_profiled_weight,
        SUM(CASE WHEN is_repeated_sales_positive = 1
                 THEN preference_weight ELSE 0 END) AS sales_positive_weight,
        SUM(CASE WHEN is_repeated_penetration_positive = 1
                 THEN preference_weight ELSE 0 END) AS penetration_positive_weight,
        SUM(CASE WHEN is_repeated_any_positive = 1
                 THEN preference_weight ELSE 0 END) AS any_positive_weight,
        SUM(CASE WHEN home_store_min_state_weeks IS NOT NULL
                 THEN preference_weight ELSE 0 END) AS home_store_profiled_weight,
        COUNT(*) FILTER (WHERE is_repeated_any_positive = 1)
            AS positive_candidate_products
    FROM work_customer_department_product_response_match
    GROUP BY 1, 2, 3, 4
), normalized AS (
    SELECT
        *,
        profiled_weight / NULLIF(department_weight, 0)
            AS profiled_share_within_department,
        multistore_profiled_weight / NULLIF(department_weight, 0)
            AS multistore_profiled_share_within_department,
        sales_positive_weight / NULLIF(department_weight, 0)
            AS sales_positive_share_within_department,
        penetration_positive_weight / NULLIF(department_weight, 0)
            AS penetration_positive_share_within_department,
        any_positive_weight / NULLIF(department_weight, 0)
            AS any_positive_share_within_department,
        home_store_profiled_weight / NULLIF(department_weight, 0)
            AS home_store_profiled_share_within_department,
        CASE
            WHEN department_relation = 'preferred_top3'
                THEN sales_positive_weight / NULLIF(department_weight, 0)
            ELSE penetration_positive_weight / NULLIF(department_weight, 0)
        END AS strategy_candidate_share
    FROM household_department
)
SELECT
    comparison,
    department_relation,
    CASE
        WHEN department_relation = 'preferred_top3'
            THEN 'home_store_sales_value'
        ELSE 'department_purchase_rate'
    END AS target_kpi,
    COUNT(DISTINCT household_key) AS households,
    COUNT(*) AS household_departments,
    AVG(profiled_share_within_department) AS avg_profiled_share_within_department,
    AVG(multistore_profiled_share_within_department)
        AS avg_multistore_profiled_share_within_department,
    AVG(sales_positive_share_within_department)
        AS avg_sales_positive_share_within_department,
    AVG(penetration_positive_share_within_department)
        AS avg_penetration_positive_share_within_department,
    AVG(any_positive_share_within_department)
        AS avg_any_positive_share_within_department,
    AVG(home_store_profiled_share_within_department)
        AS avg_home_store_profiled_share_within_department,
    AVG(strategy_candidate_share) AS avg_strategy_candidate_share,
    MEDIAN(strategy_candidate_share) AS median_strategy_candidate_share,
    100.0 * AVG(CASE WHEN strategy_candidate_share > 0
                     THEN 1.0 ELSE 0.0 END)
        AS households_with_strategy_candidate_pct,
    AVG(positive_candidate_products) AS avg_positive_candidate_products
FROM normalized
GROUP BY 1, 2, 3
ORDER BY 1, 2;
