CREATE TABLE IF NOT EXISTS highlights(
	guild BIGINT NOT NULL,
	"user" BIGINT NOT NULL,
	highlight TEXT NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS highlights_uniq_idx ON highlights (guild, "user", LOWER(highlight));
CREATE INDEX IF NOT EXISTS highlights_guild_idx ON highlights (guild);

CREATE TABLE IF NOT EXISTS blocks(
	"user" BIGINT NOT NULL,
	entity BIGINT NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS blocks_unique_idx ON blocks ("user", entity);
CREATE INDEX IF NOT EXISTS blocks_entity_idx ON blocks (entity);
