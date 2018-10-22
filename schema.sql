CREATE TABLE IF NOT EXISTS highlights(
	guild BIGINT NOT NULL,
	"user" BIGINT NOT NULL,
	highlight TEXT NOT NULL);

CREATE UNIQUE INDEX IF NOT EXISTS highlights_guild_user_highlight_unique_idx ON highlights (guild, "user", LOWER(highlight));

CREATE TABLE IF NOT EXISTS blocks(
	guild BIGINT NOT NULL,
	"user" BIGINT,
	category BIGINT,
	channel BIGINT,
	blocked_user BIGINT,

	CONSTRAINT something_is_blocked CHECK (
		category IS NOT NULL
		OR channel IS NOT NULL
		OR blocked_user IS NOT NULL));

CREATE INDEX IF NOT EXISTS blocks_guild_user_idx ON blocks (guild, "user");
