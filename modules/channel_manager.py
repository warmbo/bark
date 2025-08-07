# modules/channel_manager.py
import discord
from discord.ext import commands
from flask import jsonify, request

class ChannelManagerModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Channel Manager"
        self.description = "Admins can change channel names/descriptions and create new channels."
        self.icon = "edit"
        self.version = "1.0.0"
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
            guild = ctx.guild
            try:
                channel = await guild.create_text_channel(name, topic=topic)
                await ctx.send(f"✅ Created channel <#{channel.id}>")
            except Exception as e:
                await ctx.send(f"❌ Error: {e}")

        self.commands = ['renamechannel', 'setchanneldesc', 'createchannel']

    def get_html(self):
        return '''
        <!-- Tabler Icons CDN -->
        <link rel="stylesheet" href="https://unpkg.com/@tabler/icons-webfont@latest/tabler-icons.min.css">
        <div class="module-header">
            <h2><i class="ti ti-edit"></i> Channel Manager</h2>
            <p>Admins can change channel names/descriptions and create new channels.</p>
        </div>
        <div class="channelmanager-container">
            <div class="info-section">
                <h3><i class="ti ti-list-details"></i> Commands</h3>
                <div class="command-list">
                    <div class="command-item">
                        <i class="ti ti-edit"></i> <code>bark-renamechannel #channel new-name</code>
                        <span>Rename a channel</span>
                    </div>
                    <div class="command-item">
                        <i class="ti ti-align-box-bottom-center"></i> <code>bark-setchanneldesc #channel new description</code>
                        <span>Set channel description/topic</span>
                    </div>
                    <div class="command-item">
                        <i class="ti ti-plus"></i> <code>bark-createchannel channel-name [topic]</code>
                        <span>Create a new text channel</span>
                    </div>
                </div>
            </div>
            <div class="test-section">
                <h3><i class="ti ti-settings"></i> Test API</h3>
                <input type="text" id="test-channel-id" placeholder="Channel ID">
                <input type="text" id="test-new-name" placeholder="New Name">
                <button class="btn btn-primary" onclick="testRenameChannelAPI()"><i class="ti ti-edit"></i> Rename Channel</button>
                <input type="text" id="test-new-topic" placeholder="New Topic">
                <button class="btn btn-primary" onclick="testSetChannelDescAPI()"><i class="ti ti-align-box-bottom-center"></i> Set Description</button>
                <input type="text" id="test-create-name" placeholder="New Channel Name">
                <input type="text" id="test-create-topic" placeholder="Topic (optional)">
                <button class="btn btn-primary" onclick="testCreateChannelAPI()"><i class="ti ti-plus"></i> Create Channel</button>
                <div id="channelmanager-result" class="api-result"></div>
            </div>
        </div>
        <script>
        async function testRenameChannelAPI() {
            const channelId = document.getElementById('test-channel-id').value;
            const newName = document.getElementById('test-new-name').value;
            const resultDiv = document.getElementById('channelmanager-result');
            resultDiv.textContent = 'Renaming channel...';
            resultDiv.className = 'api-result loading';
            try {
                const response = await fetch(`/api/channel_manager/rename_channel`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ channel_id: channelId, new_name: newName })
                });
                const data = await response.json();
                resultDiv.textContent = data.success ? 'Renamed!' : (data.error || 'Error');
                resultDiv.className = data.success ? 'api-result' : 'api-result error';
            } catch (error) {
                resultDiv.textContent = 'Error: ' + error.message;
                resultDiv.className = 'api-result error';
            }
        }
        async function testSetChannelDescAPI() {
            const channelId = document.getElementById('test-channel-id').value;
            const newTopic = document.getElementById('test-new-topic').value;
            const resultDiv = document.getElementById('channelmanager-result');
            resultDiv.textContent = 'Setting topic...';
            resultDiv.className = 'api-result loading';
            try {
                const response = await fetch(`/api/channel_manager/set_channel_desc`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ channel_id: channelId, new_topic: newTopic })
                });
                const data = await response.json();
                resultDiv.textContent = data.success ? 'Updated!' : (data.error || 'Error');
                resultDiv.className = data.success ? 'api-result' : 'api-result error';
            } catch (error) {
                resultDiv.textContent = 'Error: ' + error.message;
                resultDiv.className = 'api-result error';
            }
        }
        async function testCreateChannelAPI() {
            const name = document.getElementById('test-create-name').value;
            const topic = document.getElementById('test-create-topic').value;
            const resultDiv = document.getElementById('channelmanager-result');
            resultDiv.textContent = 'Creating channel...';
            resultDiv.className = 'api-result loading';
            try {
                const response = await fetch(`/api/channel_manager/create_channel`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, topic })
                });
                const data = await response.json();
                resultDiv.textContent = data.success ? `Created! ID: ${data.channel_id}` : (data.error || 'Error');
                resultDiv.className = data.success ? 'api-result' : 'api-result error';
            } catch (error) {
                resultDiv.textContent = 'Error: ' + error.message;
                resultDiv.className = 'api-result error';
            }
        }
        </script>
        <style>
        .channelmanager-container { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
        .info-section, .test-section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
        .command-list { display: flex; flex-direction: column; gap: 1rem; }
        .command-item { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
        .api-result { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-top: 1rem; min-height: 60px; text-align: left; color: var(--text); font-style: italic; white-space: pre-wrap; }
        .api-result.loading { color: var(--text-muted); }
        .api-result.error { color: #ef4444; }
        </style>
        '''

    def handle_api(self, action, request):
        # All API actions require admin permissions, so these should be protected in production
        if action == "rename_channel":
            data = request.get_json()
            channel_id = data.get('channel_id')
            new_name = data.get('new_name')
            for guild in self.bot.guilds:
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if channel:
                    future = self.bot.loop.create_task(channel.edit(name=new_name))
                    try:
                        self.bot.loop.run_until_complete(future)
                        return jsonify({"success": True})
                    except Exception as e:
                        return jsonify({"error": str(e)}), 400
            return jsonify({"error": "Channel not found"}), 404
        if action == "set_channel_desc":
            data = request.get_json()
            channel_id = data.get('channel_id')
            new_topic = data.get('new_topic')
            for guild in self.bot.guilds:
                channel = guild.get_channel(int(channel_id)) if channel_id else None
                if channel:
                    future = self.bot.loop.create_task(channel.edit(topic=new_topic))
                    try:
                        self.bot.loop.run_until_complete(future)
                        return jsonify({"success": True})
                    except Exception as e:
                        return jsonify({"error": str(e)}), 400
            return jsonify({"error": "Channel not found"}), 404
        if action == "create_channel":
            data = request.get_json()
            name = data.get('name')
            topic = data.get('topic')
            for guild in self.bot.guilds:
                future = self.bot.loop.create_task(guild.create_text_channel(name, topic=topic))
                try:
                    channel = self.bot.loop.run_until_complete(future)
                    return jsonify({"success": True, "channel_id": channel.id})
                except Exception as e:
                    return jsonify({"error": str(e)}), 400
            return jsonify({"error": "Guild not found"}), 404
        return jsonify({"error": "Unknown action"}), 404

    def cleanup(self):
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return ChannelManagerModule(bot, app)
