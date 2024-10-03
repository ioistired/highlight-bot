# Copyright © @lambda.dance
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
		if size < 1:
			raise ValueError('size must be ≥1')
		super().__init__()
		self.size = size

	def __getitem__(self, key):
		try:
			self.move_to_end(key)
		except KeyError:
			pass
		return super().__getitem__(key)

	def __setitem__(self, key, value):
		super().__setitem__(key, value)
		self.move_to_end(key)
		if len(self) > self.size:
			self.popitem(last=False)

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

# this does not extend dict so that public method names, such as "clear"
# which may be desirable as keys, are not dispatched to the dict class
class AttrDict:
	def __init__(self, *args, **kwargs):
		self.__dict__.update(dict(*args, **kwargs))

	def __getitem__(self, key):
		try:
			return getattr(self, key)
		except AttributeError:
			raise KeyError(key)
	def __setitem__(self, key, value):
		setattr(self, key, value)
	def __delitem__(self, key):
		try:
			delattr(self, key)
		except AttributeError:
			raise KeyError(key)

# this function is Public Domain
# https://creativecommons.org/publicdomain/zero/1.0/
def load_sql(fp):
	"""given a file-like object, read the queries delimited by `-- :name foo` comment lines
	return a dict mapping these names to their respective SQL queries
	the file-like is not closed afterwards.
	"""
	# tag -> list[lines]
	queries = AttrDict()
	current_tag = ''

	for line in fp:
		match = re.match(r'\s*--\s*name:\s*(\S+).*?$', line)
		if match:
			current_tag = match[1]
		if current_tag:
			try:
				queries[current_tag].append(line)
			except KeyError:
				queries[current_tag] = l = []
				l.append(line)

	for tag, query in queries.__dict__.items():
		queries[tag] = ''.join(query)

	return queries

class _SymbolMeta(type):
	def __getattr__(cls, key):
		return cls(key)

class Symbol(metaclass=_SymbolMeta):
	"""Brings LISP style symbols to Python.

	Symbol.x is an interned object. You can use it as a replacement for sys.intern('x') or object() in argument
	defaults. Symbol('x') also works.
	"""

	__slots__ = 'name',

	_cache = {}

	def __new__(cls, name: str):
		try:
			return cls._cache[name]
		except KeyError:
			self = cls._cache[name] = super().__new__(cls)
			self.name = name
			return self

	def __hash__(self):
		return id(self)

	def __repr__(self):
		name = self.name
		cls_name = type(self).__qualname__
		if name.isidentifier():
			return f'{cls_name}.{name}'
		else:
			return f'{cls_name}({name!r})'
