# encoding: utf-8

class Database:
	def __init__(self, bot):
		self.bot = bot

	async def get_user_highlights(self, guild, user):
		return await self.bot.pool.fetchval("""
			SELECT highlights
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user) or []

	async def add_user_highlight(self, guild, user, highlight):
		await self.bot.pool.execute("""
			INSERT INTO highlights AS h
			VALUES ($1, $2, $3)
			ON CONFLICT (guild, "user") DO UPDATE
				SET highlights = array_cat(h.highlights, EXCLUDED.highlights)
		""", guild, user, [highlight])

	async def delete_user_highlight(self, guild, user, highlight):
		await self.bot.pool.execute("""
			UPDATE highlights
			SET highlights = array_remove(highlights, $3)
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user, highlight)

	async def clear_user_highlights(self, guild, user):
		await self.bot.pool.execute("""
			DELETE FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user)

	async def import_user_highlights(self, source_guild, target_guild, user):
		await self.bot.pool.execute("""
			WITH source_highlights AS (COALESCE((
				SELECT highlights
				FROM highlights
				WHERE
					guild = $1
					AND "user" = $3),
				'{}'::TEXT[])),
			UPDATE highlights SET highlights = array_cat(highlights, source_highlights)
		""", source_guild, target_guild, user)

def setup(bot):
	bot.add_cog(Database(bot))
