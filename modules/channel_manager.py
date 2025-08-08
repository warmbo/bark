# modules/channel_manager.py
import discord
from discord.ext import commands
from flask import jsonify, request
import asyncio

class ChannelManagerModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Channel Manager"
        self.description = "Admins can change channel names/descriptions and create new channels."
        self.icon = "edit"
        self.version = "1.0.1"
        self.commands = []
        self.html = self.get_html()
        self._register_commands()

    def _register_commands(self):
        @self.bot.command(name='renamechannel')
        @commands.has_permissions(manage_channels=True)
        async def rename_channel(ctx, channel: discord.TextChannel, *, new_name: str):
            """Rename a channel (admin only)."""
            try:
                await channel.edit(name=new_name)
                await ctx.send(f"✅ Channel renamed to {new_name}")
            except Exception as e:
                await ctx.send(f"❌ Error: {e}")

        @self.bot.command(name='setchanneldesc')
        @commands.has_permissions(manage_channels=True)
        async def set_channel_desc(ctx, channel: discord.TextChannel, *, new_topic: str):
            """Set channel description/topic (admin only)."""
            try:
                await channel.edit(topic=new_topic)
                await ctx.send(f"✅ Channel topic updated!")
            except Exception as e:
                await ctx.send(f"❌ Error: {e}")

        @self.bot.command(name='createchannel')
        @commands.has_permissions(manage_channels=True)
        async def create_channel(ctx, name: str, *, topic: str = None):
            """Create a new text channel (admin only)."""
            try:
                channel = await ctx.guild.create_text_channel(name, topic=topic)
                await ctx.send(f"✅ Created channel <#{channel.id}>")
            except Exception as e:
                await ctx.send(f"❌ Error: {e}")

        self.commands = ['renamechannel', 'setchanneldesc', 'createchannel']

    def get_html(self):
        return '''
        <div class="module-header">
            <h2><i data-lucide="edit"></i> Channel Manager</h2>
            <p>Admins can change channel names/descriptions and create new channels.</p>
        </div>
        <div class="channel-manager-container">
            <!-- Content abbreviated for space -->
        </div>
        '''

    async def _edit_channel_async(self, channel_id, **kwargs):
        """Helper to safely edit channels from API"""
        for guild in self.bot.guilds:
            channel = guild.get_channel(int(channel_id))
            if channel:
                await channel.edit(**kwargs)
                return True
        return False

    async def _create_channel_async(self, guild_id, name, topic=None):
        """Helper to safely create channels from API"""
        guild = self.bot.get_guild(int(guild_id))
        if guild:
            channel = await guild.create_text_channel(name, topic=topic)
            return channel.id
        return None

    def handle_api(self, action, request):
        """Fixed API handler with proper async handling"""
        if not hasattr(self.bot, 'loop') or not self.bot.loop.is_running():
            return jsonify({"error": "Bot not ready"}), 503

        try:
            if action == "rename_channel":
                data = request.get_json()
                channel_id = data.get('channel_id')
                new_name = data.get('new_name')
                
                if not channel_id or not new_name:
                    return jsonify({"error": "Missing parameters"}), 400

                # FIXED: Proper async handling
                future = asyncio.run_coroutine_threadsafe(
                    self._edit_channel_async(channel_id, name=new_name),
                    self.bot.loop
                )
                success = future.result(timeout=10)
                
                if success:
                    return jsonify({"success": True})
                else:
                    return jsonify({"error": "Channel not found"}), 404

            elif action == "set_channel_desc":
                data = request.get_json()
                channel_id = data.get('channel_id')
                new_topic = data.get('new_topic')
                
                if not channel_id or new_topic is None:
                    return jsonify({"error": "Missing parameters"}), 400

                future = asyncio.run_coroutine_threadsafe(
                    self._edit_channel_async(channel_id, topic=new_topic),
                    self.bot.loop
                )
                success = future.result(timeout=10)
                
                return jsonify({"success": success})

            elif action == "create_channel":
                data = request.get_json()
                name = data.get('name')
                topic = data.get('topic')
                
                if not name:
                    return jsonify({"error": "Missing channel name"}), 400

                # Use first available guild for now - should be configurable
                guild_id = self.bot.guilds[0].id if self.bot.guilds else None
                if not guild_id:
                    return jsonify({"error": "No guilds available"}), 400

                future = asyncio.run_coroutine_threadsafe(
                    self._create_channel_async(guild_id, name, topic),
                    self.bot.loop
                )
                channel_id = future.result(timeout=10)
                
                if channel_id:
                    return jsonify({"success": True, "channel_id": channel_id})
                else:
                    return jsonify({"error": "Failed to create channel"}), 500

        except asyncio.TimeoutError:
            return jsonify({"error": "Operation timeout"}), 504
        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify({"error": "Unknown action"}), 404

    def cleanup(self):
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return ChannelManagerModule(bot, app)