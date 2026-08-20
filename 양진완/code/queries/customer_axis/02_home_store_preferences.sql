-- 목적: 홈스토어 프로모션 로그로 측정 가능한 반복구매 선호상품과 주력 부문을 만든다.
-- 입력: 01 단계 고객·홈스토어, source.causal_data, source.product
-- 출력: work_customer_preference, work_analysis_customer, 부문 상품 가중치와 감사표

CREATE OR REPLACE TABLE work_baseline_product AS
SELECT
    t.household_key,
    t.PRODUCT_ID,
    COUNT(DISTINCT t.BASKET_ID) AS baseline_product_baskets,
    SUM(t.SALES_VALUE) AS baseline_product_sales
FROM work_customer_transaction AS t
JOIN work_baseline_customer AS c USING (household_key)
WHERE t.WEEK_NO BETWEEN 1 AND 26
  AND c.is_candidate = 1
GROUP BY 1, 2;

CREATE OR REPLACE TABLE work_causal_product AS
SELECT DISTINCT PRODUCT_ID
FROM source.causal_data;

CREATE OR REPLACE TABLE work_relevant_product_store AS
SELECT DISTINCT
    b.PRODUCT_ID,
    c.home_store_id AS STORE_ID
FROM work_baseline_product AS b
JOIN work_baseline_customer AS c USING (household_key)
WHERE b.baseline_product_baskets >= 2
  AND c.is_candidate = 1;

CREATE OR REPLACE TABLE work_relevant_promotion_clean AS
WITH collapsed AS (
    SELECT
        d.PRODUCT_ID,
        d.STORE_ID,
        d.WEEK_NO,
        COUNT(*) AS source_row_count,
        COUNT(DISTINCT d.mailer) AS n_raw_mailer_codes,
        COUNT(DISTINCT d.display) AS n_raw_display_codes,
        MIN(d.mailer) AS raw_mailer_code,
        MIN(d.display) AS raw_display_code
    FROM source.causal_data AS d
    JOIN work_relevant_product_store AS r
      ON d.PRODUCT_ID = r.PRODUCT_ID
     AND d.STORE_ID = r.STORE_ID
    WHERE d.WEEK_NO BETWEEN 1 AND 101
    GROUP BY 1, 2, 3
)
SELECT
    PRODUCT_ID,
    STORE_ID,
    WEEK_NO,
    source_row_count,
    1 AS promotion_record_present,
    raw_mailer_code AS mailer_code,
    raw_display_code AS display_code,
    CASE
        WHEN n_raw_mailer_codes > 1 OR n_raw_display_codes > 1
        THEN 1 ELSE 0
    END AS promo_code_conflict,
    CASE
        WHEN n_raw_mailer_codes = 1
         AND n_raw_display_codes = 1
         AND raw_mailer_code IN ('A', 'C', 'D', 'F', 'H', 'L')
        THEN 1 ELSE 0
    END AS is_feature_mailer,
    CASE
        WHEN n_raw_mailer_codes = 1
         AND n_raw_display_codes = 1
         AND raw_mailer_code IN ('J', 'P')
        THEN 1 ELSE 0
    END AS is_coupon_mailer,
    CASE
        WHEN n_raw_mailer_codes = 1
         AND n_raw_display_codes = 1
         AND raw_mailer_code IN ('X', 'Z')
        THEN 1 ELSE 0
    END AS is_free_mailer,
    CASE
        WHEN n_raw_mailer_codes = 1
         AND n_raw_display_codes = 1
         AND raw_mailer_code <> '0'
        THEN 1 ELSE 0
    END AS is_any_mailer,
    CASE
        WHEN n_raw_mailer_codes = 1
         AND n_raw_display_codes = 1
         AND raw_display_code IN ('1', '2', '3', '4', '5', '6', '7', '9')
        THEN 1 ELSE 0
    END AS is_display
FROM collapsed;

CREATE INDEX IF NOT EXISTS idx_customer_relevant_promo
ON work_relevant_promotion_clean (PRODUCT_ID, STORE_ID, WEEK_NO);

