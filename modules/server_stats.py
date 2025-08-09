# modules/server_stats.py
import discord
from utils import BaseModule, APIHelpers, DiscordHelpers, format_module_html

class ServerStatsModule(BaseModule):
    def __init__(self, bot, app):
        self.name = "Server Stats"
        self.description = "View detailed server statistics and send stats to channels"
        self.icon = "bar-chart-3"
        self.version = "1.0.0"
        
        super().__init__(bot, app)

    def _register_commands(self):
        @self.command(name="serverstats", help="Display detailed server statistics")
        async def serverstats_cmd(ctx):
            """Display comprehensive server statistics"""
            stats = await DiscordHelpers.get_server_stats(self.bot, str(ctx.guild.id))
            
            if not stats:
                embed = self.create_embed(
                    "❌ Error",
                    "Unable to fetch server statistics.",
                    discord.Color.red()
                )
                await ctx.send(embed=embed)
                return
            
            embed = self.create_embed(
                f"📊 {stats['server']['name']} Statistics",
                f"Comprehensive server overview",
                discord.Color.blue()
            )
            
            # Member statistics
            embed.add_field(
                name="👥 Members",
                value=f"**Total:** {stats['members']['total']}\n"
                      f"**Humans:** {stats['members']['humans']}\n"
                      f"**Bots:** {stats['members']['bots']}\n"
                      f"**Online:** {stats['members']['online']}",
                inline=True
            )
            
            # Channel statistics
            embed.add_field(
                name="📝 Channels",
                value=f"**Text:** {stats['channels']['text']}\n"
                      f"**Voice:** {stats['channels']['voice']}\n"
                      f"**Categories:** {stats['channels']['categories']}\n"
                      f"**Total:** {stats['channels']['total']}",
                inline=True
            )
            
            # Server info
            embed.add_field(
                name="🛡️ Server Info",
                value=f"**Owner:** {stats['server']['owner']}\n"
                      f"**Boost Level:** {stats['boosts']['level']}\n"
                      f"**Boosts:** {stats['boosts']['count']}\n"
                      f"**Roles:** {stats['roles']}",
                inline=True
            )
            
            embed.set_thumbnail(url=stats['server']['icon_url'] if stats['server']['icon_url'] else None)
            embed.set_footer(text=f"Server ID: {stats['server']['id']}")
            
            await ctx.send(embed=embed)

    def get_html(self):
        content = '''
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="terminal"></i>
                Commands
            </h3>
            <div class="command-list">
                <div class="command-item">
                    <code>bark-serverstats</code>
                    <span>Display comprehensive server statistics in Discord</span>
                </div>
            </div>
        </div>
        
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="server"></i>
                View Server Statistics
            </h3>
            <div class="form-group">
                <label for="stats-server-select">Select Server</label>
                <select id="stats-server-select" onchange="loadServerStats()">
                    <option value="">Loading servers...</option>
                </select>
            </div>
            
            <div id="stats-container" style="display: none;">
                <div class="stats-display">
                    <h4 id="server-name" class="server-title"></h4>
                    
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
                    <h4>
                        <i data-lucide="send"></i>
                        Send Stats to Channel
                    </h4>
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
        </div>
        
        <script>
        // Initialize when module becomes active
        function initializeServerStats() {
            console.log('Initializing Server Stats module');
            loadStatsServers();
            
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
        
        async function loadStatsServers() {
            try {
                const response = await fetch('/api/server_stats/get_servers');
                if (response.ok) {
                    const data = await response.json();
                    const select = document.getElementById('stats-server-select');
                    if (select) {
                        select.innerHTML = '<option value="">Select server</option>';
                        data.servers.forEach(server => {
                            const option = document.createElement('option');
                            option.value = server.id;
                            option.textContent = server.name;
                            select.appendChild(option);
                        });
                    }
                } else {
                    console.error('Failed to load servers');
                }
            } catch (error) {
                console.error('Failed to load servers:', error);
                const select = document.getElementById('stats-server-select');
                if (select) {
                    select.innerHTML = '<option value="">Error loading servers</option>';
                }
            }
        }
        
        async function loadServerStats() {
            const serverId = document.getElementById('stats-server-select')?.value;
            if (!serverId) {
                document.getElementById('stats-container').style.display = 'none';
                return;
            }
            
            try {
                const response = await fetch(`/api/server_stats/get_stats?server_id=${serverId}`);
                const data = await response.json();
                
                if (data.success && data.stats) {
                    const stats = data.stats;
                    const container = document.getElementById('stats-container');
                    if (container) {
                        container.style.display = 'block';
                        
                        // Update server name
                        const nameEl = document.getElementById('server-name');
                        if (nameEl) {
                            nameEl.textContent = stats.server.name;
                        }
                        
                        // Update member stats
                        const memberStatsEl = document.getElementById('member-stats');
                        if (memberStatsEl) {
                            memberStatsEl.innerHTML = `
                                <p>Total: <strong>${stats.members.total}</strong></p>
                                <p>Humans: <strong>${stats.members.humans}</strong></p>
                                <p>Bots: <strong>${stats.members.bots}</strong></p>
                                <p>Online: <strong>${stats.members.online}</strong></p>
                            `;
                        }
                        
                        // Update channel stats
                        const channelStatsEl = document.getElementById('channel-stats');
                        if (channelStatsEl) {
                            channelStatsEl.innerHTML = `
                                <p>Text: <strong>${stats.channels.text}</strong></p>
                                <p>Voice: <strong>${stats.channels.voice}</strong></p>
                                <p>Categories: <strong>${stats.channels.categories}</strong></p>
                                <p>Total: <strong>${stats.channels.total}</strong></p>
                            `;
                        }
                        
                        // Update server info
                        const serverInfoEl = document.getElementById('server-info');
                        if (serverInfoEl) {
                            const createdDate = new Date(stats.server.created_at);
                            const daysSinceCreated = Math.floor((Date.now() - createdDate.getTime()) / (1000 * 60 * 60 * 24));
                            
                            serverInfoEl.innerHTML = `
                                <p>Owner: <strong>${stats.server.owner}</strong></p>
                                <p>Created: <strong>${daysSinceCreated} days ago</strong></p>
                                <p>Roles: <strong>${stats.roles}</strong></p>
                                <p>Boosts: <strong>${stats.boosts.count} (Level ${stats.boosts.level})</strong></p>
                            `;
                        }
                        
                        // Load channels for stats sending
                        loadStatsChannels(serverId);
                    }
                } else {
                    console.error('Failed to load server stats:', data.error);
                }
            } catch (error) {
                console.error('Failed to load server stats:', error);
            }
        }
        
        async function loadStatsChannels(serverId) {
            try {
                const response = await fetch(`/api/server_stats/get_channels?server_id=${serverId}`);
                if (response.ok) {
                    const data = await response.json();
                    const select = document.getElementById('stats-channel-select');
                    if (select) {
                        select.innerHTML = '<option value="">Select a channel</option>';
                        data.channels.forEach(channel => {
                            const option = document.createElement('option');
                            option.value = channel.id;
                            option.textContent = '#' + channel.name;
                            select.appendChild(option);
                        });
                    }
                }
            } catch (error) {
                console.error('Failed to load channels for stats:', error);
            }
        }
        
        async function sendStatsToChannel() {
            const serverId = document.getElementById('stats-server-select')?.value;
            const channelId = document.getElementById('stats-channel-select')?.value;
            
            if (!serverId || !channelId) {
                alert('Please select a server and channel');
                return;
            }
            
            try {
                const response = await fetch('/api/server_stats/send_stats', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ server_id: serverId, channel_id: channelId })
                });
                
                const data = await response.json();
                if (data.success) {
                    alert('Stats sent to channel!');
                } else {
                    alert('Error: ' + (data.error || 'Failed to send stats'));
                }
            } catch (error) {
                alert('Failed to send stats to channel');
                console.error('Error:', error);
            }
        }
        
        // Auto-initialize when document loads and module is active
        document.addEventListener('DOMContentLoaded', function() {
            if (document.getElementById('server_stats') && 
                document.getElementById('server_stats').classList.contains('active')) {
                initializeServerStats();
            }
        });
        
        // Export function for external initialization
        window.initializeServerStats = initializeServerStats;
        </script>
        '''
        
        return format_module_html('server_stats', self.name, self.description, self.icon, content)

    def handle_api(self, action, request):
        """Handle API requests for this module"""
        try:
            if action == "get_servers":
                servers = self.run_async_in_bot_loop(
                    DiscordHelpers.get_server_list(self.bot, include_stats=False)
                )
                return APIHelpers.standard_success_response({"servers": servers})
            
            elif action == "get_stats":
                server_id = request.args.get('server_id')
                if not server_id:
                    return APIHelpers.standard_error_response("Missing server_id parameter")
                
                stats = self.run_async_in_bot_loop(
                    DiscordHelpers.get_server_stats(self.bot, server_id)
                )
                
                if stats:
                    return APIHelpers.standard_success_response({"stats": stats})
                else:
                    return APIHelpers.standard_error_response("Server not found or no permission")
            
            elif action == "get_channels":
                server_id = request.args.get('server_id')
                if not server_id:
                    return APIHelpers.standard_error_response("Missing server_id parameter")
                
                channels = self.run_async_in_bot_loop(
                    DiscordHelpers.get_server_channels(self.bot, server_id, text_only=True)
                )
                
                if channels is not None:
                    return APIHelpers.standard_success_response({"channels": channels})
                else:
                    return APIHelpers.standard_error_response("Server not found or no permission")
            
            elif action == "send_stats":
                data = request.get_json()
                if not data:
                    return APIHelpers.standard_error_response("No JSON data provided")
                
                server_id = data.get('server_id')
                channel_id = data.get('channel_id')
                
                if not server_id or not channel_id:
                    return APIHelpers.standard_error_response("Missing server_id or channel_id")
                
                # Get stats and send to channel
                try:
                    async def send_stats_to_channel():
                        stats = await DiscordHelpers.get_server_stats(self.bot, server_id)
                        if not stats:
                            return False
                        
                        channel = self.bot.get_channel(int(channel_id))
                        if not channel:
                            return False
                        
                        embed = discord.Embed(
                            title=f"📊 {stats['server']['name']} Statistics",
                            color=discord.Color.blue()
                        )
                        
                        # Member statistics
                        embed.add_field(
                            name="👥 Members",
                            value=f"**Total:** {stats['members']['total']}\n"
                                  f"**Humans:** {stats['members']['humans']}\n"
                                  f"**Bots:** {stats['members']['bots']}\n"
                                  f"**Online:** {stats['members']['online']}",
                            inline=True
                        )
                        
                        # Channel statistics
                        embed.add_field(
                            name="📝 Channels",
                            value=f"**Text:** {stats['channels']['text']}\n"
                                  f"**Voice:** {stats['channels']['voice']}\n"
                                  f"**Categories:** {stats['channels']['categories']}\n"
                                  f"**Total:** {stats['channels']['total']}",
                            inline=True
                        )
                        
                        # Server info
                        embed.add_field(
                            name="🛡️ Server Info",
                            value=f"**Owner:** {stats['server']['owner']}\n"
                                  f"**Boost Level:** {stats['boosts']['level']}\n"
                                  f"**Boosts:** {stats['boosts']['count']}\n"
                                  f"**Roles:** {stats['roles']}",
                            inline=True
                        )
                        
                        embed.set_thumbnail(url=stats['server']['icon_url'] if stats['server']['icon_url'] else None)
                        embed.set_footer(text=f"Generated via Bark Dashboard • Server ID: {stats['server']['id']}")
                        
                        await channel.send(embed=embed)
                        return True
                    
                    success = self.run_async_in_bot_loop(send_stats_to_channel())
                    
                    if success:
                        return APIHelpers.standard_success_response({"message": "Stats sent successfully"})
                    else:
                        return APIHelpers.standard_error_response("Failed to send stats")
                        
                except Exception as e:
                    return APIHelpers.standard_error_response(f"Error sending stats: {str(e)}")
        
        except Exception as e:
            return APIHelpers.standard_error_response(f"Server stats error: {str(e)}", 500)
        
        return APIHelpers.standard_error_response("Unknown action", 404)

def setup(bot, app):
    return ServerStatsModule(bot, app)