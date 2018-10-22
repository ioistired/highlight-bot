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
	blocked_user BIGINT);
