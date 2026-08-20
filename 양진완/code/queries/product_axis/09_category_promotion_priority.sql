-- 목적: 동일 상품-점포 내부 차이를 상품군(COMMODITY_DESC) 수준으로 집계해
--       상품군별 유망 프로모션 후보와 병행 추가분을 선별한다.
-- 입력: work_pair_group_means, source.product
-- 출력: work_category_product_store_comparison,
--       mart_category_promotion_response_sensitivity,
--       mart_category_promotion_main, mart_category_promotion_matrix
--
-- 해석 주의:
-- 1) 주 분석은 비교 상태가 각각 2주 이상인 상품-점포 쌍을 사용한다.
-- 2) 상품군-프로모션 셀은 상품 5개, 상품-점포 쌍 20개, 점포 5개 이상을 요구한다.
-- 3) 상품-점포와 상품 두 수준에서 모두 절반을 넘는 양의 방향이 나타나야
--    탐색 후보로 표시한다. 이는 유의성 검정이나 인과효과 판정이 아니다.

CREATE OR REPLACE TABLE work_category_product_store_comparison AS
WITH pair_state AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'none')
            AS none_weeks,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'display_only')
            AS display_weeks,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'mailer_only')
            AS mailer_weeks,
        MAX(observed_weeks) FILTER (WHERE promo_group = 'both')
            AS both_weeks,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'none')
            AS none_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'display_only')
            AS display_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'mailer_only')
            AS mailer_spv,
        MAX(avg_sales_per_visitor) FILTER (WHERE promo_group = 'both')
            AS both_spv,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'none')
            AS none_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'display_only')
            AS display_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'mailer_only')
            AS mailer_bpr,
        MAX(avg_buyer_penetration_rate) FILTER (WHERE promo_group = 'both')
            AS both_bpr
    FROM work_pair_group_means
    GROUP BY 1, 2
), comparisons AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        'display_only_vs_none' AS comparison,
        none_weeks AS reference_weeks,
        display_weeks AS comparison_weeks,
        LEAST(none_weeks, display_weeks) AS min_state_weeks,
        none_spv AS reference_spv,
        display_spv AS comparison_spv,
        none_bpr AS reference_bpr,
        display_bpr AS comparison_bpr
    FROM pair_state
    WHERE none_weeks IS NOT NULL AND display_weeks IS NOT NULL

    UNION ALL

    SELECT
        PRODUCT_ID,
        STORE_ID,
        'mailer_only_vs_none',
        none_weeks,
        mailer_weeks,
        LEAST(none_weeks, mailer_weeks),
        none_spv,
        mailer_spv,
        none_bpr,
        mailer_bpr
    FROM pair_state
    WHERE none_weeks IS NOT NULL AND mailer_weeks IS NOT NULL

    UNION ALL

    SELECT
        PRODUCT_ID,
        STORE_ID,
        'both_vs_none',
        none_weeks,
        both_weeks,
        LEAST(none_weeks, both_weeks),
        none_spv,
        both_spv,
        none_bpr,
        both_bpr
    FROM pair_state
    WHERE none_weeks IS NOT NULL AND both_weeks IS NOT NULL

    UNION ALL

    SELECT
        PRODUCT_ID,
        STORE_ID,
        'both_vs_additive',
        LEAST(none_weeks, display_weeks, mailer_weeks),
        both_weeks,
        LEAST(none_weeks, display_weeks, mailer_weeks, both_weeks),
        display_spv + mailer_spv - none_spv,
        both_spv,
        display_bpr + mailer_bpr - none_bpr,
        both_bpr
    FROM pair_state
    WHERE none_weeks IS NOT NULL
      AND display_weeks IS NOT NULL
      AND mailer_weeks IS NOT NULL
      AND both_weeks IS NOT NULL
)
SELECT
    c.PRODUCT_ID,
    c.STORE_ID,
    p.DEPARTMENT,
    p.COMMODITY_DESC,
    c.comparison,
    c.reference_weeks,
    c.comparison_weeks,
    c.min_state_weeks,
    c.reference_spv,
    c.comparison_spv,
    c.comparison_spv - c.reference_spv AS spv_difference,
    c.reference_bpr,
    c.comparison_bpr,
    c.comparison_bpr - c.reference_bpr AS bpr_difference,
    CASE WHEN c.comparison_spv > c.reference_spv THEN 1 ELSE 0 END
        AS is_positive_spv,
    CASE WHEN c.comparison_bpr > c.reference_bpr THEN 1 ELSE 0 END
        AS is_positive_bpr
