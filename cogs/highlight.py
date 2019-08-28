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
import copy
import contextlib
import functools
import operator
import re
import time
import typing

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

MENTION_RE = re.compile(r'<@!?(\d+)>', re.ASCII)
NICKNAME_MENTION_RE = re.compile(MENTION_RE.pattern.replace('!?', '!'), MENTION_RE.flags)

def normalize_mentions(s):
	return NICKNAME_MENTION_RE.sub(r'<@\1>', s)

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

		self.bot.dispatch('user_activity', message.channel.id, message.author.id)

		# prevent message edits from updating this message obj
		message = copy.copy(message)
		coros = []
		async for highlighted_user, highlight in self.HighlightFinder(bot=self.bot, message=message, db=self.db):
			info = message.channel.id, highlighted_user.id
			if not self.was_recently_active(info):
				# add to the dict first to prevent other message events from notifying as well
				# this is to prevent two messages sent in immediate succession
				# from notifying the user twice
				self.recently_active[info] = time.monotonic()

				coros.append(self.notify_if_user_is_inactive(highlighted_user, highlight, message))

		# notify everyone asynchronously
		await asyncio.gather(*coros)

	@commands.Cog.listener()
	async def on_user_activity(self, channel_id, user_id):
		"""dispatched whenever a user does something that would cause them to see recent messages in channel_id"""
		self.recently_active[channel_id, user_id] = time.monotonic()

	async def notify_if_user_is_inactive(self, highlighted_user, highlight, message):
		try:
			await self.bot.wait_for('user_activity',
				check=lambda channel_id, user_id:
					channel_id == message.channel.id
					and user_id == highlighted_user.id,
				timeout=NEW_MESSAGES_DELAY)
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
			return time.monotonic() - self.recently_active[info] < delay
		except KeyError:
			# if they haven't spoken at all, then they also haven't spoken recently
			return False

	@commands.Cog.listener()
	async def on_typing(self, channel, user, when):
		self.bot.dispatch('user_activity', channel.id, user.id)

	# we use a class to have shared state which is isolated from the cog
	# we use a nested class so as to have HighlightFinder defined close to where it's used
	class HighlightFinder:
		__slots__ = {
			'bot': '',
			'db': 'type: DatabaseInterface',
			'message': 'the message to process highlights for',
			'author_id': 'ID of the user who sent the message',
			'seen_users':
				'users who have already been highlighted and should not be highlighted again for this message'}

		def __init__(self, *, bot, message, db):
			self.bot = bot
			self.db = db
			self.message = message
			self.author_id = self.message.author.id
			self.seen_users = set()

		async def __aiter__(self):
			searcher = await self.db.channel_highlights(self.message.channel)
			if not searcher:
				return

			content = normalize_mentions(self.message.content)
			for highlight_users, start, end in searcher.search_extended(content):
				highlight = content[max(0, start - len('<@!')):end + len('>') + 1]
				for highlight_user in highlight_users:
					preferred_caps = highlight_user.preferred_caps
					user = self.bot.get_user(highlight_user.id) or await self.bot.fetch_user(highlight_user.id)

					if await self.should_notify(user, highlight, preferred_caps):
						yield user, preferred_caps

		async def should_notify(self, user, highlight, preferred_caps):
			"""assuming that a highlight was found in the message, return whether to notify the user"""
			if (await self.bot.get_context(self.message)).valid:
				# don't trigger on command invokes
				# this prevents a sneaky user from adding "add" as a highlight and getting notified when someone
				# adds a new highlight
				return False
			if self.message.author == self.bot.user:
				# prevent someone adding "Your highlight words have been updated" as a highlight too
				return False
			if not self.message.guild.get_member(user.id):
				# the user appears to have left the guild
				return False
			if user == self.message.author:
				# users may not highlight themselves
				return False
			if bool(MENTION_RE.match(preferred_caps)) != bool(MENTION_RE.match(highlight)):
				# only highlight @mentions if the user requested that
				return False
			if await self.blocked(user):
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

	@classmethod
	async def notify(cls, user, highlight, message):
		message = await cls.notification_message(user, highlight, message)
		with contextlib.suppress(discord.HTTPException):
			await user.send(**message)

	@classmethod
	async def notification_message(cls, user, highlight, message):
		"""Create an embed message to send to the user for being highlighted."""
		content = (
			f'In {message.channel.mention} for server {message.guild.name}, '
			f'you were mentioned with highlight word **{highlight}**')

		embed = discord.Embed()
		embed.color = discord.Color.blurple()
		embed.title = highlight
		embed.description = await cls.embed_description(message)
		embed.set_author(name=message.author.name, icon_url=message.author.avatar_url_as(format='png', size=64))

		# "Triggered today at 21:21"
		embed.set_footer(text='Triggered')
		embed.timestamp = message.created_at

		return dict(content=content, embed=embed)

	@classmethod
	async def embed_description(cls, message):
		orig_message = message
		formatted_messages = '\n'.join([
			cls.format_message(orig_message, message)
			async for message in message.channel.history(around=orig_message, limit=8, oldest_first=True)])

		return '\n\n'.join((formatted_messages, f'[Original message]({orig_message.jump_url})'))

	@staticmethod
	def format_message(orig_message, message):
		is_highlight = message.id == orig_message.id  # Message.__eq__ when
		date = message.created_at.strftime('[%I:%M:%S %p UTC]')
		date = f'**{date}**' if is_highlight else date
		# display the original message content in case someone edits a message after highlighting
		formatted = f'{date} {message.author}: {(orig_message if is_highlight else message).content}'
		return formatted

	### Commands

	@guild_only_command(aliases=['show', 'ls'])
	async def list(self, context):
		"""Shows all your highlights words or phrases."""
		await context.message.delete(delay=DELETE_AFTER)

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
		await context.message.delete(delay=DELETE_AFTER)
		try:
			await self.db.add(context.guild.id, context.author.id, normalize_mentions(highlight))
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
		await context.message.delete(delay=DELETE_AFTER)
		await self.db.remove(context.guild.id, context.author.id, highlight)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@commands.command(aliases=['blocks'])
	async def blocked(self, context):
		"""Shows you the users or channels that you have globally blocked."""
		await context.message.delete(delay=DELETE_AFTER)

		embed = self.author_embed(context.author)
		embed.title = 'Blocked'
		entities = list(map(self.format_entity, await self.db.blocks(context.author.id)))
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
		return discord.Embed().set_author(name=str(author), icon_url=author.avatar_url_as(format='png', size=64))

	@guild_only_command()
	async def block(self, context, *, entity: Entity):
		"""Blocks a member, channel, or channel category from highlighting you.

		This is functionally equivalent to the Discord block feature,
		which blocks them globally. This is not a per-server block.
		"""
		await context.message.delete(delay=DELETE_AFTER)
		await self.db.block(context.guild.id, context.author.id, entity.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@guild_only_command()
	async def unblock(self, context, *, entity: Entity):
		"""Unblocks a member or channel from mentioning you.

		This reverts a previous block action.
		"""
		await context.message.delete(delay=DELETE_AFTER)
		await self.db.unblock(context.guild.id, context.author.id, entity.id)
		await context.try_add_reaction(utils.SUCCESS_EMOJIS[True])

	@commands.command(name='blocked-by', aliases=['blocked-by?', 'blocked?'])
	async def blocked_by(self, context, *, user: User):
		"""Tells you if a given user has blocked you."""
		await context.message.delete(delay=DELETE_AFTER)
		clean = functools.partial(commands.clean_content().convert, context)
		if await self.db.blocked(user.id, context.author.id):
			await context.send(await clean(f'Yes, {user.mention} has blocked you.'), delete_after=DELETE_AFTER)
		else:
			await context.send(await clean(f'No, {user.mention} has not blocked you.'), delete_after=DELETE_AFTER)

	@guild_only_command()
	async def clear(self, context):
		"""Removes all your highlight words or phrases."""
		await context.message.delete(delay=DELETE_AFTER)
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
		await context.message.delete(delay=DELETE_AFTER)
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

def setup(bot):
	bot.add_cog(Highlight(bot))
