-- Reference data for the POC: rule configuration, a starter product list and the first cycle.

INSERT INTO rule_config (key, value) VALUES
    ('baselinePct', '25'),
    ('sharing', '"UNMET_DEMAND"');

INSERT INTO product (name) VALUES
    ('Printer Model A'), ('Printer Model B'), ('Printer Model C'), ('Printer Model D'),
    ('Mono Laser L100'), ('Mono Laser L200'), ('Mono Laser MFP L300'), ('Color Laser C100'),
    ('Color Laser C200'), ('Color Laser MFP C300'), ('Inkjet Home I100'), ('Inkjet Home I200'),
    ('Inkjet Office I300'), ('Ink Tank T100'), ('Ink Tank T200'), ('Photo Inkjet P100'),
    ('Wide Format W100'), ('Wide Format W200'), ('Mobile Printer M100'), ('Label Printer B100');

INSERT INTO cycle (name, stage) VALUES ('Cycle ' || to_char(now(), 'YYYY-MM'), 1);
