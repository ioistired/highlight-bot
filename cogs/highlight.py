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
		highlight_users, regex = await self.db_cog.get_channel_highlights(message.channel)
		if not highlight_users:
			return

		print(highlight_users, bool(highlight_users))
		print(regex)

		seen_users = set()
		for match in re.finditer(regex, message.content):
			highlight = match[0]
			for user_id in highlight_users.getall(highlight):
				user = self.bot.get_user(user_id) or await self.bot.get_user_info(user_id)

				if user not in seen_users and user != message.author:
					yield user, highlight
					seen_users.add(user)

	async def notify(self, user, highlight, message):
		message = self.get_message(user, highlight, message)

		with contextlib.suppress(discord.HTTPException):
			await user.send(**message)

	def get_message(self, user, highlight, message):
		content = f'In {message.channel.mention} for server {message.guild.name}, you were mentioned with highlight word **{highlight}**'
		embed = discord.Embed(title=highlight, description=self.get_embed_description(message))
		return dict(content=content, embed=embed)

	def get_embed_description(self, message):
		date = message.created_at.strftime('[%I:%M:%S %p UTC]')
		return f'{date} {message.author}: {message.content}'

def setup(bot):
	bot.add_cog(Highlight(bot))
