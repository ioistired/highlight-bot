CREATE TABLE IF NOT EXISTS highlights(
	"user" BIGINT NOT NULL,
	guild BIGINT NOT NULL,
	highlights TEXT[] NOT NULL,

	PRIMARY KEY ("user", guild));

CREATE TABLE IF NOT EXISTS blocks(
	"user" BIGINT,
	guild BIGINT NOT NULL,
	categories BIGINT[],
	channels BIGINT[],
	users BIGINT[],

	PRIMARY KEY ("user", guild));
