# encoding: utf-8

"""
Copyright © 2018 Benjamin Mintz <bmintz@protonmail.com>

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import re

from multidict import CIMultiDict

class Database:
	def __init__(self, bot):
		self.bot = bot

	async def get_channel_highlights(self, channel):
		highlight_users = CIMultiDict()
		async for user, highlight in self.cursor("""
			-- TODO incorporate blocks
			SELECT "user", highlight
			FROM highlights
			WHERE guild = $1
		""", channel.guild.id):
			# allow multiple users to have the same highlight phrase
			highlight_users.add(highlight, user)

		return highlight_users, self.build_re(highlight_users.keys())

	@staticmethod
	def build_re(highlights):
		s = r'(?i)\b'  # case insensitive
		s += '|'.join(map(re.escape, highlights))
		s += r'\b'
		return s

	async def get_user_highlights(self, guild, user):
		async for row in self.cursor("""
			SELECT highlight
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user):
			yield row['highlight']

	async def add_user_highlight(self, guild, user, highlight):
		await self.bot.pool.execute("""
			INSERT INTO highlights(guild, "user", highlight)
			VALUES ($1, $2, $3)
			ON CONFLICT DO NOTHING
		""", guild, user, highlight)

	async def delete_user_highlight(self, guild, user, highlight):
		await self.bot.pool.execute("""
			UPDATE highlights
			SET highlights = array_remove(highlights, $3)
			WHERE
				guild = $1
				AND "user" = $2
				AND LOWER(highlight) = LOWER($3)
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
			INSERT INTO highlights (guild, "user", highlight)
			SELECT $2, "user", highlight
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $3
			ON CONFLICT DO NOTHING
		""", source_guild, target_guild, user)

	async def cursor(self, query, *args):
		async with self.bot.pool.acquire() as connection:
			async with connection.transaction():
				async for row in connection.cursor(query, *args):
					yield row

def setup(bot):
	bot.add_cog(Database(bot))
