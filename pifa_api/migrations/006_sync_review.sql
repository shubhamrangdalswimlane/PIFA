-- One-time catch-up for 005 → "Sales Manager saves during review reach the Regional Manager":
-- regions still in review whose Sales Manager saved newer versions before that rule existed get
-- their latest version sent to review now (same effect as routes_workflow._send_to_review).

CREATE TEMP TABLE stale_review ON COMMIT DROP AS
SELECT v1.id AS v1_id, v2.id AS v2_id, v1.rev_no, v1.cycle_id, v1.region
FROM forecast_version v1
JOIN cycle c ON c.id = v1.cycle_id
JOIN forecast_version v2 ON v2.cycle_id = v1.cycle_id AND v2.region = v1.region AND v2.version_no = 2
WHERE v1.version_no = 1 AND v1.status = 'submitted' AND c.stage <= 2
  AND v1.rev_no IS NOT NULL AND v1.rev_no > coalesce(v1.submitted_rev, 0);

DELETE FROM forecast_line WHERE version_id IN (SELECT v2_id FROM stale_review);

INSERT INTO forecast_line (version_id, product_id, qty)
SELECT s.v2_id, fl.product_id, fl.qty FROM stale_review s JOIN forecast_line fl ON fl.version_id = s.v1_id;

UPDATE forecast_version fv SET rev_no = s.rev_no, status = 'draft', updated_at = now()
FROM stale_review s WHERE fv.id = s.v2_id;

UPDATE forecast_version fv SET submitted_rev = s.rev_no FROM stale_review s WHERE fv.id = s.v1_id;

INSERT INTO audit_log (username, role, region, cycle_id, entity, version, comment, status)
SELECT 'system', 'SYSTEM', s.region, s.cycle_id, 'forecast', 'V' || s.rev_no,
       'Latest Sales Manager version V' || s.rev_no || ' sent to regional review (catch-up after upgrade)', 'submitted'
FROM stale_review s;
