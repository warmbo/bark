import discord
from flask import jsonify
import asyncio

class SpeakAsBotModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Speak As Bot"
        self.description = "Send messages as the bot through a web interface"
        self.html = self.get_html()
    
    def get_html(self):
        """Return the HTML for this module's interface"""
        return '''
        <h2>Speak As Bot</h2>
        <p>Send a message as the bot to any channel in any server.</p>
        
        <div style="margin-top: 20px;">
            <label for="server-select">Select Server:</label><br>
            <select id="server-select" style="width: 300px; padding: 5px; margin: 10px 0;">
                <option value="">Loading servers...</option>
            </select>
        </div>
        
        <div style="margin-top: 10px;">
            <label for="channel-select">Select Channel:</label><br>
            <select id="channel-select" style="width: 300px; padding: 5px; margin: 10px 0;" disabled>
                <option value="">Select a server first</option>
            </select>
        </div>
        
        <div style="margin-top: 10px;">
            <label for="message-input">Message:</label><br>
            <textarea id="message-input" style="width: 500px; height: 100px; padding: 5px; margin: 10px 0;" placeholder="Enter your message here..."></textarea>
        </div>
        
        <button onclick="sendMessage()" style="background-color: #43b581; color: white; border: none; padding: 10px 20px; cursor: pointer; border-radius: 4px;">Send Message</button>
        
        <div id="status-message" style="margin-top: 20px; padding: 10px; display: none;"></div>
        
        <script>
            // Load servers when the module is opened
            function loadServers() {
                fetch('/api/speak_as_bot/get_servers')
                    .then(response => response.json())
                    .then(data => {
                        const serverSelect = document.getElementById('server-select');
                        serverSelect.innerHTML = '<option value="">Select a server</option>';
                        data.servers.forEach(server => {
                            const option = document.createElement('option');
                            option.value = server.id;
                            option.textContent = server.name;
                            serverSelect.appendChild(option);
                        });
                    });
            }
            
            // Load channels when a server is selected
            document.getElementById('server-select').addEventListener('change', function() {
                const serverId = this.value;
                const channelSelect = document.getElementById('channel-select');
                
                if (!serverId) {
                    channelSelect.disabled = true;
                    channelSelect.innerHTML = '<option value="">Select a server first</option>';
                    return;
                }
                
                fetch(`/api/speak_as_bot/get_channels?server_id=${serverId}`)
                    .then(response => response.json())
                    .then(data => {
                        channelSelect.disabled = false;
                        channelSelect.innerHTML = '<option value="">Select a channel</option>';
                        data.channels.forEach(channel => {
                            const option = document.createElement('option');
                            option.value = channel.id;
                            option.textContent = '#' + channel.name;
                            channelSelect.appendChild(option);
                        });
                    });
            });
            
            // Send message function
            function sendMessage() {
                const channelId = document.getElementById('channel-select').value;
                const message = document.getElementById('message-input').value;
                const statusDiv = document.getElementById('status-message');
                
                if (!channelId || !message) {
                    statusDiv.style.display = 'block';
                    statusDiv.style.backgroundColor = '#f04747';
                    statusDiv.textContent = 'Please select a channel and enter a message.';
                    return;
                }
                
                fetch('/api/speak_as_bot/send_message', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        channel_id: channelId,
                        message: message
                    })
                })
                .then(response => response.json())
                .then(data => {
                    statusDiv.style.display = 'block';
                    if (data.success) {
                        statusDiv.style.backgroundColor = '#43b581';
                        statusDiv.textContent = 'Message sent successfully!';
                        document.getElementById('message-input').value = '';
                    } else {
                        statusDiv.style.backgroundColor = '#f04747';
                        statusDiv.textContent = 'Error: ' + data.error;
                    }
                });
            }
            
            // Load servers when this module view becomes active
            const observer = new MutationObserver(function(mutations) {
                mutations.forEach(function(mutation) {
                    if (mutation.target.classList.contains('active')) {
                        loadServers();
                    }
                });
            });
            
            observer.observe(document.getElementById('speak_as_bot'), {
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
            
            # Send the message asynchronously
            async def send_msg():
                try:
                    channel = self.bot.get_channel(int(channel_id))
                    if channel:
                        await channel.send(message)
                        return True
                    return False
                except Exception as e:
                    print(f"Error sending message: {e}")
                    return False
            
            # Run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success = loop.run_until_complete(send_msg())
            
            if success:
                return jsonify({"success": True})
            else:
                return jsonify({"success": False, "error": "Failed to send message"}), 500
        
        return jsonify({"error": "Unknown action"}), 404

def setup(bot, app):
    """Setup function called by the main bot"""
    return SpeakAsBotModule(bot, app)