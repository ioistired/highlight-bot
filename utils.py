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

import collections
import functools
import re

import discord.utils
from discord.ext import commands

SUCCESS_EMOJIS = {False: '❌', True: '✅'}

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

attrdict = type('attrdict', (dict,), {
	'__getattr__': dict.__getitem__,
	'__setattr__': dict.__setitem__,
	'__delattr__': dict.__delitem__})

# this function is Public Domain
# https://creativecommons.org/publicdomain/zero/1.0/
def load_sql(fp):
	"""given a file-like object, read the queries delimited by `-- :name foo` comment lines
	return a dict mapping these names to their respective SQL queries
	the file-like is not closed afterwards.
	"""
	# tag -> list[lines]
	queries = attrdict()
	current_tag = ''

	for line in fp:
		match = re.match(r'\s*--\s*name:\s*(\S+).*?$', line)
		if match:
			current_tag = match[1]
		if current_tag:
			queries.setdefault(current_tag, []).append(line)

	for tag, query in queries.items():
		queries[tag] = ''.join(query)

	return queries
