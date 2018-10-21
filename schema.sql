CREATE TABLE IF NOT EXISTS highlights(
	guild BIGINT NOT NULL,
	"user" BIGINT NOT NULL,
	highlights TEXT[] NOT NULL,

	PRIMARY KEY (guild, "user"));

CREATE TABLE IF NOT EXISTS blocks(
	guild BIGINT NOT NULL,
	"user" BIGINT,
	categories BIGINT[],
	channels BIGINT[],
	users BIGINT[],

	PRIMARY KEY (guild, "user"),
	CHECK (
		categories IS NOT NULL
		OR channels IS NOT NULL
		OR users IS NOT NULL));
