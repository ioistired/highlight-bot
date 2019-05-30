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
import functools
import operator
import re
import typing

import autoslot
import discord
from discord.ext import commands

from cogs.db import DatabaseInterface
import utils

User = typing.Union[discord.Member, discord.User]
Entity = typing.Union[User, discord.TextChannel, discord.CategoryChannel]
# how many seconds after a user is active in a channel before they are no longer considered active in that channel
INACTIVITY_CUTOFF = 10
# how many seconds to wait for new messages after a user has been highlighted
NEW_MESSAGES_DELAY = 10
# how many seconds to wait before command messages sent by the user and our replies to them
DELETE_AFTER = 5
# how many seconds to wait before deleting long messages, such as lists
DELETE_LONG_AFTER = 15

def guild_only_command(*args, **kwargs):
	def wrapper(func):
		# wooo, currying
		return commands.guild_only()(commands.command(*args, **kwargs)(func))
	return wrapper

class Highlight(commands.Cog):
	def __init__(self, bot):
		self.bot = bot
		self.db = DatabaseInterface(self.bot)
		self.recently_active = utils.LRUDict(size=1_000)

	### Events

	@commands.Cog.listener()
	async def on_message(self, message):
		if not message.guild or not self.bot.should_reply(message):
			return

		self.track_user_activity(message.channel.id, message.author.id, message.created_at)

		async for highlighted_user, highlight in self.HighlightFinder(bot=self.bot, message=message, db=self.db):
			info = message.channel.id, highlighted_user.id
			if not self.was_recently_active(info):
				# add to the dict first to prevent other message events from notifying as well
				# this is to prevent two messages sent in immediate succession
				# from notifying the user twice
				self.recently_active[info] = datetime.utcnow()

				await self.notify_if_user_is_inactive(highlighted_user, highlight, message)

	def track_user_activity(self, channel_id, user_id, when):
		if (datetime.utcnow() - when).total_seconds() < INACTIVITY_CUTOFF:
			self.bot.dispatch('user_activity', channel_id, user_id, when)

	@commands.Cog.listener()
	async def on_user_activity(self, channel_id, user_id, when):
		"""dispatched whenever a user does something that would cause them to see recent messages in channel_id"""
		self.recently_active[channel_id, user_id] = when

	async def notify_if_user_is_inactive(self, highlighted_user, highlight, message):
		# allow new messages to come in so the user gets some more context
		time_needed = self.time_difference_needed(message.created_at, NEW_MESSAGES_DELAY)

		try:
			await self.bot.wait_for('user_activity',
				check=lambda channel_id, user_id, when:
					channel_id == message.channel.id
					and user_id == highlighted_user.id,
				timeout=time_needed)
		except asyncio.TimeoutError:
			# no activity received in time
			await self.notify(highlighted_user, highlight, message)

	@commands.Cog.listener()
	async def on_member_remove(self, member):
		await self.db.clear(member.guild.id, member.id)

	@commands.Cog.listener()
	async def on_guild_leave(self, guild):
		await self.db.clear_guild(guild.id)

	def was_recently_active(self, info, *, delay=INACTIVITY_CUTOFF):
		try:
			return (datetime.utcnow() - self.recently_active[info]).total_seconds() < delay
		except KeyError:
			# if they haven't spoken at all, then they also haven't spoken recently
			return False

	@commands.Cog.listener()
	async def on_typing(self, channel, user, when):
		self.track_user_activity(channel.id, user.id, when)

	@commands.Cog.listener(name='on_raw_reaction_add')
	@commands.Cog.listener(name='on_raw_reaction_remove')
	async def on_raw_reaction(self, payload):
		# assume that a user reacting to a message sent an hour ago, has seen the channel an hour ago
		# but track it in case the user reacts to a message sent 3 seconds ago
		# in practice this technique is not ideal, because: if the user sees a message created 3 hours ago,
		# but that message is the most recent message in a given channel, they should not be highlighted either
		# but it's expensive to determine whether this message is the last message.
		message_creation = discord.utils.snowflake_time(payload.message_id)
		self.track_user_activity(payload.channel_id, payload.user_id, message_creation)

	# we use a class to have shared state which is isolated from the cog
	# we use a nested class so as to have HighlightUser defined close to where it's used
	class HighlightFinder(metaclass=autoslot.SlotsMeta):
		__slots__ = {'highlight_users'}

		def __init__(self, *, bot, message, db):
			self.bot = bot
			self.db = db
			self.message = message
			self.author_id = self.message.author.id
			self.seen_users = set()

		async def __aiter__(self):
			highlight_users = await self.db.channel_highlights(self.message.channel)
			if not highlight_users:
				return

			regex = self.build_re(set(highlight_users.keys()))
			content = self.remove_mentions(self.message.content)

			for highlight in map(operator.itemgetter(0), re.finditer(regex, content)):
				for user in highlight_users.getall(highlight):
					user = self.bot.get_user(user) or await self.bot.fetch_user(user)

					if await self.should_notify_user(user, highlight):
						yield user, highlight

		async def should_notify_user(self, user, highlight):
			"""assuming that a highlight was found in the message, return whether to notify the user"""
			if not self.message.guild.get_member(user.id):
				# the user appears to have left the guild
				return False

			if user == self.message.author:
				# users may not highlight themselves
				return False

			if await self.blocked(user):
				return False

			if user in self.message.mentions:
				# pinging someone should not also highlight them
				return False

			if user in self.seen_users:
				# this user has already been highlighted for this message
				return False

			self.seen_users.add(user)
			return True

		def blocked(self, user):
			"""return whether this user (the highlightee) has blocked the highlighter"""
			# we only have to check if the *user* is blocked here bc the database filters out blocked channels
			return self.db.blocked(user.id, self.author_id)

		@staticmethod
		def build_re(highlights):
			return (
				r'(?i)'  # case insensitive
				r'\b'  # word bound
				r'(?:{})'  # non capturing group, to make sure that the word bound occurs before/after all words
				r'\b'
			).format('|'.join(map(re.escape, highlights)))

		@staticmethod
		def remove_mentions(content):
			"""remove user @mentions from a message"""
			return re.sub(r'<@!?\d+>', '', content, re.ASCII)
			# don't remove role mentions because conceivably someone would want to be highlighted for a role they cannot join
			# though it would be easier on the user to replace role mentions with @{role.name},
			# @weeb should not highlight someone who has "weeb" set up as a mention

	@classmethod
	async def notify(cls, user, highlight, message):
		message = await cls.notification_message(user, highlight, message)
		with contextlib.suppress(discord.HTTPException):
			await user.send(**message)

	@staticmethod
	def time_difference_needed(time: datetime, max_delay: float):
		"""return the number of seconds needed to ensure that max_delay seconds have elapsed since time"""
		diff = max(0, (datetime.utcnow() - time).total_seconds())
		return max_delay - diff

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
			async for message in message.channel.history(around=message, limit=8, oldest_first=True)])

		return '\n\n'.join((formatted_messages, f'[Original message]({message.jump_url})'))

	@staticmethod
	def format_message(message, *, is_highlight: bool):
		date = message.created_at.strftime('[%I:%M:%S %p UTC]')
		date = f'**{date}**' if is_highlight else date
		formatted = f'{date} {message.author}: {message.content}'
		return formatted

	### Commands

	@guild_only_command(aliases=['show', 'ls'])
	async def list(self, context):
		"""Shows all your highlights words or phrases."""
		self.delete_later(context.message)

		highlights = await self.db.user_highlights(context.guild.id, context.author.id)
		if not highlights:
			await context.send('You do not have any highlight words or phrases set up.', delete_after=DELETE_AFTER)
			return

		embed = self.author_embed(context.author)
		embed.title = 'Triggers'
		embed.description = '\n'.join(highlights)
		embed.set_footer(text=f'{len(highlights)} triggers')

		await context.send(embed=embed, delete_after=DELETE_LONG_AFTER)

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
			await self.db.add(context.guild.id, context.author.id, highlight)
		except commands.UserInputError:
			await context.try_add_reaction(utils.SUCCESS_EMOJIS[False])
			raise
		else:
			await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command(usage='<word or phrase>', aliases=['delete', 'del', 'rm'])
	async def remove(self, context, *, highlight):
		"""Removes a previously registered highlight word or phrase.

		Highlight words and phrases are not case-sensitive,
		so coffee, Coffee, and COFFEE will all notify you.
		"""
		self.delete_later(context.message)
		await self.db.remove(context.guild.id, context.author.id, highlight)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@commands.command(aliases=['blocks'])
	async def blocked(self, context):
		"""Shows you the users or channels that you have globally blocked."""
		self.delete_later(context.message)

		entities = list(map(self.format_entity, await self.db.blocks(context.author.id)))

		embed = self.author_embed(context.author)
		embed.title = 'Blocked'
		embed.description='\n'.join(entities)
		embed.set_footer(text=f'{len(entities)} entities blocked')

		await context.send(embed=embed, delete_after=DELETE_LONG_AFTER)

	def format_entity(self, entity):
		channel = self.bot.get_channel(entity)
		if channel:
			if isinstance(channel, discord.CategoryChannel):
				return f'📂 {channel.name}'
			return f'🗨️  {channel.mention}'

		user = self.bot.get_user(entity)
		if user:
			return f'👤 {user.mention}'

		return f'❔ {entity}'

	@staticmethod
	def author_embed(author):
		return discord.Embed().set_author(
			name=str(author),
			icon_url=author.avatar_url_as(format='png', size=64))

	@guild_only_command()
	async def block(self, context, *, entity: Entity):
		"""Blocks a member, channel, or channel category from highlighting you.

		This is functionally equivalent to the Discord block feature,
		which blocks them globally. This is not a per-server block.
		"""
		self.delete_later(context.message)
		await self.db.block(context.author.id, entity.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command()
	async def unblock(self, context, *, entity: Entity):
		"""Unblocks a member or channel from mentioning you.

		This reverts a previous block action.
		"""
		self.delete_later(context.message)
		await self.db.unblock(context.author.id, entity.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@commands.command(name='blocked-by', aliases=['blocked-by?', 'blocked?'])
	async def blocked_by(self, context, *, user: User):
		"""Tells you if a given user has blocked you."""
		self.delete_later(context.message)
		clean = functools.partial(commands.clean_content().convert, context)
		if await self.db.blocked(user.id, context.author.id):
			await context.send(await clean(f'Yes, {user.mention} has blocked you.'), delete_after=DELETE_AFTER)
		else:
			await context.send(await clean(f'No, {user.mention} has not blocked you.'), delete_after=DELETE_AFTER)

	@guild_only_command()
	async def clear(self, context):
		"""Removes all your highlight words or phrases."""
		self.delete_later(context.message)
		await self.db.clear(context.guild.id, context.author.id)
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
			await self.db.import_(source_guild=server.id, target_guild=context.guild.id, user=context.author.id)
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

		await self.db.delete_account(context.author.id)
		await context.send(f"{context.author.mention} I've deleted your account successfully.")

	async def confirm(self, context, prompt, required_phrase, *, timeout=30):
		await context.send(prompt)

		def check(message): return (
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

	def delete_later(self, message, delay=DELETE_AFTER):
		async def delete_after():
			await asyncio.sleep(delay)
			with contextlib.suppress(discord.HTTPException):
				await message.delete()
		self.bot.loop.create_task(delete_after())

def setup(bot):
	bot.add_cog(Highlight(bot))
