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

import contextlib
import re

import discord
from discord.ext import commands

class Highlight:
	def __init__(self, bot):
		self.bot = bot
		self.db_cog = self.bot.get_cog('Database')

	async def on_message(self, message):
		if not message.guild:
			return

		async for user, highlight in self.highlights(message):
			await self.notify(user, highlight, message)

	async def highlights(self, message):
		highlight_users, regex = await self.db_cog.channel_highlights(message.channel)
		if not highlight_users:
			return

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

	async def notification_message(self, user, highlight, message):
		content = (
			f'In {message.channel.mention} for server {message.guild.name}, '
			f'you were mentioned with highlight word **{highlight}**')

		embed = discord.Embed()
		embed.title = highlight
		embed.description = await self.embed_description(message)
		embed.set_author(name=message.author.name, icon_url=message.author.avatar_url_as(format='png', size=64))
		embed.set_footer(text='Triggered')  # "Triggered today at 21:21"
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
