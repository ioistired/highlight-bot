# encoding: utf-8

import asyncio
import functools

SUCCESS_EMOJIS = {False: '❌', True: '✅'}

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
