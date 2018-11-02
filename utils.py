# encoding: utf-8

import asyncio
import collections
import functools

SUCCESS_EMOJIS = {False: '❌', True: '✅'}

class LRUDict(collections.OrderedDict):
	"""a dictionary with fixed size, sorted by last use"""

	def __init__(self, size):
		super().__init__()
		self.size = size

	def __getitem__(self, key):
		# move key to the end
		result = self.pop(key)
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
