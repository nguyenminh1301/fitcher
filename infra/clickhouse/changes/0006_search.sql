-- Pack search in ClickHouse (DECISIONS §5 Search collections). Each generation
-- of a logical collection <pack>_<index> is a table search.<collection>__<N>,
-- created by the search_index user at compile time. search.live names the live
-- generation of each collection: the latest switched_at of a collection wins,
-- and a compile switches all six collections of a pack in one insert.
CREATE DATABASE IF NOT EXISTS search;
CREATE TABLE IF NOT EXISTS search.live
(
    collection String,
    generation UInt32,
    switched_at DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree(switched_at)
ORDER BY collection;