-- 주 분석의 선호상품 적격성은 결과기간 처치 기록을 보지 않고
-- 기준기간(1~26주)에 홈스토어 로그에 등장했는지로 확정한다.
CREATE OR REPLACE TABLE work_home_store_product_history AS
SELECT DISTINCT PRODUCT_ID, STORE_ID
FROM work_relevant_promotion_clean
WHERE WEEK_NO BETWEEN 1 AND 26;

-- 기존 1~101주 규칙은 민감도 분석용으로만 보존한다.
CREATE OR REPLACE TABLE work_home_store_product_history_all_weeks AS
SELECT DISTINCT PRODUCT_ID, STORE_ID
FROM work_relevant_promotion_clean;

CREATE OR REPLACE TABLE work_original_top20_product AS
WITH ranked AS (
    SELECT
        b.*,
        c.home_store_id,
        ROW_NUMBER() OVER (
            PARTITION BY b.household_key
            ORDER BY b.baseline_product_baskets DESC,
                     b.baseline_product_sales DESC,
                     b.PRODUCT_ID
        ) AS original_product_rank
    FROM work_baseline_product AS b
    JOIN work_baseline_customer AS c USING (household_key)
)
SELECT
    r.*,
    CASE WHEN cp.PRODUCT_ID IS NOT NULL THEN 1 ELSE 0 END
        AS appears_any_causal_store,
    CASE WHEN hp.PRODUCT_ID IS NOT NULL THEN 1 ELSE 0 END
        AS appears_home_store,
    CASE WHEN hpa.PRODUCT_ID IS NOT NULL THEN 1 ELSE 0 END
        AS appears_home_store_all_weeks
FROM ranked AS r
LEFT JOIN work_causal_product AS cp USING (PRODUCT_ID)
LEFT JOIN work_home_store_product_history AS hp
  ON r.PRODUCT_ID = hp.PRODUCT_ID
 AND r.home_store_id = hp.STORE_ID
LEFT JOIN work_home_store_product_history_all_weeks AS hpa
  ON r.PRODUCT_ID = hpa.PRODUCT_ID
 AND r.home_store_id = hpa.STORE_ID
WHERE original_product_rank <= 20;

CREATE OR REPLACE TABLE work_customer_preference AS
WITH eligible AS (
    SELECT
        b.household_key,
        b.PRODUCT_ID,
        c.home_store_id,
        b.baseline_product_baskets,
        b.baseline_product_sales,
        p.DEPARTMENT,
        ROW_NUMBER() OVER (
            PARTITION BY b.household_key
            ORDER BY b.baseline_product_baskets DESC,
                     b.baseline_product_sales DESC,
                     b.PRODUCT_ID
        ) AS preference_rank
    FROM work_baseline_product AS b
    JOIN work_baseline_customer AS c USING (household_key)
    JOIN work_home_store_product_history AS hp
      ON b.PRODUCT_ID = hp.PRODUCT_ID
     AND c.home_store_id = hp.STORE_ID
    LEFT JOIN source.product AS p
      ON b.PRODUCT_ID = p.PRODUCT_ID
    WHERE b.baseline_product_baskets >= 2
      AND c.is_candidate = 1
), top20 AS (
    SELECT *
    FROM eligible
    WHERE preference_rank <= 20
), weighted AS (
    SELECT
        *,
        SUM(baseline_product_baskets) OVER (PARTITION BY household_key)
            AS top20_basket_denominator,
        SUM(CASE WHEN preference_rank <= 10
                 THEN baseline_product_baskets ELSE 0 END)
            OVER (PARTITION BY household_key) AS top10_basket_denominator
    FROM top20
)
SELECT
    *,
    baseline_product_baskets::DOUBLE
        / NULLIF(top20_basket_denominator, 0) AS preference_weight_top20,
    CASE WHEN preference_rank <= 10
         THEN baseline_product_baskets::DOUBLE
              / NULLIF(top10_basket_denominator, 0)
         ELSE 0.0 END AS preference_weight_top10
