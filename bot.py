import discord
from discord.ext import commands
import importlib
import os
import sys
import asyncio
from flask import Flask, render_template, request, jsonify, send_from_directory
import threading
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
WEB_PORT = int(os.getenv('WEB_PORT', 5000))
BOT_PREFIX = os.getenv('BOT_PREFIX', '!')

# Validate required configuration
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found in .env file!")
    print("Please create a .env file with your bot token.")
    sys.exit(1)

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents)

# Flask app for web dashboard
app = Flask(__name__, static_folder='static', template_folder='templates')

# Store loaded modules
loaded_modules = {}

# Default theme settings
DEFAULT_THEME = {
    'primary': '#3b82f6',
    'secondary': '#64748b',
    'accent': '#06b6d4',
    'background': '#0f172a',
    'surface': '#1e293b',
    'text': '#f1f5f9'
}

def load_modules():
    """Load all modules from the modules directory"""
    modules_dir = "modules"
    if not os.path.exists(modules_dir):
        os.makedirs(modules_dir)
        return
    
    for filename in os.listdir(modules_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]
            try:
                spec = importlib.util.spec_from_file_location(
                    module_name, 
                    os.path.join(modules_dir, filename)
                )
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                if hasattr(module, 'setup'):
                    module_instance = module.setup(bot, app)
                    loaded_modules[module_name] = module_instance
                    print(f"Loaded module: {module_name}")
            except Exception as e:
                print(f"Failed to load module {module_name}: {e}")

@app.route('/')
def dashboard():
    return render_template('dashboard.html', modules=loaded_modules, theme=DEFAULT_THEME)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/theme', methods=['POST'])
def update_theme():
    """Update theme colors"""
    data = request.get_json()
    # In a real app, you'd save this to a database or config file
    # For now, we'll just return success
    return jsonify({"success": True})

@app.route('/api/dashboard/stats')
def dashboard_stats():
    """Get basic dashboard statistics"""
    total_servers = len(bot.guilds)
    total_members = sum(guild.member_count for guild in bot.guilds)
    online_members = sum(
        sum(1 for member in guild.members if member.status != discord.Status.offline)
        for guild in bot.guilds
    )
    
    return jsonify({
        "servers": total_servers,
        "members": total_members,
        "online": online_members
    })

@app.route('/api/<module_name>/<action>', methods=['GET', 'POST'])
def module_api(module_name, action):
    """Handle API requests for modules"""
    if module_name in loaded_modules:
        module = loaded_modules[module_name]
        if hasattr(module, 'handle_api'):
            return module.handle_api(action, request)
    return jsonify({"error": "Module or action not found"}), 404

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Web dashboard running on http://localhost:{WEB_PORT}')

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False)

def main():
    # Create directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Load modules
    load_modules()
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Run the bot
    bot.run(BOT_TOKEN)

if __name__ == "__main__":
    main()