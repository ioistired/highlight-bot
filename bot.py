#!/usr/bin/env python3
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

import contextlib
import logging
import os.path

import discord
import json5
import querypp
from bot_bin.bot import Bot
from discord.ext import commands

import utils

# has to go first to resolve import dependencies
BASE_DIR = os.path.dirname(__file__)

from cogs.db import HighlightError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('bot')

class CustomContext(commands.Context):
	async def try_add_reaction(self, emoji):
		with contextlib.suppress(discord.HTTPException):
			await self.message.add_reaction(emoji)

class HelpCommand(commands.MinimalHelpCommand):
	async def send_bot_help(self, mapping):
		cog = self.context.bot.get_cog('Highlight')
		if cog is None:
			await super().send_bot_help(mapping)
			return

		await self.send_cog_help(cog)

class HighlightBot(Bot):
	def __init__(self, *, config):
		self.jinja_env = querypp.QueryEnvironment('sql')
		super().__init__(
			description='DMs you when one of your configured words or phrases are said in chat.',
			help_command=HelpCommand(),
			config=config,
			setup_db=True)

	def process_config(self):
		super().process_config()
		success_emojis = self.config.get('success_or_failure_emojis')
		if success_emojis:
			utils.SUCCESS_EMOJIS = success_emojis

	def get_context(self, message, *, cls=None):
		return super().get_context(message, cls=cls or CustomContext)

	startup_extensions = (
		'cogs.highlight',
		'cogs.meta',
		'bot_bin.misc',
		'bot_bin.debug',
		'bot_bin.stats',
		'bot_bin.sql',
		'jishaku',
	)

if __name__ == '__main__':
	with open(os.path.join(BASE_DIR, 'config.json5')) as f:
		config = json5.load(f)

	HighlightBot(config=config).run()
