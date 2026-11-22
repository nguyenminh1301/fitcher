-- Each conversation keeps the pack of the source it was started on (DECISIONS §1,
-- §15). A conversation started before this change stores no pack; it keeps the
-- pack that was active when the change was applied, recorded here, while the
-- "active" pack becomes the pack used last, where a new chat starts.
INSERT INTO settings (group_name, key, value, updated_at)
SELECT 'pack', 'earlier_conversations', value, strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
FROM settings
WHERE group_name = 'pack' AND key = 'active'
  AND NOT EXISTS (SELECT 1 FROM settings WHERE group_name = 'pack' AND key = 'earlier_conversations');
