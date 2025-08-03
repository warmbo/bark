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
        self.icon = "bar-chart-3"
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
        <div class="module-header">
            <h2><i data-lucide="bar-chart-3"></i> Server Statistics</h2>
            <p>View detailed statistics for your Discord servers.</p>
        </div>
        
        <div class="form-container">
            <div class="form-group">
                <label for="stats-server-select">Select Server</label>
                <select id="stats-server-select" onchange="loadServerStats()">
                    <option value="">Loading servers...</option>
                </select>
            </div>
        </div>
        
        <div id="stats-container" style="display: none;">
            <div class="stats-display">
                <h3 id="server-name" class="server-title"></h3>
                
                <div class="stats-grid">
                    <div class="stat-section">
                        <div class="stat-header">
                            <i data-lucide="users"></i>
                            <h4>Members</h4>
                        </div>
                        <div id="member-stats" class="stat-content"></div>
                    </div>
                    
                    <div class="stat-section">
                        <div class="stat-header">
                            <i data-lucide="hash"></i>
                            <h4>Channels</h4>
                        </div>
                        <div id="channel-stats" class="stat-content"></div>
                    </div>
                    
                    <div class="stat-section">
                        <div class="stat-header">
                            <i data-lucide="info"></i>
                            <h4>Server Info</h4>
                        </div>
                        <div id="server-info" class="stat-content"></div>
                    </div>
                </div>
            </div>
            
            <div class="send-stats-section">
                <h4><i data-lucide="send"></i> Send Stats to Channel</h4>
                <div class="form-row">
                    <select id="stats-channel-select" class="flex-1">
                        <option value="">Select a channel</option>
                    </select>
                    <button class="btn btn-primary" onclick="sendStatsToChannel()">
                        <i data-lucide="send"></i>
                        Send Stats
                    </button>
                </div>
            </div>
        </div>
        
        <style>
            .module-header {
                margin-bottom: 2rem;
            }
            
            .module-header h2 {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 0.5rem;
                color: var(--text);
            }
            
            .form-container {
                background: var(--glass-bg);
                backdrop-filter: var(--blur);
                border: 1px solid var(--glass-border);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 2rem;
            }
            
            .stats-display {
                background: var(--glass-bg);
                backdrop-filter: var(--blur);
                border: 1px solid var(--glass-border);
                border-radius: 12px;
                padding: 1.5rem;
                margin-bottom: 2rem;
            }
            
            .server-title {
                color: var(--text);
                margin-bottom: 1.5rem;
                font-size: 1.5rem;
            }
            
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 1.5rem;
            }
            
            .stat-section {
                background: var(--surface);
                border: 1px solid var(--border);
                border-radius: 8px;
                padding: 1rem;
            }
            
            .stat-header {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 1rem;
                color: var(--primary);
            }
            
            .stat-header h4 {
                margin: 0;
                font-size: 1.1rem;
            }
            
            .stat-content p {
                margin: 0.5rem 0;
                color: var(--text-muted);
            }
            
            .stat-content strong {
                color: var(--text);
                font-weight: 600;
            }
            
            .send-stats-section {
                background: var(--glass-bg);
                backdrop-filter: var(--blur);
                border: 1px solid var(--glass-border);
                border-radius: 12px;
                padding: 1.5rem;
            }
            
            .send-stats-section h4 {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                margin-bottom: 1rem;
                color: var(--text);
            }
            
            .form-row {
                display: flex;
                gap: 1rem;
                align-items: center;
            }
            
            .flex-1 {
                flex: 1;
            }
        </style>
        
        <script>
            // Auto-load servers when module becomes active
            const observer2 = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.target.id === 'server_stats' && 
                        mutation.target.classList.contains('active')) {
                        loadStatsServers();
                        lucide.createIcons();
                    }
                });
            });
            
            const serverStatsModule = document.getElementById('server_stats');
            if (serverStatsModule) {
                observer2.observe(serverStatsModule, {
                    attributes: true,
                    attributeFilter: ['class']
                });
            }
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