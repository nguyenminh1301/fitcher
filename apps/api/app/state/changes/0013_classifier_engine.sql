-- The prompt-injection classifier runs through a model provider by default, or on
-- this computer (DECISIONS §9). An instance that turned the classifier on before
-- this change ran it on this computer, so it keeps that engine.
INSERT INTO settings (group_name, key, value, updated_at)
SELECT 'screening', 'classifier_engine', '"local_onnx"', strftime('%Y-%m-%dT%H:%M:%f+00:00', 'now')
WHERE EXISTS (SELECT 1 FROM settings WHERE group_name = 'screening' AND key = 'classifier_enabled' AND value = 'true')
  AND NOT EXISTS (SELECT 1 FROM settings WHERE group_name = 'screening' AND key = 'classifier_engine');