FROM weighted;

CREATE OR REPLACE TABLE work_customer_preference_all_weeks AS
WITH eligible AS (
    SELECT
        b.household_key,
        b.PRODUCT_ID,
        c.home_store_id,
        b.baseline_product_baskets,
        ROW_NUMBER() OVER (
            PARTITION BY b.household_key
            ORDER BY b.baseline_product_baskets DESC,
                     b.baseline_product_sales DESC,
                     b.PRODUCT_ID
        ) AS preference_rank
    FROM work_baseline_product AS b
    JOIN work_baseline_customer AS c USING (household_key)
    JOIN work_home_store_product_history_all_weeks AS hp
      ON b.PRODUCT_ID = hp.PRODUCT_ID
     AND c.home_store_id = hp.STORE_ID
    WHERE b.baseline_product_baskets >= 2
      AND c.is_candidate = 1
), top20 AS (
    SELECT * FROM eligible WHERE preference_rank <= 20
)
SELECT
    *,
    baseline_product_baskets::DOUBLE
        / SUM(baseline_product_baskets) OVER (PARTITION BY household_key)
        AS preference_weight_top20
FROM top20;

CREATE OR REPLACE TABLE work_customer_preference_no_history_filter AS
WITH eligible AS (
    SELECT
        b.household_key,
        b.PRODUCT_ID,
        c.home_store_id,
        b.baseline_product_baskets,
        ROW_NUMBER() OVER (
            PARTITION BY b.household_key
            ORDER BY b.baseline_product_baskets DESC,
                     b.baseline_product_sales DESC,
                     b.PRODUCT_ID
        ) AS preference_rank
    FROM work_baseline_product AS b
    JOIN work_baseline_customer AS c USING (household_key)
    WHERE b.baseline_product_baskets >= 2
      AND c.is_candidate = 1
), top20 AS (
    SELECT * FROM eligible WHERE preference_rank <= 20
)
SELECT
    *,
    baseline_product_baskets::DOUBLE
        / SUM(baseline_product_baskets) OVER (PARTITION BY household_key)
        AS preference_weight_top20
FROM top20;

CREATE OR REPLACE TABLE work_customer_department AS
WITH department_baskets AS (
    SELECT
        t.household_key,
        p.DEPARTMENT,
        COUNT(DISTINCT t.BASKET_ID) AS baseline_department_baskets,
        SUM(t.SALES_VALUE) AS baseline_department_sales
    FROM work_customer_transaction AS t
    JOIN work_baseline_customer AS c USING (household_key)
    JOIN source.product AS p USING (PRODUCT_ID)
    WHERE t.WEEK_NO BETWEEN 1 AND 26
      AND c.is_candidate = 1
      AND p.DEPARTMENT IS NOT NULL
      AND TRIM(p.DEPARTMENT) <> ''
    GROUP BY 1, 2
), ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY household_key
            ORDER BY baseline_department_baskets DESC,
                     baseline_department_sales DESC,
                     DEPARTMENT
        ) AS department_rank
    FROM department_baskets
)
SELECT
    *,
    CASE WHEN department_rank <= 3 THEN 1 ELSE 0 END
        AS is_preferred_department
FROM ranked;

CREATE OR REPLACE TABLE work_customer_department_product AS
WITH eligible AS (
    SELECT
        b.household_key,
        p.DEPARTMENT,
        b.PRODUCT_ID,
        c.home_store_id,
        b.baseline_product_baskets,
        b.baseline_product_sales,
        d.is_preferred_department,
        ROW_NUMBER() OVER (
            PARTITION BY b.household_key, p.DEPARTMENT
            ORDER BY b.baseline_product_baskets DESC,
                     b.baseline_product_sales DESC,
                     b.PRODUCT_ID
        ) AS department_product_rank
    FROM work_baseline_product AS b
    JOIN work_baseline_customer AS c USING (household_key)
    JOIN source.product AS p USING (PRODUCT_ID)
    JOIN work_customer_department AS d
      ON b.household_key = d.household_key
     AND p.DEPARTMENT = d.DEPARTMENT
    JOIN work_home_store_product_history AS hp
      ON b.PRODUCT_ID = hp.PRODUCT_ID
     AND c.home_store_id = hp.STORE_ID
    WHERE b.baseline_product_baskets >= 2
      AND c.is_candidate = 1
), top10 AS (
    SELECT * FROM eligible WHERE department_product_rank <= 10
)
SELECT
    *,
    baseline_product_baskets::DOUBLE
        / SUM(baseline_product_baskets) OVER (
            PARTITION BY household_key, DEPARTMENT
        ) AS department_product_weight
