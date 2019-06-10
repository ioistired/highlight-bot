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
import os.path
import re
from typing import DefaultDict, List, Tuple

import discord
from discord.ext import commands

import utils

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

# it's here to resolve a circular import
from bot import BASE_DIR

class DatabaseInterface:
	def __init__(self, bot):
		self.bot = bot
		self.pool = bot.pool
		with open(os.path.join(BASE_DIR, 'sql', 'queries.sql')) as f:
			self.queries = utils.load_sql(f)
		self.highlight_cache = utils.LRUDict(size=1_000)

	### Queries

	async def channel_highlights(self, channel):
		if channel.id in self.highlight_cache.get(channel.guild.id, {}):
			return self.highlight_cache[channel.guild.id][channel.id]

		highlight_users: DefaultDict[str, List[HighlightUser]] = defaultdict(list)
		async for user_id, highlight in self.cursor(
			self.queries.channel_highlights,
			channel.guild.id, (channel.id, getattr(channel.category, 'id', None))
		):
			# we store both lowercase and original case
			# so that the original case can eventually be displayed to the user
			highlight_users[highlight.lower()].append(HighlightUser(id=user_id, preferred_caps=highlight))

		for other_highlight_users, regex in self.highlight_cache.get(channel.guild.id, {}).values():
			if highlight_users == other_highlight_users:
				self.highlight_cache.setdefault(channel.guild.id, {})[channel.id] = ret = (other_highlight_users, regex)
				return ret

		self.highlight_cache.setdefault(channel.guild.id, {})[channel.id] = ret = (
			highlight_users, self._build_re(set(highlight_users.keys())))
		return ret

	def _build_re(self, highlights):
		return re.compile((
			r'(?i)'  # case insensitive
			r'\b'  # word bound
			r'(?:{})'  # non capturing group, to make sure that the word bound occurs before/after all words
			r'\b'
		).format('|'.join(map(re.escape, highlights))))

	async def user_highlights(self, guild, user):
		# tfw no "fetchvals"
		return [row['highlight'] for row in await self.pool.fetch(self.queries.user_highlights, guild, user)]

	async def blocks(self, user):
		return set([row['entity'] for row in await self.pool.fetch(self.queries.blocks, user)])

	async def blocked(self, user, entity):
		"""Return whether user has blocked entity"""
		return await self.pool.fetchval(self.queries.blocked, user, entity)

	### Actions

	async def add(self, guild, user, highlight):
		self._remove_from_cache(guild)
		async with self.pool.acquire() as conn, conn.transaction():
			await self._add_highlight_check(guild, user, highlight, connection=conn)
			await conn.execute(self.queries.add, guild, user, highlight)

	async def _add_highlight_check(self, guild, user, highlight, *, connection):
		if len(highlight) < 3:
			raise InvalidHighlightLength('Highlight word or phrase is too small.')
		if len(highlight) > 50:
			raise InvalidHighlightLength('Highlight word or phrase is too long.')

		count = await self.highlight_count(guild, user, connection=connection)
		if count > LIMIT:
			logger.error('highlight count for guild=%s user=%s exceeds limit of %d!', guild, user, LIMIT)
		if count >= LIMIT:
			raise TooManyHighlights('You have too many highlight words or phrases.')

	async def remove(self, guild, user, highlight):
		self._remove_from_cache(guild)
		await self.pool.execute(self.queries.remove, guild, user, highlight)

	async def clear(self, guild, user):
		self._remove_from_cache(guild)
		await self.pool.execute(self.queries.clear, guild, user)

	async def clear_guild(self, guild):
		self._remove_from_cache(guild)
		await self.pool.execute(self.queries.clear_guild, guild)

	async def import_(self, source_guild, target_guild, user):
		self._remove_from_cache(target_guild)
		async with self.pool.acquire() as conn, conn.transaction():
			await self._import_highlights_check(source_guild, target_guild, user, connection=conn)
			await conn.execute(self.queries.import_, source_guild, target_guild, user)

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
		return await (connection or self.pool).fetchval(self.queries.highlight_count, guild, user)

	async def block(self, guild, user, entity: int):
		self._remove_from_cache(guild, entity)
		await self.pool.execute(self.queries.block, user, entity)

	async def unblock(self, guild, user, entity: int):
		self._remove_from_cache(guild, entity)
		await self.pool.execute(self.queries.unblock, user, entity)

	async def delete_account(self, user):
		user = self.bot.get_user(user)
		if user is not None:
			for guild in self.bot.guilds:
				if guild.get_member(user.id):
					self._remove_from_cache(guild.id)

		async with self.pool.acquire() as conn, conn.transaction():
			for table in 'highlights', 'blocks':
				await conn.execute(self.queries.delete_by_user.format(table=table), user)

	def _remove_from_cache(self, guild_id, channel_id=None):
		if channel_id is not None:
			self.highlight_cache.get(guild_id, {}).pop(channel_id, None)
			return

		self.highlight_cache.pop(guild_id, None)

	async def cursor(self, query, *args):
		async with self.pool.acquire() as connection, connection.transaction():
			async for row in connection.cursor(query, *args):
				yield row
