-- An instance chooses each task's chain of free models across its providers by itself until the owner sets a
-- task by hand (DECISIONS §2). An instance that has no provider yet has made no choice, so it starts in
-- auto_free; an instance with providers keeps the mode it has.
UPDATE model_mode SET mode = 'auto_free', refreshed_at = NULL
WHERE id = 1 AND mode = 'manual' AND NOT EXISTS (SELECT 1 FROM providers);
