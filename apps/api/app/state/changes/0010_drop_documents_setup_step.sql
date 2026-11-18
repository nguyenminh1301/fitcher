-- The setup no longer asks about company documents, and a new instance starts with
-- them off (DECISIONS §15). An instance that already has setup state never stored
-- the setting while it defaulted to on, so it is stored as on here: such an
-- instance keeps searching its documents until the owner turns them off on the
-- Documents page. The answer to the removed step is dropped.
INSERT INTO settings (group_name, key, value, updated_at)
SELECT 'documents', 'enabled', 'true', strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE (EXISTS (SELECT 1 FROM setup_steps) OR EXISTS (SELECT 1 FROM settings WHERE group_name = 'setup'))
  AND NOT EXISTS (SELECT 1 FROM settings WHERE group_name = 'documents' AND key = 'enabled');
DELETE FROM setup_steps WHERE id = 'documents';