FROM top10;

CREATE OR REPLACE TABLE work_analysis_customer AS
WITH preference_summary AS (
    SELECT
        household_key,
        COUNT(*) AS n_eligible_products,
        SUM(baseline_product_baskets) AS eligible_product_baskets
    FROM work_customer_preference
    GROUP BY 1
), all_weeks_summary AS (
    SELECT household_key, COUNT(*) AS n_eligible_products_all_weeks
    FROM work_customer_preference_all_weeks
    GROUP BY 1
), no_filter_summary AS (
    SELECT household_key, COUNT(*) AS n_repeated_products_no_history_filter
    FROM work_customer_preference_no_history_filter
    GROUP BY 1
), original_top20_summary AS (
    SELECT
        household_key,
        SUM(baseline_product_baskets) AS original_top20_baskets,
        SUM(
            CASE
                WHEN baseline_product_baskets >= 2
                 AND appears_home_store = 1
                THEN baseline_product_baskets ELSE 0
            END
        ) AS eligible_original_top20_baskets
    FROM work_original_top20_product
    GROUP BY 1
)
SELECT
    c.*,
    COALESCE(p.n_eligible_products, 0) AS n_eligible_products,
    COALESCE(p.eligible_product_baskets, 0) AS eligible_product_baskets,
    COALESCE(a.n_eligible_products_all_weeks, 0)
        AS n_eligible_products_all_weeks,
    COALESCE(n.n_repeated_products_no_history_filter, 0)
        AS n_repeated_products_no_history_filter,
    COALESCE(o.original_top20_baskets, 0) AS original_top20_baskets,
    COALESCE(o.eligible_original_top20_baskets, 0)
        AS eligible_original_top20_baskets,
    CASE
        WHEN COALESCE(o.original_top20_baskets, 0) > 0
        THEN 1.0
             - o.eligible_original_top20_baskets::DOUBLE
               / o.original_top20_baskets
        ELSE NULL
    END AS excluded_weight_share,
    CASE
        WHEN c.is_candidate = 1
         AND COALESCE(p.n_eligible_products, 0) >= 1
        THEN 1 ELSE 0
    END AS is_candidate_analysis,
    CASE
        WHEN c.is_primary_preference_pending = 1
         AND COALESCE(p.n_eligible_products, 0) >= 5
        THEN 1 ELSE 0
    END AS is_primary_analysis,
    CASE
        WHEN c.is_primary_preference_pending = 1
         AND COALESCE(p.n_eligible_products, 0) >= 1
        THEN 1 ELSE 0
    END AS is_primary_eligible1_analysis,
    CASE
        WHEN c.is_primary_preference_pending = 1
         AND COALESCE(a.n_eligible_products_all_weeks, 0) >= 5
        THEN 1 ELSE 0
    END AS is_primary_all_weeks_analysis,
    CASE
        WHEN c.is_primary_preference_pending = 1
         AND COALESCE(n.n_repeated_products_no_history_filter, 0) >= 5
        THEN 1 ELSE 0
    END AS is_primary_no_history_filter_analysis,
    CASE
        WHEN c.is_home70_preference_pending = 1
         AND COALESCE(p.n_eligible_products, 0) >= 5
        THEN 1 ELSE 0
    END AS is_home70_analysis
