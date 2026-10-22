-- PIFA schema (Arch §6). Lives in schema `pifa` so it can share a database with Keycloak.

CREATE TABLE product (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE cycle (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    stage      SMALLINT NOT NULL DEFAULT 1 CHECK (stage BETWEEN 1 AND 6),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE forecast_version (
    id         SERIAL PRIMARY KEY,
    cycle_id   INT NOT NULL REFERENCES cycle(id),
    region     TEXT NOT NULL CHECK (region IN ('North', 'East', 'West', 'South')),
    version_no SMALLINT NOT NULL CHECK (version_no IN (1, 2)),
    status     TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, region, version_no)
);

CREATE TABLE forecast_line (
    version_id INT NOT NULL REFERENCES forecast_version(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES product(id),
    qty        INT NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (version_id, product_id)
);

CREATE TABLE inventory_snapshot (
    id          SERIAL PRIMARY KEY,
    cycle_id    INT NOT NULL REFERENCES cycle(id),
    source_file TEXT,
    uploaded_by TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE inventory_line (
    snapshot_id INT NOT NULL REFERENCES inventory_snapshot(id) ON DELETE CASCADE,
    product_id  INT NOT NULL REFERENCES product(id),
    qty         INT NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (snapshot_id, product_id)
);

CREATE TABLE allocation_version (
    id         SERIAL PRIMARY KEY,
    cycle_id   INT NOT NULL REFERENCES cycle(id),
    version_no TEXT NOT NULL CHECK (version_no IN ('1', '2', 'final')),
    status     TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'published')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, version_no)
);

CREATE TABLE allocation_line (
    version_id INT NOT NULL REFERENCES allocation_version(id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES product(id),
    region     TEXT NOT NULL CHECK (region IN ('North', 'East', 'West', 'South')),
    qty        INT NOT NULL CHECK (qty >= 0),
    PRIMARY KEY (version_id, product_id, region)
);

CREATE TABLE transfer_request (
    id               SERIAL PRIMARY KEY,
    cycle_id         INT NOT NULL REFERENCES cycle(id),
    product_id       INT NOT NULL REFERENCES product(id),
    from_region      TEXT NOT NULL,
    to_region        TEXT NOT NULL,
    qty              INT NOT NULL CHECK (qty > 0),
    comment          TEXT NOT NULL,
    requested_by     TEXT NOT NULL,
    requested_region TEXT,
    status           TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'undone', 'approved')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (from_region <> to_region)
);

CREATE TABLE region_confirmation (
    cycle_id     INT NOT NULL REFERENCES cycle(id),
    region       TEXT NOT NULL,
    confirmed_by TEXT NOT NULL,
    confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (cycle_id, region)
);

CREATE TABLE approval (
    id         SERIAL PRIMARY KEY,
    cycle_id   INT NOT NULL REFERENCES cycle(id),
    entity     TEXT NOT NULL,
    decision   TEXT NOT NULL,
    comment    TEXT,
    decided_by TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE file_ingest (
    id          SERIAL PRIMARY KEY,
    path        TEXT NOT NULL,
    kind        TEXT NOT NULL,
    status      TEXT NOT NULL,
    message     TEXT,
    uploaded_by TEXT,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rule_config (
    key   TEXT PRIMARY KEY,
    value JSONB NOT NULL
);

CREATE TABLE audit_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    username   TEXT NOT NULL,
    role       TEXT NOT NULL,
    region     TEXT,
    cycle_id   INT,
    entity     TEXT NOT NULL,
    version    TEXT,
    product_id INT REFERENCES product(id),
    before_qty INT,
    after_qty  INT,
    comment    TEXT,
    status     TEXT
);
CREATE INDEX audit_log_ts_idx ON audit_log (ts DESC);
CREATE INDEX audit_log_region_idx ON audit_log (region);

-- Append-only: block UPDATE, DELETE and TRUNCATE for every role, including the owner.
CREATE FUNCTION audit_log_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only();
