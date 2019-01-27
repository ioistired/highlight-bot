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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.	If not, see <https://www.gnu.org/licenses/>.

import asyncio
import collections
import inspect
import functools

import discord.utils
from discord.ext import commands

SUCCESS_EMOJIS = {False: '❌', True: '✅'}

class HelpFormatter(commands.HelpFormatter):
	def get_command_signature(self):
		return '`' + super().get_command_signature() + '`'

	def get_ending_note(self):
		command_name = self.context.invoked_with
		return (
			"Type `{0}{1}` command for more info on a command.\n"
			"You can also type `{0}{1}` category for more info on a category.".format(self.clean_prefix, command_name))

	def _add_subcommands_to_page(self, max_width, commands):
		for name, command in commands:
			if name in command.aliases:
				# skip aliases
				continue

			self._paginator.add_line(f'**{name}**')
			self._paginator.add_line(command.short_doc)

	async def format(self):
		"""Handles the actual behaviour involved with formatting.

		Returns
		--------
		list
			A paginated output of the help command.
		"""
		# XXX UnboundedLocalError if we don't do this??
		# but if i do discord.ext.commands without `global commands` it works???
		global commands
		self._paginator = commands.Paginator(prefix='', suffix='')

		description = (
			self.command.description and f'*{self.command.description}*'
			if not self.is_cog()
			else inspect.getdoc(self.command))

		if description:
			# <description> portion
			self._paginator.add_line(description, empty=True)

		if isinstance(self.command, commands.Command):
			# <signature portion>
			signature = self.get_command_signature()
			self._paginator.add_line(signature, empty=True)

			# <long doc> section
			if self.command.help:
				self._paginator.add_line(self.command.help, empty=True)

			# end it here if it's just a regular command
			if not self.has_subcommands():
				self._paginator.close_page()
				return self._paginator.pages

		max_width = self.max_name_size

		def category(tup):
			cog = tup[1].cog_name
			# we insert the zero width space there to give it approximate
			# last place sorting position.
			return f'**{cog}:**' if cog is not None else '\u200b**No Category:**'

		filtered = await self.filter_command_list()
		if self.is_bot():
			data = sorted(filtered, key=category)
			for category, commands in itertools.groupby(data, key=category):
				# there simply is no prettier way of doing this.
				commands = sorted(commands)
				if len(commands) > 0:
					self._paginator.add_line(category)

				self._add_subcommands_to_page(max_width, commands)
		else:
			filtered = sorted(filtered)
			if filtered:
				self._paginator.add_line('Commands:')
				self._add_subcommands_to_page(max_width, filtered)

		# add the ending note
		self._paginator.add_line()
		ending_note = self.get_ending_note()
		self._paginator.add_line(ending_note)
		return self._paginator.pages

class LRUDict(collections.OrderedDict):
	"""a dictionary with fixed size, sorted by last use"""

	def __init__(self, size):
		super().__init__()
		self.size = size

	def __getitem__(self, key):
		# move key to the end
		result = super().__getitem__(key)
		del self[key]
		super().__setitem__(key, result)
		return result

	def __setitem__(self, key, value):
		try:
			# if an entry exists at key, make sure it's moved up
			del self[key]
		except KeyError:
			# we only need to do this when adding a new key
			if len(self) >= self.size:
				self.popitem(last=False)

		super().__setitem__(key, value)

def asyncexecutor(*, timeout=None, loop=None, executor=None):
	"""decorator that turns a synchronous function into an async one

	Created by @Arqm#9302 (ID 325012556940836864). XXX Unknown license
	"""
	def decorator(func):
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			nonlocal loop  # have to do this to fix the `loop = loop or` UnboundLocalError

			partial = functools.partial(func, *args, **kwargs)
			loop = loop or asyncio.get_event_loop()

			coro = loop.run_in_executor(executor, partial)
			# don't need to check if timeout is None since wait_for will just "block" in that case anyway
			return asyncio.wait_for(coro, timeout=timeout, loop=loop)
		return wrapper
	return decorator

class Guild(commands.Converter):
	@staticmethod
	async def convert(context, argument):
		try:
			id = int(argument)
		except ValueError:
			pass
		else:
			guild = context.bot.get_guild(id)
			if guild:
				return guild

		guild = discord.utils.get(context.bot.guilds, name=argument)
		if guild:
			return guild
		raise commands.BadArgument('Server not found.')
