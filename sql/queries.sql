-- name: channel_highlights
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

-- name: user_highlights
-- params: guild_id, user_id
SELECT highlight
FROM highlights
WHERE
	guild = $1
	AND "user" = $2

-- name: blocks
-- params: user_id
SELECT entity
FROM blocks
WHERE "user" = $1

-- name: blocked
-- params: user_id, entity_id
SELECT true
FROM blocks
WHERE
	"user" = $1
	AND entity = $2

-- name: add
-- params: guild_id, user_id, highlight
INSERT INTO highlights(guild, "user", highlight)
VALUES ($1, $2, $3)
ON CONFLICT DO NOTHING

-- name: remove
-- params: guild_id, user_id, highlight
DELETE FROM highlights
WHERE
	guild = $1
	AND "user" = $2
	AND LOWER(highlight) = LOWER($3)

-- name: clear
-- params: guild_id, user_id
DELETE FROM highlights
WHERE
	guild = $1
	AND "user" = $2

-- name: clear_guild
-- params: guild_id
DELETE FROM highlights
WHERE guild = $1

-- name: import_
-- params: source_guild_id, target_guild_id, user_id
INSERT INTO highlights (guild, "user", highlight)
SELECT FOR UPDATE $2, "user", highlight
FROM highlights
WHERE
	guild = $1
	AND "user" = $3
ON CONFLICT DO NOTHING

-- name: highlight_count
-- params: guild_id, user_id
-- for update because checking the highlight count usually precedes updating it
SELECT COUNT(*)
FROM highlights
WHERE
	guild = $1
	AND "user" = $2

-- name: block
-- params: user_id, entity_id
INSERT INTO blocks ("user", entity)
VALUES ($1, $2)
ON CONFLICT DO NOTHING

-- name: unblock
-- params: user_id, entity_id
DELETE FROM blocks
WHERE
	"user" = $1
	AND entity = $2

-- name: delete_by_user
-- params: user_id
DELETE FROM {table}
WHERE "user" = $1
