import discord
from discord.ext import commands
import os
import sys
from flask import Flask, render_template, request, jsonify, send_from_directory
import threading
from dotenv import load_dotenv
from module_manager import ModuleManager

# Load environment variables
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
WEB_PORT = int(os.getenv('WEB_PORT', 5000))
BOT_PREFIX = os.getenv('BOT_PREFIX', '!')

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not found in .env file!")
    sys.exit(1)

# Initialize bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None)

# Flask app
app = Flask(__name__)
module_manager = None

@app.route('/')
def dashboard():
    return render_template('dashboard.html', 
                         modules=module_manager.loaded_modules if module_manager else {})

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/dashboard/stats')
def dashboard_stats():
    if not bot.is_ready():
        return jsonify({"servers": 0, "members": 0, "online": 0})
    
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
    if not module_manager or module_name not in module_manager.loaded_modules:
        return jsonify({"error": "Module not found"}), 404
    
    module = module_manager.loaded_modules[module_name]
    if hasattr(module, 'handle_api'):
        return module.handle_api(action, request)
    
    return jsonify({"error": "Module does not support API"}), 404

@bot.event
async def on_ready():
    print(f'🤖 {bot.user} connected to Discord!')
    print(f'📊 {len(bot.guilds)} servers')
    print(f'🌐 Dashboard: http://localhost:{WEB_PORT}')

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(title="🐕 Bark Commands", color=discord.Color.blue())
    
    commands_list = []
    for command in bot.commands:
        commands_list.append(f"`{BOT_PREFIX}{command.name}` - {command.help or 'No description'}")
    
    embed.add_field(name="Commands", value="\n".join(commands_list), inline=False)
    await ctx.send(embed=embed)

def run_flask():
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)

def main():
    global module_manager
    
    # Create directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Initialize module manager
    module_manager = ModuleManager(bot, app)
    # Attach module_manager to bot and app for module access
    bot.module_manager = module_manager
    app.module_manager = module_manager
    module_manager.load_all_modules()
    
    # Start Flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run bot
    bot.run(BOT_TOKEN)

if __name__ == "__main__":
    main()