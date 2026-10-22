-- Forecast revision history: every save (cell edits or one Excel file) by the Sales Manager or the
-- Regional Manager creates a numbered, immutable snapshot per cycle and region (V1, V2, ... V6).
-- forecast_version keeps the working copy of each stage (1 = Sales Manager, 2 = Regional Manager)
-- and remembers which revision it currently holds.

CREATE TABLE forecast_revision (
    id         SERIAL PRIMARY KEY,
    cycle_id   INT NOT NULL REFERENCES cycle(id),
    region     TEXT NOT NULL CHECK (region IN ('North', 'East', 'West', 'South')),
    rev_no     INT NOT NULL CHECK (rev_no > 0),
    stage      SMALLINT NOT NULL CHECK (stage IN (1, 2)),
    source     TEXT NOT NULL CHECK (source IN ('edit', 'upload', 'submit', 'restore')),
    file_name  TEXT,
    created_by TEXT NOT NULL,
    role       TEXT NOT NULL,
    comment    TEXT,
    changed    INT NOT NULL DEFAULT 0,
    total      INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, region, rev_no)
);

CREATE TABLE forecast_revision_line (
    revision_id INT NOT NULL REFERENCES forecast_revision(id) ON DELETE CASCADE,
    product_id  INT NOT NULL REFERENCES product(id),
    qty         INT NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (revision_id, product_id)
);

ALTER TABLE forecast_version ADD COLUMN rev_no INT;

-- Backfill: existing stage versions become revisions 1 (Sales Manager) and 2 (Regional Manager).
INSERT INTO forecast_revision (cycle_id, region, rev_no, stage, source, created_by, role, comment, total)
SELECT fv.cycle_id, fv.region, fv.version_no, fv.version_no, 'edit', coalesce(fv.updated_by, 'migration'),
       CASE fv.version_no WHEN 1 THEN 'SALES_MANAGER' ELSE 'REGIONAL_MANAGER' END,
       'Backfilled from the forecast before revision history existed',
       coalesce((SELECT sum(qty) FROM forecast_line fl WHERE fl.version_id = fv.id), 0)
FROM forecast_version fv;

INSERT INTO forecast_revision_line (revision_id, product_id, qty)
SELECT fr.id, fl.product_id, fl.qty
FROM forecast_revision fr
JOIN forecast_version fv ON fv.cycle_id = fr.cycle_id AND fv.region = fr.region AND fv.version_no = fr.rev_no
JOIN forecast_line fl ON fl.version_id = fv.id;

UPDATE forecast_version SET rev_no = version_no;
