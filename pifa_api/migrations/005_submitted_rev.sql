-- The Sales Manager may keep editing after submitting. The version they submitted is what the
-- Regional Manager reviews and what "forecast V1" means for planning, so remember it separately
-- from the working copy's latest version.
ALTER TABLE forecast_version ADD COLUMN submitted_rev INT;

UPDATE forecast_version SET submitted_rev = rev_no
WHERE version_no = 1 AND status IN ('submitted', 'approved', 'rejected');
