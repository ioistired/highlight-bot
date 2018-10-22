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

import logging
import re

import discord
from discord.ext import commands
from multidict import CIMultiDict

LIMIT = 10
logger = logging.getLogger(__name__)

class TooManyHighlights(commands.UserInputError):
	pass

class InvalidHighlightLength(commands.UserInputError):
	pass

class Database:
	def __init__(self, bot):
		self.bot = bot

	## Queries

	async def channel_highlights(self, channel):
		highlight_users = CIMultiDict()
		async for user, highlight in self.cursor("""
			SELECT "user", highlight
			FROM highlights
			WHERE
				guild = $1
				AND NOT EXISTS (
					SELECT 1
					FROM blocks
					WHERE entity = $2)
		""", channel.guild.id, channel.id):
			# allow multiple users to have the same highlight phrase
			highlight_users.add(highlight, user)

		return highlight_users, self.build_re(highlight_users.keys())

	async def user_highlights(self, guild, user):
		query = """
			SELECT highlight
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		"""
		# tfw no "fetchvals"
		return [row['highlight'] async for row in self.cursor(query, guild, user)]

	async def blocks(self, user):
		query = """
			SELECT entity
			FROM blocks
			WHERE "user" = $1
		"""
		return set([row['entity'] async for row in self.cursor(query, user)])

	@staticmethod
	def build_re(highlights):
		s = r'(?i)\b'  # case insensitive
		s += '|'.join(map(re.escape, highlights))
		s += r'\b'
		return s

	## Actions

	async def add(self, guild, user, highlight):
		await self._add_highlight_check(guild, user, highlight)

		await self.bot.pool.execute("""
			INSERT INTO highlights(guild, "user", highlight)
			VALUES ($1, $2, $3)
			ON CONFLICT DO NOTHING
		""", guild, user, highlight)

	async def _add_highlight_check(self, guild, user, highlight):
		if len(highlight) < 3:
			raise InvalidHighlightLength('Highlight word or phrase is too small.')
		if len(highlight) > 50:
			raise InvalidHighlightLength('Highlight word or phrase is too long.')

		count = await self.highlight_count(guild, user)
		if count > LIMIT:
			logger.error('highlight count for guild=%s user=%s exceeds limit of %d!', guild, user, LIMIT)
		if count >= LIMIT:
			raise TooManyHighlights('You have too many highlight words or phrases.')

	async def remove(self, guild, user, highlight):
		await self.bot.pool.execute("""
			DELETE FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
				AND LOWER(highlight) = LOWER($3)
		""", guild, user, highlight)

	async def clear(self, guild, user):
		await self.bot.pool.execute("""
			DELETE FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user)

	async def import_(self, source_guild, target_guild, user):
		await self._import_highlights_check(source_guild, target_guild, user)

		await self.bot.pool.execute("""
			INSERT INTO highlights (guild, "user", highlight)
			SELECT $2, "user", highlight
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $3
			ON CONFLICT DO NOTHING
		""", source_guild, target_guild, user)

	async def _import_highlights_check(self, source_guild, target_guild, user):
		source_guild_count = await self.highlight_count(source_guild, user)
		target_guild_count = await self.highlight_count(target_guild, user)
		total = source_guild_count + target_guild_count

		if total > LIMIT * 2:
			logger.error(
				'highlight count for guild in {%d, %d}, user=%d exceeds limit of %d!',
				source_guild,
				target_guild,
				user,
				LIMIT)
		if total >= LIMIT:
			raise TooManyHighlights('Import would place you over the maximum number of highlight words.')

	def highlight_count(self, guild, user):
		return self.bot.pool.fetchval("""
			SELECT COUNT(*)
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user)

	async def block(self, user, entity: int):
		await self.bot.pool.execute("""
			INSERT INTO blocks ("user", entity)
			VALUES ($1, $2)
			ON CONFLICT DO NOTHING
		""", user, entity)

	async def unblock(self, user, entity: int):
		await self.bot.pool.execute("""
			DELETE FROM blocks
			WHERE
				"user" = $1
				AND entity = $2
		""", user, entity)

	async def cursor(self, query, *args):
		async with self.bot.pool.acquire() as connection:
			async with connection.transaction():
				async for row in connection.cursor(query, *args):
					yield row

def setup(bot):
	bot.add_cog(Database(bot))
