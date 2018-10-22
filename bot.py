#!/usr/bin/env python3
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

import asyncio
import contextlib
import logging
import os.path
import re
import uuid

import asyncpg
import discord
from discord.ext import commands
import json5

BASE_DIR = os.path.dirname(__file__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HighlightBotBase(commands.bot.BotBase):
	def __init__(self, *, config):
		self.config = config
		self._process_config()

		self.db_ready = asyncio.Event()

		super().__init__(
			command_prefix=self.get_prefix_,
			description='DMs you when certain words are said in chat.')

	def get_prefix_(self, bot, message):
		prefixes = ()
		mention_match = re.search(fr'({bot.user.mention}|<@!{bot.user.id}>)\s+', message.content)
		if mention_match:
			prefixes += (mention_match[0],)

		match = re.search(fr'{self.config["prefix"]}', message.content, re.IGNORECASE)

		if match is not None:
			prefixes += (match[0],)

		if not prefixes:
			# something that's guaranteed to not be in the message
			# because we have to return *something*
			# annoying af
			return str(uuid.uuid4())

		return prefixes

	def _process_config(self):
		for key in 'guilds', 'channels':
			self.config['ignore_bots']['overrides'][key] = (
				frozenset(self.config['ignore_bots']['overrides'][key]))

	async def on_ready(self):
		await self.change_presence(activity=self.game)

		logger.info('Logged in as: %s', self.user)
		logger.info('ID: %s', self.user.id)

	@property
	def game(self):
		return discord.Game(name=self._formatted_prefix() + 'help')

	def _formatted_prefix(self):
		prefix = self.config['prefix']
		if prefix is None:
			prefix = f'@{self.user.name} '
		return prefix

	async def on_message(self, message):
		if self.should_reply(message):
			await self.process_commands(message)

	async def process_commands(self, message):
		# overridden because the default process_commands now ignores bots
		context = await self.get_context(message)
		await self.invoke(context)

	def should_reply(self, message):
		return not (
			message.author == self.user
			or (message.author.bot and not self._should_reply_to_bot(message))
			or not message.content)

	def _should_reply_to_bot(self, message):
		should_reply = not self.config['ignore_bots'].get('default', True)
		overrides = self.config['ignore_bots']['overrides']

		def check_overrides(location, overrides_key):
			return location and location.id in overrides[overrides_key]

		if check_override(message.guild, 'guilds') or check_override(message.channel, 'channels'):
			should_reply = not should_reply

		return should_reply

	# https://github.com/Rapptz/RoboDanny/blob/ca75fae7de132e55270e53d89bc19dd2958c2ae0/bot.py#L77-L85
	async def on_command_error(self, context, error):
		if isinstance(error, commands.NoPrivateMessage):
			await context.author.send('This command cannot be used in private messages.')
		elif isinstance(error, commands.DisabledCommand):
			message = 'Sorry. This command is disabled and cannot be used.'
			try:
				await context.author.send(message)
			except discord.Forbidden:
				await context.send(message)
		elif isinstance(error, commands.NotOwner):
			logger.error('%s tried to run %s but is not the owner', context.author, context.command.name)
			with contextlib.suppress(discord.HTTPException):
				await context.try_add_reaction(utils.SUCCESS_EMOJIS[False])
		elif isinstance(error, (commands.UserInputError, commands.CheckFailure)):
			await context.send(error)
		elif isinstance(error, commands.CommandInvokeError):
			logger.error('"%s" caused an exception', context.message.content)
			logger.error(''.join(traceback.format_tb(error.original.__traceback__)))
			# pylint: disable=logging-format-interpolation
			logger.error('{0.__class__.__name__}: {0}'.format(error.original))

			await context.send('An internal error occured while trying to run that command.')

	async def start(self):
		await self._init_db()
		self._load_extensions()

		await super().start(self.config['tokens'].pop('discord'))

	async def _init_db(self):
		credentials = self.config['database']
		pool = await asyncpg.create_pool(**credentials)

		with open(os.path.join(BASE_DIR, 'schema.sql')) as f:
			await pool.execute(f.read())

		self.pool = pool
		self.db_ready.set()

	def _load_extensions(self):
		for extension in self.config['startup_extensions']:
			self.load_extension(extension)
			logger.info('Successfully loaded %s', extension)

	async def logout(self):
		with contextlib.suppress(AttributeError):
			await self.pool.close()
		await super.logout()

class HighlightBot(HighlightBotBase, discord.Client):
	pass

class AutoShardedHighlightBot(HighlightBotBase, discord.AutoShardedClient):
	pass

if __name__ == '__main__':
	with open(os.path.join(BASE_DIR, 'config.json5')) as f:
		config = json5.load(f)

	cls = AutoShardedHighlightBot if config['sharded'] else HighlightBot
	bot = cls(config=config)
	bot.run()
