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

import asyncio
import collections
import contextlib
from datetime import datetime
import re
import typing

import autoslot
import discord
from discord.ext import commands

import utils

Entity = typing.Union[discord.Member, discord.TextChannel, discord.CategoryChannel]
# how many seconds after a user is active in a channel before they are no longer considered "recently spoken"
LAST_SPOKEN_CUTOFF = 10
# how many seconds to wait for new messages after a user has been highlighted
NEW_MESSAGES_DELAY = 10

def guild_only_command(*args, **kwargs):
	def wrapper(func):
		# wooo, currying
		return commands.guild_only()(commands.command(*args, **kwargs)(func))
	return wrapper

class Highlight:
	def __init__(self, bot):
		self.bot = bot
		self.db_cog = self.bot.get_cog('Database')
		self.recently_spoken = utils.LRUDict(size=1_000)

		for event in 'on_raw_reaction_add', 'on_raw_reaction_remove':
			self.bot.add_listener(self.on_raw_reaction, event)

	### Events

	async def on_message(self, message):
		if not message.guild or not self.bot.should_reply(message):
			return

		self.recently_spoken[message.channel.id, message.author.id] = message.created_at

		async for highlighted_user, highlight in self.HighlightFinder(self.bot, message):
			info = message.channel.id, highlighted_user.id
			if not self.has_recently_spoken(info):
				# add to the dict first since notify may sleep
				# this is to prevent two messages sent in immediate succession
				# from notifying the user twice
				self.recently_spoken[info] = datetime.utcnow()
				await self.notify(highlighted_user, highlight, message)

	def has_recently_spoken(self, info, *, delay=LAST_SPOKEN_CUTOFF):
		try:
			return (datetime.utcnow() - self.recently_spoken[info]).total_seconds() < delay
		except KeyError:
			# if they haven't spoken at all, then they also haven't spoken recently
			return False

	async def on_typing(self, channel, user, when):
		self.track_spoken(channel.guild and channel.guild.id, channel.id, user.id, when)

	async def on_raw_reaction(self, payload):
		self.track_spoken(payload.guild_id, payload.channel_id, payload.user_id, datetime.utcnow())

	def track_spoken(self, guild_id, channel_id, user_id, time):
		if not guild_id:
			return

		if (datetime.utcnow() - time).total_seconds() < LAST_SPOKEN_CUTOFF:
			self.recently_spoken[channel_id, user_id] = time

	# we use a class to have shared state which is isolated from the cog
	# we use a nested class so as to have HighlightUser defined close to where it's used
	class HighlightFinder(metaclass=autoslot.SlotsMeta):
		__slots__ = {'highlight_users'}

		def __init__(self, bot, message):
			self.bot = bot
			self.db_cog = self.bot.get_cog('Database')
			self.message = message
			self.seen_users = set()

		async def __aiter__(self):
			highlight_users = await self.db_cog.channel_highlights(self.message.channel)
			if not highlight_users:
				return
			self.highlight_users = highlight_users

			regex = self.build_re(set(self.highlight_users.keys()))

			for match in re.finditer(regex, self.message.clean_content):
				highlight = match[0]
				async for user in self.users_highlighted_by(highlight):
					yield user, highlight

		async def users_highlighted_by(self, highlight):
			for user in self.highlight_users.getall(highlight):
				user = self.bot.get_user(user) or await self.bot.get_user_info(user)

				if await self.should_notify_user(user, highlight):
					yield user

		async def should_notify_user(self, user, highlight):
			"""assuming that highlight was found in the message, return whether to notify the user"""
			if await self.blocked(user):
				return False

			if user not in self.seen_users and user != self.message.author:
				self.seen_users.add(user)
				return True
			return False

		async def blocked(self, user):
			"""return whtether the highlightee is blocked by the highlighter"""
			# we only have to check if the *user* is blocked here bc the database filters out blocked channels
			return user in await self.db_cog.blocks(self.message.author.id)

		@staticmethod
		def build_re(highlights):
			s  = r'(?i)'  # case insensitive
			s += r'\b'  # word bound
			s += r'(?:'  # begin non-capturing group, to make sure that the word bound occurs before/after all words
			s += r'|'.join(map(re.escape, highlights))
			s += r')'
			s += r'\b'
			return s

	@classmethod
	async def notify(cls, user, highlight, message):
		# allow new messages to come in so the user gets some more context
		await asyncio.sleep(cls.time_difference_needed(message.created_at, NEW_MESSAGES_DELAY))

		message = await cls.notification_message(user, highlight, message)
		with contextlib.suppress(discord.HTTPException):
			await user.send(**message)

	@staticmethod
	def time_difference_needed(time: datetime, max_delay: float):
		"""return the number of seconds needed to ensure that max_delay seconds have elapsed since time"""
		diff = max(0, (datetime.utcnow() - time).total_seconds())
		return max_delay-diff

	@classmethod
	async def notification_message(cls, user, highlight, message):
		"""Create an embed message to send to the user for being highlighted

		Here's what it looks like:
		https://dingo.csdisaster.club/~ben/highlight-notification-example.png
		"""

		content = (
			f'In {message.channel.mention} for server {message.guild.name}, '
			f'you were mentioned with highlight word **{highlight}**')

		embed = discord.Embed()
		embed.color = discord.Color.blurple()
		embed.title = highlight
		embed.description = await cls.embed_description(message)
		embed.set_author(name=message.author.name, icon_url=message.author.avatar_url_as(format='png', size=64))

		embed.set_footer(text='Triggered')	# "Triggered today at 21:21"
		embed.timestamp = message.created_at

		return dict(content=content, embed=embed)

	@classmethod
	async def embed_description(cls, message):
		orig_message = message
		formatted_messages = '\n'.join([
			cls.format_message(message, is_highlight=message.id == orig_message.id)
			async for message in message.channel.history(around=message, limit=8, reverse=True)])

		return '\n\n'.join((formatted_messages, f'[Original message]({message.jump_url})'))

	@staticmethod
	def format_message(message, *, is_highlight: bool):
		date = message.created_at.strftime('[%I:%M:%S %p UTC]')
		date = f'**{date}**' if is_highlight else date
		formatted = f'{date} {message.author}: {message.content}'
		return formatted

	### Commands

	@guild_only_command(aliases=['list'])
	async def show(self, context):
		"""Shows all your highlights words or phrases."""
		self.delete_later(context.message)

		highlights = await self.db_cog.user_highlights(context.guild.id, context.author.id)
		if not highlights:
			return await context.send('You do not have any highlight words or phrases set up.')

		embed = self.author_embed(context.author)
		embed.title = 'Triggers'
		embed.description = '\n'.join(highlights)
		embed.set_footer(text=f'{len(highlights)} triggers')

		await context.send(embed=embed, delete_after=15)

	@guild_only_command(usage='<word or phrase>')
	async def add(self, context, *, highlight):
		"""Adds a highlight word or phrase.

		Highlight words and phrases are not case-sensitive,
		so coffee, Coffee, and COFFEE will all notify you.

		When a highlight word is found, the bot will send you
		a private message with the message that triggered it
		along with context.

		To prevent abuse of the service, you may only have up to 10
		highlight word or phrases.
		"""
		self.delete_later(context.message)
		try:
			await self.db_cog.add(context.guild.id, context.author.id, highlight)
		except commands.UserInputError:
			await context.try_add_reaction(utils.SUCCESS_EMOJIS[False])
			raise
		else:
			await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command(usage='<word or phrase>')
	async def remove(self, context, *, highlight):
		"""Removes a previously registered highlight word or phrase.

		Highlight words and phrases are not case-sensitive,
		so coffee, Coffee, and COFFEE will all notify you.
		"""
		self.delete_later(context.message)
		await self.db_cog.remove(context.guild.id, context.author.id, highlight)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@commands.command(aliases=['blocks'])
	async def blocked(self, context):
		"""Shows you the users or channels that you have globally blocked."""
		entities = tuple(map(self.format_entity, await self.db_cog.blocks(context.author.id)))

		embed = self.author_embed(context.author)
		embed.title = 'Blocked'
		embed.description='\n'.join(entities)
		embed.set_footer(text=f'{len(entities)} entities blocked')

		await context.send(embed=embed)

	def format_entity(self, entity):
		channel = self.bot.get_channel(entity)
		if channel:
			if isinstance(channel, discord.CategoryChannel):
				return f'📂 {channel.name}'
			return f'🗨️ {channel.mention}'

		user = self.bot.get_user(entity)
		if user:
			return f'👤 {user.mention}'

		return f'❔ {entity}'

	@staticmethod
	def author_embed(author):
		embed = discord.Embed()
		embed.set_author(name=author.name, icon_url=author.avatar_url_as(format='png', size=64))
		return embed

	@guild_only_command()
	async def block(self, context, *, entity: Entity):
		"""Blocks a member, channel, or channel category from highlighting you.

		This is functionally equivalent to the Discord block feature,
		which blocks them globally. This is not a per-server block.
		"""
		self.delete_later(context.message)
		await self.db_cog.block(context.author.id, entity.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command()
	async def unblock(self, context, *, entity: Entity):
		"""Unblocks a member or channel from mentioning you.

		This reverts a previous block action.
		"""
		self.delete_later(context.message)
		await self.db_cog.unblock(context.author.id, entity.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command()
	async def clear(self, context):
		"""Removes all your highlight words or phrases."""
		self.delete_later(context.message)
		await self.db_cog.clear(context.guild.id, context.author.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command(name='import')
	async def import_(self, context, *, server: utils.Guild):
		"""Imports your highlight words from another server.

		This is a copy operation, so if you remove a highlight word
		from the other server later, it is not reflected in the new
		server.

		You can provide the server either by ID or by name. Names are case-sensitive.
		"""
		self.delete_later(context.message)
		try:
			await self.db_cog.import_(source_guild=server.id, target_guild=context.guild.id, user=context.author.id)
		except commands.UserInputError:
			await context.try_add_reaction(utils.SUCCESS_EMOJIS[False])
			raise
		else:
			await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@commands.command(name='delete-my-account')
	async def delete_my_account(self, context):
		"""Deletes all information I have on you.

		This will delete:
			• All your highlight words or phrases, from every server.
			• All your blocks
		"""

		confirmation_phrase = 'Yes, delete my account.'
		prompt = (
			 'Are you sure you want to delete your account? '
			f'To confirm, please say “{confirmation_phrase}” exactly.')

		if not await self.confirm(context, prompt, confirmation_phrase):
			return

		await self.db_cog.delete_account(context.author.id)
		await context.send(f"{context.author.mention} I've deleted your account successfully.")

	async def confirm(self, context, prompt, required_phrase, *, timeout=30):
		await context.send(prompt)

		def check(message):
			return (
				message.author == context.author
				and message.channel == context.channel
				and message.content == required_phrase)

		try:
			await self.bot.wait_for('message', check=check, timeout=timeout)
		except asyncio.TimeoutError:
			await context.send('Confirmation phrase not received in time. Please try again.')
			return False
		else:
			return True

	def delete_later(self, message, delay=5):
		async def delete_after():
			await asyncio.sleep(delay)
			with contextlib.suppress(discord.HTTPException):
				await message.delete()
		self.bot.loop.create_task(delete_after())

def setup(bot):
	bot.add_cog(Highlight(bot))
