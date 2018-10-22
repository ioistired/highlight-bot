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
import re
import typing

import discord
from discord.ext import commands

import utils

Entity = typing.Union[discord.Member, discord.TextChannel, discord.CategoryChannel]

def guild_only_command(*args, **kwargs):
	def wrapper(func):
		# wooo, currying
		return commands.guild_only()(commands.command(*args, **kwargs))(func)
	return wrapper

class Highlight:
	def __init__(self, bot):
		self.bot = bot
		self.db_cog = self.bot.get_cog('Database')

	### Commands

	@guild_only_command(aliases=['list'])
	async def show(self, context):
		"""Shows all your highlights words or phrases."""
		self.delete_later(context.message)

		highlights = await self.db_cog.user_highlights(context.guild.id, context.author.id)
		if not highlights:
			return await context.send('You do not have any highlight words or phrases set up.')

		embed = discord.Embed()
		embed.set_author(name=context.author.name, icon_url=context.author.avatar_url_as(format='png', size=64))
		embed.add_field(name='Triggers', value='\n'.join(highlights), inline=False)
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
	async def import_(self, context, server: int):
		"""Imports your highlight words from another server.

		This is a copy operation, so if you remove a highlight word
		from the other server later, it is not reflected in the new
		server.
		"""
		self.delete_later(context.message)
		try:
			await self.db_cog.import_(source_guild=server, target_guild=context.guild.id, user=context.author.id)
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

	### Events

	async def on_message(self, message):
		if not message.guild or not self.bot.should_reply(message):
			return

		async for user, highlight in self.highlights(message):
			await self.notify(user, highlight, message)

	async def highlights(self, message):
		highlight_users = await self.db_cog.channel_highlights(message.channel)
		if not highlight_users:
			return

		regex = self.build_re(set(highlight_users.keys()))

		seen_users = set()
		for match in re.finditer(regex, message.content):
			highlight = match[0]
			for user in highlight_users.getall(highlight):
				if await self.blocked(user, message):
					continue

				user = self.bot.get_user(user) or await self.bot.get_user_info(user)

				if user not in seen_users and user != message.author:
					yield user, highlight
					seen_users.add(user)

	@staticmethod
	def build_re(highlights):
		s = r'(?i)\b'  # case insensitive
		s += '|'.join(map(re.escape, highlights))
		s += r'\b'
		return s

	async def blocked(self, user: int, message):
		blocks = await self.db_cog.blocks(user)
		return any(
			entity in blocks
			for entity in (
				message.channel.id,
				message.author.id,
				getattr(message.channel.category, 'id', None)))

	@classmethod
	async def notify(cls, user, highlight, message):
		message = await cls.notification_message(user, highlight, message)

		with contextlib.suppress(discord.HTTPException):
			await user.send(**message)

	@classmethod
	async def notification_message(cls, user, highlight, message):
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

def setup(bot):
	bot.add_cog(Highlight(bot))
