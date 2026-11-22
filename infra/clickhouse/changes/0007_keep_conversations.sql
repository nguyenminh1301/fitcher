-- Conversations, their messages, groups and feedback are kept until their
-- owner deletes them (DECISIONS §10); run logs, events, LLM calls, SQL runs,
-- audit and screening keep the 90-day expiry. Each table keeps its 0002
-- definition with the TTL, so this change removes it. The runner records the
-- change once applied, so each statement runs once on a volume.
ALTER TABLE agent_logs.conversations REMOVE TTL;
ALTER TABLE agent_logs.conversation_groups REMOVE TTL;
ALTER TABLE agent_logs.chat_messages REMOVE TTL;
ALTER TABLE agent_logs.feedback REMOVE TTL;
