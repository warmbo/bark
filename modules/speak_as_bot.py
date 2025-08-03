import discord
from flask import jsonify
import asyncio

class SpeakAsBotModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Speak As Bot"
        self.description = "Send messages as the bot through a web interface"
        self.icon = "message-circle"
        self.html = self.get_html()
    
    def get_html(self):
        """Return the HTML for this module's interface"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="message-circle"></i> Speak As Bot</h2>
            <p>Send messages as the bot to any channel in any server.</p>
        </div>
        
        <div class="form-container">
            <div class="form-group">
                <label for="server-select">Select Server</label>
                <select id="server-select" onchange="loadChannels(this.value)">
                    <option value="">Loading servers...</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="channel-select">Select Channel</label>
                <select id="channel-select" disabled>
                    <option value="">Select a server first</option>
                </select>
            </div>
            
            <div class="form-group">
                <label for="message-input">Message</label>
                <textarea 
                    id="message-input" 
                    placeholder="Enter your message here..." 
                    rows="4"
                ></textarea>
            </div>
            
            <div class="form-actions">
                <button class="btn btn-primary" onclick="sendMessage()">
                    <i data-lucide="send"></i>
                    Send Message
                </button>
            </div>
        </div>
        
        <script>
            // Auto-load servers when module becomes active
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.target.id === 'speak_as_bot' && 
                        mutation.target.classList.contains('active')) {
                        loadServers();
                        lucide.createIcons();
                    }
                });
            });
            
            const speakAsBotModule = document.getElementById('speak_as_bot');
            if (speakAsBotModule) {
                observer.observe(speakAsBotModule, {
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
        
        elif action == "send_message":
            data = request.get_json()
            channel_id = data.get('channel_id')
            message = data.get('message')
            
            if not channel_id or not message:
                return jsonify({"error": "Missing channel ID or message"}), 400
            
            try:
                if not hasattr(self.bot, 'loop') or self.bot.loop is None:
                    return jsonify({"success": False, "error": "Bot is not ready"}), 503
                
                if self.bot.loop.is_closed():
                    return jsonify({"success": False, "error": "Bot event loop is closed"}), 503
                
                channel = self.bot.get_channel(int(channel_id))
                if not channel:
                    return jsonify({"success": False, "error": "Channel not found"}), 404
                
                future = asyncio.run_coroutine_threadsafe(
                    channel.send(message),
                    self.bot.loop
                )
                
                future.result(timeout=10)
                return jsonify({"success": True})
                
            except asyncio.TimeoutError:
                return jsonify({"success": False, "error": "Message send timeout"}), 504
            except ValueError as e:
                return jsonify({"success": False, "error": "Invalid channel ID"}), 400
            except Exception as e:
                print(f"Error sending message: {e}")
                return jsonify({"success": False, "error": str(e)}), 500
        
        return jsonify({"error": "Unknown action"}), 404

def setup(bot, app):
    """Setup function called by the main bot"""
    return SpeakAsBotModule(bot, app)