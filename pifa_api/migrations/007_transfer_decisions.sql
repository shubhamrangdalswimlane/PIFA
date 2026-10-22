-- Head of Sales decides on each transfer at final approval (approve or reject), or on all at once.
ALTER TABLE transfer_request DROP CONSTRAINT transfer_request_status_check;
ALTER TABLE transfer_request ADD CONSTRAINT transfer_request_status_check
    CHECK (status IN ('pending', 'undone', 'approved', 'rejected'));

ALTER TABLE transfer_request
    ADD COLUMN decided_by       TEXT,
    ADD COLUMN decided_at       TIMESTAMPTZ,
    ADD COLUMN decision_comment TEXT;