FROM work_baseline_customer AS c
LEFT JOIN preference_summary AS p USING (household_key)
LEFT JOIN all_weeks_summary AS a USING (household_key)
LEFT JOIN no_filter_summary AS n USING (household_key)
LEFT JOIN original_top20_summary AS o USING (household_key);

DELETE FROM audit_customer_sample_flow
WHERE step_no IN (7, 80, 81, 91);

INSERT INTO audit_customer_sample_flow
SELECT 80, 'sensitivity_candidate_with_eligible_preference', COUNT(*)
FROM work_analysis_customer WHERE is_candidate_analysis = 1
UNION ALL
SELECT 81, 'sensitivity_primary_eligible1', COUNT(*)
FROM work_analysis_customer WHERE is_primary_eligible1_analysis = 1
UNION ALL
SELECT 7, 'primary_final', COUNT(*)
FROM work_analysis_customer WHERE is_primary_analysis = 1
UNION ALL
SELECT 91, 'sensitivity_home70_final', COUNT(*)
FROM work_analysis_customer WHERE is_home70_analysis = 1;

CREATE OR REPLACE TABLE audit_customer_preference_exclusion AS
WITH reasoned AS (
    SELECT
        *,
        CASE
            WHEN baseline_product_baskets < 2 THEN 'one_time_purchase'
            WHEN appears_any_causal_store = 0 THEN 'never_in_causal_data'
            WHEN appears_home_store_all_weeks = 0 THEN 'never_at_home_store'
            WHEN appears_home_store = 0 THEN 'first_home_store_log_after_baseline'
            ELSE 'baseline_eligible_before_reranking'
        END AS eligibility_reason
    FROM work_original_top20_product
)
SELECT
    eligibility_reason,
    COUNT(*) AS customer_products,
    COUNT(DISTINCT household_key) AS households,
    SUM(baseline_product_baskets) AS baseline_baskets,
    SUM(baseline_product_baskets)::DOUBLE
        / SUM(SUM(baseline_product_baskets)) OVER () AS basket_weight_share
FROM reasoned
GROUP BY 1
ORDER BY basket_weight_share DESC;

CREATE OR REPLACE TABLE audit_customer_preference_summary AS
WITH sample_rows AS (
    SELECT 'candidate' AS sample_definition, *
    FROM work_analysis_customer WHERE is_candidate_analysis = 1
    UNION ALL
    SELECT 'primary', *
    FROM work_analysis_customer WHERE is_primary_analysis = 1
    UNION ALL
    SELECT 'home70', *
    FROM work_analysis_customer WHERE is_home70_analysis = 1
)
SELECT
    sample_definition,
    COUNT(*) AS households,
    AVG(n_eligible_products) AS avg_eligible_products,
    MEDIAN(n_eligible_products) AS median_eligible_products,
    QUANTILE_CONT(n_eligible_products, 0.10) AS p10_eligible_products,
    QUANTILE_CONT(n_eligible_products, 0.90) AS p90_eligible_products,
    AVG(excluded_weight_share) AS avg_excluded_weight_share,
    MEDIAN(excluded_weight_share) AS median_excluded_weight_share,
    QUANTILE_CONT(excluded_weight_share, 0.90) AS p90_excluded_weight_share,
    AVG(baseline_home_store_share) AS avg_baseline_home_store_share,
    AVG(outcome_home_store_share) AS avg_outcome_home_store_share
FROM sample_rows
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE TABLE audit_customer_preference_count_band AS
SELECT
    CASE
        WHEN n_eligible_products <= 4 THEN '01_1_4'
        WHEN n_eligible_products <= 9 THEN '02_5_9'
        WHEN n_eligible_products <= 14 THEN '03_10_14'
        ELSE '04_15_20'
    END AS eligible_product_band,
    COUNT(*) AS households,
    AVG(baseline_baskets) AS avg_baseline_baskets,
    AVG(baseline_home_store_share) AS avg_home_store_share
FROM work_analysis_customer
WHERE is_primary_analysis = 1
GROUP BY 1
ORDER BY 1;
