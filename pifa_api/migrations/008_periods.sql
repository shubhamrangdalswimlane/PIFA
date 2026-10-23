-- Month-year planning periods: each cycle belongs to one month (first day of the month).
-- Several months can be in progress at once; the latest cycle of a month is that month's current cycle
-- (an Admin reset starts a new cycle for the same month).
ALTER TABLE cycle ADD COLUMN period DATE;
UPDATE cycle SET period = date_trunc('month', created_at)::date;
ALTER TABLE cycle ALTER COLUMN period SET NOT NULL;
ALTER TABLE cycle ALTER COLUMN period SET DEFAULT date_trunc('month', now())::date;
ALTER TABLE cycle ADD CONSTRAINT cycle_period_first_of_month CHECK (extract(day FROM period) = 1);
CREATE INDEX cycle_period_idx ON cycle (period, id DESC);
