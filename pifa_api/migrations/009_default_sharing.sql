-- Default allocation logic: equal percentage cut for every region when inventory is below the forecast.
UPDATE rule_config SET value = '"PROPORTIONAL"' WHERE key = 'sharing';
