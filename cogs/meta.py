# Copyright © @lambda.dance
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

import inspect
import os.path
import pkg_resources

import discord
from discord.ext import commands
import pygit2

from bot import BASE_DIR
import utils

class Meta(commands.Cog):
	@commands.hybrid_command(aliases=['inv'])
	async def invite(self, context):
		"""Gives you a link to add me to your server."""
		# these are the same as the attributes of discord.Permissions
		permission_names = (
			'read_messages',
			'send_messages',
			'read_message_history',
			'external_emojis',
			'add_reactions',
			'manage_messages',
			'embed_links')
		permissions = discord.Permissions()
		permissions.update(**dict.fromkeys(permission_names, True))
		await context.send('<%s>' % discord.utils.oauth_url(context.bot.user.id, permissions=permissions))

	@commands.hybrid_command()
	async def support(self, context):
		"""Directs you to the support server."""
		try:
			await context.author.send('https://discord.gg/' + context.bot.config['support_server_invite_code'])
		except discord.HTTPException:
			await context.send(f'{utils.SUCCESS_EMOJIS[False]} Unable to send invite in DMs. Please allow DMs from server members.', ephemeral=True)
		else:
			await context.send('📬', ephemeral=True)

	# heavily based on code provided by Rapptz, © 2015 Rapptz
	# https://github.com/Rapptz/RoboDanny/blob/8919ec0a455f957848ef77b479fe3494e76f0aa7/cogs/meta.py#L162-L190
	@commands.hybrid_command()
	async def source(self, context, *, command: str = None):
		"""Displays my full source code or for a specific command."""
		source_url = context.bot.config['repo']
		if command is None:
			return await context.send(source_url)

		obj = context.bot.get_command(command.replace('.', ' '))
		if obj is None:
			return await context.send('Could not find command.')

		# since we found the command we're looking for, presumably anyway, let's
		# try to access the code itself
		src = obj.callback
		lines, firstlineno = inspect.getsourcelines(src)
		module = inspect.getmodule(src).__name__
		if module.startswith(self.__module__.split('.')[0]):
			# not a built-in command
			location = os.path.relpath(inspect.getfile(src)).replace('\\', '/')
			at = self._current_revision()
		else:
			if module.startswith('discord'):
				source_url = 'https://github.com/Rapptz/discord.py'
				at = self._discord_revision()
			if module.startswith('jishaku'):
				source_url = 'https://github.com/Gorialis/jishaku'
				at = self._pkg_version('jishaku')
			elif module.startswith('bot_bin'):
				source_url = 'https://github.com/ioistired/bot-bin'
				at = self._bot_bin_revision()

			location = module.replace('.', '/') + '.py'

		final_url = f'<{source_url}/blob/{at}/{location}#L{firstlineno}-L{firstlineno + len(lines) - 1}>'
		await context.send(final_url)

	@staticmethod
	def _current_revision():
		repo = pygit2.Repository(str(BASE_DIR / '.git'))
		c = next(repo.walk(repo.head.target, pygit2.GIT_SORT_TOPOLOGICAL))
		return c.short_id

	@classmethod
	def _discord_revision(cls):
		version = cls._pkg_version('discord.py')
		version, sep, commit = version.partition('+g')
		return commit or version

	@classmethod
	def _bot_bin_revision(cls, *, default='master'):
		ver = cls._pkg_version('bot_bin', default=default)
		if ver == default:
			return default

		return 'v' + ver

	@staticmethod
	def _pkg_version(pkg, *, default='master'):
		try:
			return pkg_resources.get_distribution(pkg).version
		except pkg_resources.DistributionNotFound:
			return default

async def setup(bot):
	await bot.add_cog(Meta())
	if not bot.config.get('support_server_invite_code'):
		bot.remove_command('support')
