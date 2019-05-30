# encoding: utf-8

# Copyright © 2018 Benjamin Mintz <bmintz@protonmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from collections import defaultdict, namedtuple
import logging
from typing import DefaultDict, List, Tuple

import discord
from discord.ext import commands

# max highlights per user
LIMIT = 10
logger = logging.getLogger(__name__)

class HighlightError(commands.UserInputError):
	pass

class TooManyHighlights(HighlightError):
	pass

class InvalidHighlightLength(HighlightError):
	pass

HighlightUser = namedtuple('HighlightUser', 'id preferred_caps')

class DatabaseInterface:
	def __init__(self, bot):
		self.pool = bot.pool

	### Queries

	async def channel_highlights(self, channel):
		highlight_users: DefaultDict[str, List[HighlightUser]] = defaultdict(list)
		async for user_id, highlight in self.cursor("""
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
		""", channel.guild.id, (channel.id, getattr(channel.category, 'id', None))):
			# we store both lowercase and original case
			# so that the original case can eventually be displayed to the user
			highlight_users[highlight.lower()].append(HighlightUser(id=user_id, preferred_caps=highlight))

		return highlight_users

	async def user_highlights(self, guild, user):
		# tfw no "fetchvals"
		return [row['highlight'] async for row in self.cursor("""
			SELECT highlight
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user)]

	async def blocks(self, user):
		return set([row['entity'] async for row in self.cursor("""
			SELECT entity
			FROM blocks
			WHERE "user" = $1
		""", user)])

	def blocked(self, user, entity):
		"""Return whether user has blocked entity"""
		return self.pool.fetchval("""
			SELECT true
			FROM blocks
			WHERE
				"user" = $1
				AND entity = $2
		""", user, entity)

	### Actions

	async def add(self, guild, user, highlight):
		await self._add_highlight_check(guild, user, highlight)

		await self.pool.execute("""
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
		await self.pool.execute("""
			DELETE FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
				AND LOWER(highlight) = LOWER($3)
		""", guild, user, highlight)

	async def clear(self, guild, user):
		await self.pool.execute("""
			DELETE FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user)

	async def clear_guild(self, guild):
		await self.pool.execute("""
			DELETE FROM highlights
			WHERE guild = $1
		""", guild)

	async def import_(self, source_guild, target_guild, user):
		await self._import_highlights_check(source_guild, target_guild, user)

		await self.pool.execute("""
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
		return self.pool.fetchval("""
			SELECT COUNT(*)
			FROM highlights
			WHERE
				guild = $1
				AND "user" = $2
		""", guild, user)

	async def block(self, user, entity: int):
		await self.pool.execute("""
			INSERT INTO blocks ("user", entity)
			VALUES ($1, $2)
			ON CONFLICT DO NOTHING
		""", user, entity)

	async def unblock(self, user, entity: int):
		await self.pool.execute("""
			DELETE FROM blocks
			WHERE
				"user" = $1
				AND entity = $2
		""", user, entity)

	async def delete_account(self, user):
		for table in 'highlights', 'blocks':
			await self.pool.execute(f'DELETE FROM {table} WHERE "user" = $1', user)

	async def cursor(self, query, *args):
		async with self.pool.acquire() as connection, connection.transaction():
			async for row in connection.cursor(query, *args):
				yield row
