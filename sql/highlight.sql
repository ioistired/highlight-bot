-- :macro channel_highlights()
-- params: guild_id, (channel_id, channel_category_id)
SELECT "user", highlight
FROM highlights
WHERE
	guild = $1
	AND NOT EXISTS (
		SELECT 1
		FROM blocks
		WHERE
			highlights.user = blocks.user
			AND entity = ANY ($2))
-- :endmacro

-- :macro user_highlights()
-- params: guild_id, user_id
SELECT highlight
FROM highlights
WHERE
	guild = $1
	AND "user" = $2
-- :endmacro

-- :macro blocks()
-- params: user_id
SELECT entity
FROM blocks
WHERE "user" = $1
-- :endmacro

-- :macro blocked()
-- params: user_id, entity_id
SELECT true
FROM blocks
WHERE
	"user" = $1
	AND entity = $2
-- :endmacro

-- :macro add()
-- params: guild_id, user_id, highlight
INSERT INTO highlights(guild, "user", highlight)
VALUES ($1, $2, $3)
ON CONFLICT DO NOTHING
-- :endmacro

-- :macro remove()
-- params: guild_id, user_id, highlight
DELETE FROM highlights
WHERE
	guild = $1
	AND "user" = $2
	AND LOWER(highlight) = LOWER($3)
-- :endmacro

-- :macro clear()
-- params: guild_id, user_id
DELETE FROM highlights
WHERE
	guild = $1
	AND "user" = $2
-- :endmacro

-- :macro clear_guild()
-- params: guild_id
DELETE FROM highlights
WHERE guild = $1
-- :endmacro

-- :macro import_()
-- params: source_guild_id, target_guild_id, user_id
INSERT INTO highlights (guild, "user", highlight)
SELECT FOR UPDATE $2, "user", highlight
FROM highlights
WHERE
	guild = $1
	AND "user" = $3
ON CONFLICT DO NOTHING
-- :endmacro

-- :macro highlight_count()
-- params: guild_id, user_id
SELECT COUNT(*)
FROM highlights
WHERE
	guild = $1
	AND "user" = $2
-- :endmacro

-- :macro block()
-- params: user_id, entity_id
INSERT INTO blocks ("user", entity)
VALUES ($1, $2)
ON CONFLICT DO NOTHING
-- :endmacro

-- :macro unblock()
-- params: user_id, entity_id
DELETE FROM blocks
WHERE
	"user" = $1
	AND entity = $2
-- :endmacro

-- :macro delete_by_user(table)
-- params: user_id
DELETE FROM {{ table }}
WHERE "user" = $1
-- :endmacro
