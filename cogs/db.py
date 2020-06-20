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
from typing import DefaultDict, List, Optional, Tuple

import discord
import lacbd
from discord.ext import commands

import utils

# minimum length in characters of a highlight keyword
# TODO count grapheme clusters instead?
MIN_HIGHLIGHT_LENGTH = 2
MAX_HIGHLIGHT_LENGTH = 200
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
		self.bot = bot
		self.pool = bot.pool
		self.queries = bot.queries('highlight.sql')
		self.highlight_cache = utils.LRUDict(size=1_000)

	### Queries

	async def channel_highlights(self, channel) -> Optional[lacbd.Searcher]:
		if channel.id in self.highlight_cache.get(channel.guild.id, {}):
			return self.highlight_cache[channel.guild.id][channel.id]

		highlight_users: DefaultDict[str, List[HighlightUser]] = defaultdict(list)
		async for user_id, highlight in self.cursor(
			self.queries.channel_highlights(),
			channel.guild.id, (channel.id, getattr(channel.category, 'id', None))
		):
			# we store both lowercase and original case
			# so that the original case can eventually be displayed to the user
			highlight_users[highlight.lower()].append(HighlightUser(id=user_id, preferred_caps=highlight))

		if not highlight_users:
			searcher = None
		else:
			self.highlight_cache.setdefault(channel.guild.id, {})[channel.id] = searcher \
				= lacbd.Searcher(highlight_users.items())

		return searcher

	async def user_highlights(self, guild, user):
		# tfw no "fetchvals"
		return [row['highlight'] for row in await self.pool.fetch(self.queries.user_highlights(), guild, user)]

	async def blocks(self, user):
		return set([row['entity'] for row in await self.pool.fetch(self.queries.blocks(), user)])

	async def blocked(self, user, entity):
		"""Return whether user has blocked entity"""
		return await self.pool.fetchval(self.queries.blocked(), user, entity)

	### Actions

	async def add(self, guild, user, highlight):
		self._remove_from_cache(guild)
		async with self.pool.acquire() as conn, conn.transaction():
			await self._add_highlight_check(guild, user, highlight, connection=conn)
			await conn.execute(self.queries.add(), guild, user, highlight)

	async def _add_highlight_check(self, guild, user, highlight, *, connection):
		if len(highlight) < MIN_HIGHLIGHT_LENGTH:
			raise InvalidHighlightLength('Highlight word or phrase is too small.')
		if len(highlight) > MAX_HIGHLIGHT_LENGTH:
			raise InvalidHighlightLength('Highlight word or phrase is too long.')

		count = await self.highlight_count(guild, user, connection=connection)
		if count > LIMIT:
			logger.error('highlight count for guild=%s user=%s exceeds limit of %d!', guild, user, LIMIT)
		if count >= LIMIT:
			raise TooManyHighlights('You have too many highlight words or phrases.')

	async def remove(self, guild, user, highlight):
		self._remove_from_cache(guild)
		await self.pool.execute(self.queries.remove(), guild, user, highlight)

	async def clear(self, guild, user):
		self._remove_from_cache(guild)
		await self.pool.execute(self.queries.clear(), guild, user)

	async def clear_guild(self, guild):
		self._remove_from_cache(guild)
		await self.pool.execute(self.queries.clear_guild(), guild)

	async def import_(self, source_guild, target_guild, user):
		self._remove_from_cache(target_guild)
		async with self.pool.acquire() as conn, conn.transaction():
			await self._import_highlights_check(source_guild, target_guild, user, connection=conn)
			await conn.execute(self.queries.import_(), source_guild, target_guild, user)

	async def _import_highlights_check(self, source_guild, target_guild, user, *, connection):
		source_guild_count = await self.highlight_count(source_guild, user, connection=connection)
		target_guild_count = await self.highlight_count(target_guild, user, connection=connection)
		total = source_guild_count + target_guild_count

		if total > LIMIT * 2:
			logger.error(
				'highlight count (%d) for guild in {%d, %d}, user=%d exceeds limit of %d!',
				total,
				source_guild,
				target_guild,
				user,
				LIMIT)
		if total >= LIMIT:
			raise TooManyHighlights('Import would place you over the maximum number of highlight words.')

	async def highlight_count(self, guild, user, *, connection=None):
		return await (connection or self.pool).fetchval(self.queries.highlight_count(), guild, user)

	async def block(self, guild, user, entity: int):
		self._remove_from_cache(guild, entity)
		await self.pool.execute(self.queries.block(), user, entity)

	async def unblock(self, guild, user, entity: int):
		self._remove_from_cache(guild, entity)
		await self.pool.execute(self.queries.unblock(), user, entity)

	async def delete_account(self, user):
		user = self.bot.get_user(user)
		if user is not None:
			for guild in self.bot.guilds:
				if guild.get_member(user.id):
					self._remove_from_cache(guild.id)

		async with self.pool.acquire() as conn, conn.transaction():
			for table in 'highlights', 'blocks':
				await conn.execute(self.queries.delete_by_user.format(table=table), user.id)

	def _remove_from_cache(self, guild_id, channel_id=None):
		if channel_id is not None:
			self.highlight_cache.get(guild_id, {}).pop(channel_id, None)
			return

		self.highlight_cache.pop(guild_id, None)

	async def cursor(self, query, *args):
		async with self.pool.acquire() as connection, connection.transaction():
			async for row in connection.cursor(query, *args):
				yield row
