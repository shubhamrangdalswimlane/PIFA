-- A Sales Manager may upload a forecast file at any stage. While their forecast is locked
-- (submitted, or after regional review) the file is kept as a version in the history only:
-- applied = false means the version was not copied into the working forecast.
ALTER TABLE forecast_revision ADD COLUMN applied BOOLEAN NOT NULL DEFAULT true;
