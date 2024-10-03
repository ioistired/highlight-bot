CREATE TABLE highlights(
	guild BIGINT NOT NULL,
	"user" BIGINT NOT NULL,
	highlight TEXT NOT NULL);

CREATE UNIQUE INDEX highlights_uniq_idx ON highlights (guild, "user", LOWER(highlight));
CREATE INDEX highlights_guild_idx ON highlights (guild);

CREATE TYPE block_entity_type AS ENUM ('user', 'channel', 'unknown');

CREATE TABLE blocks(
	"user" BIGINT NOT NULL,
	entity BIGINT NOT NULL,
	"type" block_entity_type NOT NULL DEFAULT 'unknown',

	PRIMARY KEY ("user", entity));

CREATE INDEX IF NOT EXISTS blocks_entity_idx ON blocks (entity);
