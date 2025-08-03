import discord
from discord.ext import commands
from flask import jsonify
from datetime import datetime
import asyncio

class ServerStatsModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Server Stats"
        self.description = "View detailed server statistics and send stats to channels"
        self.html = self.get_html()
        
        # Add command to the bot
        @bot.command(name='stats', aliases=['serverstats', 'barkstats'])
        async def stats_command(ctx):
            """Display server statistics"""
            stats = self.get_server_stats(ctx.guild)
            embed = self.create_stats_embed(ctx.guild, stats)
            await ctx.send(embed=embed)
    
    def get_server_stats(self, guild):
        """Gather statistics for a guild"""
        if not guild:
            return None
            
        # Member stats
        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        bot_members = sum(1 for m in guild.members if m.bot)
        human_members = total_members - bot_members
        
        # Channel stats
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        categories = len(guild.categories)
        total_channels = text_channels + voice_channels
        
        # Role stats
        roles = len(guild.roles) - 1  # Exclude @everyone
        
        # Server info
        created_at = guild.created_at
        age_days = (datetime.utcnow().replace(tzinfo=None) - created_at.replace(tzinfo=None)).days
        
        # Boost info
        boost_level = guild.premium_tier
        boost_count = guild.premium_subscription_count
        
        return {
            "members": {
                "total": total_members,
                "humans": human_members,
                "bots": bot_members,
                "online": online_members
            },
            "channels": {
                "text": text_channels,
                "voice": voice_channels,
                "categories": categories,
                "total": total_channels
            },
            "server": {
                "name": guild.name,
                "id": str(guild.id),
                "owner": str(guild.owner),
                "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                "age_days": age_days,
                "icon_url": str(guild.icon.url) if guild.icon else None
            },
            "roles": roles,
            "boosts": {
                "level": boost_level,
                "count": boost_count
            },
            "features": guild.features
        }
    
    def create_stats_embed(self, guild, stats):
        """Create a Discord embed with server stats"""
        embed = discord.Embed(
            title=f"📊 {guild.name} Statistics",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        
        # Members field
        members = stats['members']
        embed.add_field(
            name="👥 Members",
            value=f"Total: **{members['total']}**\n"
                  f"Humans: **{members['humans']}**\n"
                  f"Bots: **{members['bots']}**\n"
                  f"Online: **{members['online']}**",
            inline=True
        )
        
        # Channels field
        channels = stats['channels']
        embed.add_field(
            name="💬 Channels",
            value=f"Text: **{channels['text']}**\n"
                  f"Voice: **{channels['voice']}**\n"
                  f"Categories: **{channels['categories']}**\n"
                  f"Total: **{channels['total']}**",
            inline=True
        )
        
        # Server Info field
        server = stats['server']
        embed.add_field(
            name="ℹ️ Server Info",
            value=f"Owner: **{server['owner']}**\n"
                  f"Created: **{server['age_days']}** days ago\n"
                  f"Roles: **{stats['roles']}**\n"
                  f"Boosts: **{stats['boosts']['count']}** (Level {stats['boosts']['level']})",
            inline=True
        )
        
        embed.set_footer(text=f"Server ID: {server['id']}")
        
        return embed
    
    def get_html(self):
        """Return the HTML for this module's interface"""
        return '''
        <h2>Server Statistics</h2>
        <p>View detailed statistics for your Discord servers.</p>
        
        <div>
            <label for="stats-server-select">Select Server:</label><br>
            <select id="stats-server-select" onchange="loadServerStats()">
                <option value="">Loading servers...</option>
            </select>
        </div>
        
        <div id="stats-container" style="margin-top: 20px; display: none;">
            <h3 id="server-name"></h3>
            
            <div id="stats-grid" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 20px;">
                <div>
                    <h4>Members</h4>
                    <div id="member-stats"></div>
                </div>
                
                <div>
                    <h4>Channels</h4>
                    <div id="channel-stats"></div>
                </div>
                
                <div>
                    <h4>Server Info</h4>
                    <div id="server-info"></div>
                </div>
            </div>
            
            <div style="margin-top: 30px;">
                <h4>Send Stats to Channel</h4>
                <select id="stats-channel-select">
                    <option value="">Select a channel</option>
                </select>
                <button onclick="sendStatsToChannel()">Send Stats</button>
                <div id="send-status"></div>
            </div>
        </div>
        
        <script>
            function loadStatsServers() {
                fetch('/api/server_stats/get_servers')
                    .then(response => response.json())
                    .then(data => {
                        const select = document.getElementById('stats-server-select');
                        select.innerHTML = '<option value="">Select a server</option>';
                        data.servers.forEach(server => {
                            const option = document.createElement('option');
                            option.value = server.id;
                            option.textContent = server.name;
                            select.appendChild(option);
                        });
                    });
            }
            
            function loadServerStats() {
                const serverId = document.getElementById('stats-server-select').value;
                if (!serverId) {
                    document.getElementById('stats-container').style.display = 'none';
                    return;
                }
                
                fetch(`/api/server_stats/get_stats?server_id=${serverId}`)
                    .then(response => response.json())
                    .then(data => {
                        if (data.error) {
                            alert(data.error);
                            return;
                        }
                        
                        displayStats(data.stats);
                        loadChannelsForStats(serverId);
                    });
            }
            
            function displayStats(stats) {
                document.getElementById('stats-container').style.display = 'block';
                document.getElementById('server-name').textContent = stats.server.name;
                
                // Member stats
                document.getElementById('member-stats').innerHTML = `
                    <p>Total Members: <strong>${stats.members.total}</strong></p>
                    <p>Humans: <strong>${stats.members.humans}</strong></p>
                    <p>Bots: <strong>${stats.members.bots}</strong></p>
                    <p>Online: <strong>${stats.members.online}</strong></p>
                `;
                
                // Channel stats
                document.getElementById('channel-stats').innerHTML = `
                    <p>Text Channels: <strong>${stats.channels.text}</strong></p>
                    <p>Voice Channels: <strong>${stats.channels.voice}</strong></p>
                    <p>Categories: <strong>${stats.channels.categories}</strong></p>
                    <p>Total: <strong>${stats.channels.total}</strong></p>
                `;
                
                // Server info
                document.getElementById('server-info').innerHTML = `
                    <p>Owner: <strong>${stats.server.owner}</strong></p>
                    <p>Created: <strong>${stats.server.age_days}</strong> days ago</p>
                    <p>Roles: <strong>${stats.roles}</strong></p>
                    <p>Boosts: <strong>${stats.boosts.count}</strong> (Level ${stats.boosts.level})</p>
                `;
            }
            
            function loadChannelsForStats(serverId) {
                fetch(`/api/server_stats/get_channels?server_id=${serverId}`)
                    .then(response => response.json())
                    .then(data => {
                        const select = document.getElementById('stats-channel-select');
                        select.innerHTML = '<option value="">Select a channel</option>';
                        data.channels.forEach(channel => {
                            const option = document.createElement('option');
                            option.value = channel.id;
                            option.textContent = '#' + channel.name;
                            select.appendChild(option);
                        });
                    });
            }
            
            function sendStatsToChannel() {
                const serverId = document.getElementById('stats-server-select').value;
                const channelId = document.getElementById('stats-channel-select').value;
                const statusDiv = document.getElementById('send-status');
                
                if (!channelId) {
                    statusDiv.textContent = 'Please select a channel';
                    return;
                }
                
                fetch('/api/server_stats/send_stats', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        server_id: serverId,
                        channel_id: channelId
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        statusDiv.textContent = 'Stats sent successfully!';
                    } else {
                        statusDiv.textContent = 'Error: ' + data.error;
                    }
                });
            }
            
            // Load servers when module becomes active
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.target.classList.contains('active')) {
                        loadStatsServers();
                    }
                });
            });
            
            observer.observe(document.getElementById('server_stats'), {
                attributes: true,
                attributeFilter: ['class']
            });
        </script>
        '''
    
    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "get_servers":
            servers = []
            for guild in self.bot.guilds:
                servers.append({
                    "id": str(guild.id),
                    "name": guild.name
                })
            return jsonify({"servers": servers})
        
        elif action == "get_stats":
            server_id = request.args.get('server_id')
            if not server_id:
                return jsonify({"error": "No server ID provided"}), 400
            
            guild = self.bot.get_guild(int(server_id))
            if not guild:
                return jsonify({"error": "Server not found"}), 404
            
            stats = self.get_server_stats(guild)
            return jsonify({"stats": stats})
        
        elif action == "get_channels":
            server_id = request.args.get('server_id')
            if not server_id:
                return jsonify({"error": "No server ID provided"}), 400
            
            guild = self.bot.get_guild(int(server_id))
            if not guild:
                return jsonify({"error": "Server not found"}), 404
            
            channels = []
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    channels.append({
                        "id": str(channel.id),
                        "name": channel.name
                    })
            return jsonify({"channels": channels})
        
        elif action == "send_stats":
            data = request.get_json()
            server_id = data.get('server_id')
            channel_id = data.get('channel_id')
            
            if not server_id or not channel_id:
                return jsonify({"error": "Missing server or channel ID"}), 400
            
            try:
                guild = self.bot.get_guild(int(server_id))
                channel = self.bot.get_channel(int(channel_id))
                
                if not guild or not channel:
                    return jsonify({"error": "Server or channel not found"}), 404
                
                stats = self.get_server_stats(guild)
                embed = self.create_stats_embed(guild, stats)
                
                # Send using the bot's event loop
                future = asyncio.run_coroutine_threadsafe(
                    channel.send(embed=embed),
                    self.bot.loop
                )
                future.result(timeout=10)
                
                return jsonify({"success": True})
                
            except Exception as e:
                print(f"Error sending stats: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        return jsonify({"error": "Unknown action"}), 404

def setup(bot, app):
    """Setup function called by the main bot"""
    return ServerStatsModule(bot, app)