FROM comparisons AS c
INNER JOIN source.product AS p USING (PRODUCT_ID)
WHERE p.COMMODITY_DESC IS NOT NULL;

CREATE OR REPLACE TABLE mart_category_promotion_response_sensitivity AS
WITH thresholds AS (
    SELECT min_weeks
    FROM range(1, 4) AS t(min_weeks)
), eligible AS (
    SELECT t.min_weeks, d.*
    FROM thresholds AS t
    INNER JOIN work_category_product_store_comparison AS d
      ON d.min_state_weeks >= t.min_weeks
), product_level AS (
    SELECT
        min_weeks,
        DEPARTMENT,
        COMMODITY_DESC,
        comparison,
        PRODUCT_ID,
        COUNT(*) AS eligible_product_stores,
        MEDIAN(spv_difference) AS product_median_spv_difference,
        MEDIAN(bpr_difference) AS product_median_bpr_difference
    FROM eligible
    GROUP BY 1, 2, 3, 4, 5
), pair_summary AS (
    SELECT
        min_weeks,
        DEPARTMENT,
        COMMODITY_DESC,
        comparison,
        COUNT(*) AS product_store_pairs,
        COUNT(DISTINCT PRODUCT_ID) AS products,
        COUNT(DISTINCT STORE_ID) AS stores,
        MEDIAN(spv_difference) AS pair_median_spv_difference,
        100.0 * AVG(CASE WHEN is_positive_spv = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_spv_pair_pct,
        MEDIAN(bpr_difference) AS pair_median_bpr_difference,
        100.0 * AVG(CASE WHEN is_positive_bpr = 1 THEN 1.0 ELSE 0.0 END)
            AS positive_bpr_pair_pct
    FROM eligible
    GROUP BY 1, 2, 3, 4
), product_summary AS (
    SELECT
        min_weeks,
        DEPARTMENT,
        COMMODITY_DESC,
        comparison,
        COUNT(*) AS product_count_check,
        MEDIAN(product_median_spv_difference)
            AS median_product_spv_difference,
        100.0 * AVG(
            CASE WHEN product_median_spv_difference > 0 THEN 1.0 ELSE 0.0 END
        ) AS positive_spv_product_pct,
        MEDIAN(product_median_bpr_difference)
            AS median_product_bpr_difference,
        100.0 * AVG(
            CASE WHEN product_median_bpr_difference > 0 THEN 1.0 ELSE 0.0 END
        ) AS positive_bpr_product_pct
    FROM product_level
    GROUP BY 1, 2, 3, 4
), scored AS (
    SELECT
        p.*,
        s.median_product_spv_difference,
        s.positive_spv_product_pct,
        s.median_product_bpr_difference,
        s.positive_bpr_product_pct,
        CASE
            WHEN p.products >= 5
             AND p.product_store_pairs >= 20
             AND p.stores >= 5
            THEN 1 ELSE 0
        END AS has_adequate_support
    FROM pair_summary AS p
    INNER JOIN product_summary AS s
        USING (min_weeks, DEPARTMENT, COMMODITY_DESC, comparison)
), classified AS (
    SELECT
        *,
        CASE
            WHEN has_adequate_support = 1
             AND pair_median_spv_difference > 0
             AND positive_spv_pair_pct > 50
             AND median_product_spv_difference > 0
             AND positive_spv_product_pct > 50
            THEN 1 ELSE 0
        END AS is_sales_signal,
        CASE
            WHEN has_adequate_support = 1
             AND pair_median_bpr_difference > 0
             AND positive_bpr_pair_pct > 50
             AND median_product_bpr_difference > 0
             AND positive_bpr_product_pct > 50
            THEN 1 ELSE 0
        END AS is_penetration_signal
    FROM scored
)
SELECT
    *,
    CASE
        WHEN is_sales_signal = 1 OR is_penetration_signal = 1 THEN 1 ELSE 0
    END AS is_promising,
    CASE
        WHEN has_adequate_support = 0 THEN 'insufficient_support'
        WHEN is_sales_signal = 1 AND is_penetration_signal = 1
            THEN 'sales_and_penetration'
        WHEN is_sales_signal = 1 THEN 'sales_only'
        WHEN is_penetration_signal = 1 THEN 'penetration_only'
        ELSE 'mixed_or_nonpositive'
    END AS response_label
FROM classified
ORDER BY min_weeks, DEPARTMENT, COMMODITY_DESC, comparison;

-- 세 직접 비교가 모두 가능한 상품군만 같은 행에서 비교한다.
CREATE OR REPLACE TABLE mart_category_promotion_main AS
WITH comparable_categories AS (
    SELECT DEPARTMENT, COMMODITY_DESC
    FROM mart_category_promotion_response_sensitivity
    WHERE min_weeks = 2
      AND comparison IN (
          'display_only_vs_none', 'mailer_only_vs_none', 'both_vs_none'
      )
      AND has_adequate_support = 1
    GROUP BY 1, 2
    HAVING COUNT(DISTINCT comparison) = 3
)
SELECT r.*
FROM mart_category_promotion_response_sensitivity AS r
INNER JOIN comparable_categories AS c
    USING (DEPARTMENT, COMMODITY_DESC)
WHERE r.min_weeks = 2
ORDER BY r.COMMODITY_DESC,
    CASE r.comparison
        WHEN 'display_only_vs_none' THEN 1
        WHEN 'mailer_only_vs_none' THEN 2
        WHEN 'both_vs_none' THEN 3
        ELSE 4
    END;

CREATE OR REPLACE TABLE mart_category_promotion_matrix AS
WITH main_direct AS (
    SELECT *
    FROM mart_category_promotion_main
    WHERE comparison IN (
        'display_only_vs_none', 'mailer_only_vs_none', 'both_vs_none'
    )
), stable_three_week AS (
    SELECT DEPARTMENT, COMMODITY_DESC, comparison, is_promising
    FROM mart_category_promotion_response_sensitivity
    WHERE min_weeks = 3 AND has_adequate_support = 1
), synergy_two_week AS (
    SELECT DEPARTMENT, COMMODITY_DESC, has_adequate_support, is_promising,
           response_label, products, product_store_pairs
    FROM mart_category_promotion_response_sensitivity
    WHERE min_weeks = 2 AND comparison = 'both_vs_additive'
), synergy_three_week AS (
    SELECT DEPARTMENT, COMMODITY_DESC, has_adequate_support, is_promising
    FROM mart_category_promotion_response_sensitivity
    WHERE min_weeks = 3 AND comparison = 'both_vs_additive'
), pivoted AS (
    SELECT
        d.DEPARTMENT,
        d.COMMODITY_DESC,
        MAX(d.response_label) FILTER (
            WHERE d.comparison = 'display_only_vs_none'
        ) AS display_response,
        MAX(d.products) FILTER (
            WHERE d.comparison = 'display_only_vs_none'
        ) AS display_products,
        MAX(d.product_store_pairs) FILTER (
            WHERE d.comparison = 'display_only_vs_none'
        ) AS display_pairs,
        MAX(d.is_promising) FILTER (
            WHERE d.comparison = 'display_only_vs_none'
        ) AS is_display_candidate,
        MAX(d.response_label) FILTER (
            WHERE d.comparison = 'mailer_only_vs_none'
        ) AS mailer_response,
        MAX(d.products) FILTER (
            WHERE d.comparison = 'mailer_only_vs_none'
        ) AS mailer_products,
        MAX(d.product_store_pairs) FILTER (
            WHERE d.comparison = 'mailer_only_vs_none'
        ) AS mailer_pairs,
        MAX(d.is_promising) FILTER (
            WHERE d.comparison = 'mailer_only_vs_none'
        ) AS is_mailer_candidate,
        MAX(d.response_label) FILTER (
            WHERE d.comparison = 'both_vs_none'
        ) AS both_response,
        MAX(d.products) FILTER (
            WHERE d.comparison = 'both_vs_none'
        ) AS both_products,
        MAX(d.product_store_pairs) FILTER (
            WHERE d.comparison = 'both_vs_none'
        ) AS both_pairs,
        MAX(d.is_promising) FILTER (
            WHERE d.comparison = 'both_vs_none'
        ) AS is_both_candidate
    FROM main_direct AS d
    GROUP BY 1, 2
), stable_pivot AS (
    SELECT
        DEPARTMENT,
        COMMODITY_DESC,
        MAX(is_promising) FILTER (
            WHERE comparison = 'display_only_vs_none'
        ) AS display_candidate_3week,
        MAX(is_promising) FILTER (
            WHERE comparison = 'mailer_only_vs_none'
        ) AS mailer_candidate_3week,
        MAX(is_promising) FILTER (
            WHERE comparison = 'both_vs_none'
        ) AS both_candidate_3week
    FROM stable_three_week
    GROUP BY 1, 2
), joined AS (
    SELECT
        p.*,
        CASE WHEN p.is_display_candidate = 1
                   AND COALESCE(s.display_candidate_3week, 0) = 1
             THEN 1 ELSE 0 END AS display_stable_3week,
        CASE WHEN p.is_mailer_candidate = 1
                   AND COALESCE(s.mailer_candidate_3week, 0) = 1
             THEN 1 ELSE 0 END AS mailer_stable_3week,
        CASE WHEN p.is_both_candidate = 1
                   AND COALESCE(s.both_candidate_3week, 0) = 1
             THEN 1 ELSE 0 END AS both_stable_3week,
        y.response_label AS synergy_response,
        y.products AS synergy_products,
        y.product_store_pairs AS synergy_pairs,
        CASE WHEN y.has_adequate_support = 1 THEN y.is_promising END
            AS is_synergy_candidate,
        CASE WHEN y.is_promising = 1
                   AND COALESCE(y3.has_adequate_support, 0) = 1
                   AND COALESCE(y3.is_promising, 0) = 1
             THEN 1 ELSE 0 END AS synergy_stable_3week
    FROM pivoted AS p
    LEFT JOIN stable_pivot AS s USING (DEPARTMENT, COMMODITY_DESC)
    LEFT JOIN synergy_two_week AS y USING (DEPARTMENT, COMMODITY_DESC)
    LEFT JOIN synergy_three_week AS y3 USING (DEPARTMENT, COMMODITY_DESC)
)
SELECT
    *,
    is_display_candidate + is_mailer_candidate + is_both_candidate
        AS candidate_promo_count,
    CONCAT_WS(
        ', ',
        CASE WHEN is_display_candidate = 1 THEN '특별 진열' END,
        CASE WHEN is_mailer_candidate = 1 THEN '전단' END,
        CASE WHEN is_both_candidate = 1 THEN '전단+진열' END
    ) AS promising_promotions,
    CASE
        WHEN is_display_candidate + is_mailer_candidate + is_both_candidate = 0
            THEN '뚜렷한 후보 없음'
        WHEN is_display_candidate + is_mailer_candidate + is_both_candidate = 1
            THEN '단일 우선 후보'
        ELSE '복수 후보 - 우열 미확정'
    END AS strategy_type
FROM joined
ORDER BY candidate_promo_count DESC, COMMODITY_DESC;
