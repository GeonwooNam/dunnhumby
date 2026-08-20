-- 목적: causal_data를 고유한 상품-점포-주 단위로 정제하고 프로모션 변수를 만든다.
-- 입력: source.causal_data
-- 출력: work_promotion_clean
-- 중복 키의 원시 코드가 다르면 conflict로 분리해 핵심 비교에서 제외한다.

CREATE OR REPLACE TABLE work_promotion_clean AS
WITH collapsed AS (
    SELECT
        PRODUCT_ID,
        STORE_ID,
        WEEK_NO,
        COUNT(*) AS source_row_count,
        MAX(CASE WHEN mailer <> '0' THEN 1 ELSE 0 END) AS is_mailer,
        MAX(CASE WHEN display NOT IN ('0', 'A') THEN 1 ELSE 0 END) AS is_display,
        COUNT(DISTINCT mailer) AS n_raw_mailer_codes,
        COUNT(DISTINCT display) AS n_raw_display_codes,
        COUNT(DISTINCT NULLIF(mailer, '0')) AS n_mailer_codes,
        COUNT(DISTINCT CASE
            WHEN display NOT IN ('0', 'A') THEN display
        END) AS n_display_codes,
        MAX(NULLIF(mailer, '0')) AS single_mailer_code,
        MAX(CASE WHEN display NOT IN ('0', 'A') THEN display END)
            AS single_display_code,
        MAX(CASE WHEN display = 'A' THEN 1 ELSE 0 END) AS has_in_shelf,
        MAX(CASE
            WHEN mailer = '0' AND display IN ('0', 'A') THEN 1 ELSE 0
        END) AS has_explicit_none_row
    FROM source.causal_data
    GROUP BY 1, 2, 3
),
coded AS (
    SELECT
        *,
        CASE
            WHEN n_mailer_codes = 1 THEN single_mailer_code
            ELSE NULL
        END AS mailer_code,
        CASE
            WHEN n_display_codes = 1 THEN single_display_code
            ELSE NULL
        END AS display_code,
        CASE
            WHEN n_raw_mailer_codes > 1 OR n_raw_display_codes > 1 THEN 1
            ELSE 0
        END AS promo_code_conflict
    FROM collapsed
)
SELECT
    PRODUCT_ID,
    STORE_ID,
    WEEK_NO,
    source_row_count,
    1 AS promotion_record_present,
    is_mailer,
    is_display,
    is_mailer * is_display AS is_both,
    CASE
        WHEN promo_code_conflict = 1 THEN 'conflict'
        WHEN is_mailer = 0 AND is_display = 0 THEN 'none'
        WHEN is_mailer = 0 AND is_display = 1 THEN 'display_only'
        WHEN is_mailer = 1 AND is_display = 0 THEN 'mailer_only'
        ELSE 'both'
    END AS promo_group,
    mailer_code,
    display_code,
    has_in_shelf,
    CASE
        WHEN promo_code_conflict = 0
         AND is_mailer = 0 AND is_display = 0
         AND has_explicit_none_row = 1 THEN 1
        ELSE 0
    END AS is_explicit_none,
    CASE
        WHEN mailer_code IN ('J', 'P') THEN 'coupon'
        WHEN mailer_code IN ('X', 'Z') THEN 'free_item'
        WHEN mailer_code IN ('A', 'C', 'D', 'F', 'H', 'L') THEN 'position'
        WHEN is_mailer = 0 THEN 'none'
        ELSE 'other_or_conflict'
    END AS mailer_offer_type,
    promo_code_conflict
FROM coded;

CREATE UNIQUE INDEX IF NOT EXISTS idx_work_promotion_key
ON work_promotion_clean (PRODUCT_ID, STORE_ID, WEEK_NO);
