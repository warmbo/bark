import discord
from discord.ext import commands
import os
import sys
import asyncio
from flask import Flask, render_template, request, jsonify, send_from_directory
import threading
import signal
from dotenv import load_dotenv
from module_manager import ModuleManager  # Import our new module manager

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

# Initialize bot with no default help command
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None)

# Flask app for web dashboard
app = Flask(__name__, static_folder='static', template_folder='templates')

# Initialize module manager
module_manager = None

# Default theme settings
DEFAULT_THEME = {
    'primary': '#3b82f6',
    'secondary': '#64748b',
    'accent': '#06b6d4',
    'background': '#0f172a',
    'surface': '#1e293b',
    'text': '#f1f5f9'
}

@app.route('/')
def dashboard():
    return render_template('dashboard.html', 
                         modules=module_manager.loaded_modules if module_manager else {}, 
                         theme=DEFAULT_THEME)

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/theme', methods=['POST'])
def update_theme():
    """Update theme colors"""
    data = request.get_json()
    # In a real app, you'd save this to a database or config file
    return jsonify({"success": True})

@app.route('/api/dashboard/stats')
def dashboard_stats():
    """Get basic dashboard statistics"""
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

@app.route('/api/modules', methods=['GET'])
def get_modules():
    """Get module information"""
    if not module_manager:
        return jsonify({"error": "Module manager not initialized"}), 500
    
    return jsonify(module_manager.get_module_info())

@app.route('/api/modules/<module_name>/enable', methods=['POST'])
def enable_module(module_name):
    """Enable a module"""
    if not module_manager:
        return jsonify({"error": "Module manager not initialized"}), 500
    
    success = module_manager.enable_module(module_name)
    return jsonify({"success": success})

@app.route('/api/modules/<module_name>/disable', methods=['POST'])
def disable_module(module_name):
    """Disable a module"""
    if not module_manager:
        return jsonify({"error": "Module manager not initialized"}), 500
    
    success = module_manager.disable_module(module_name)
    return jsonify({"success": success})

@app.route('/api/modules/<module_name>/reload', methods=['POST'])
def reload_module(module_name):
    """Reload a module"""
    if not module_manager:
        return jsonify({"error": "Module manager not initialized"}), 500
    
    success = module_manager.reload_module(module_name)
    return jsonify({"success": success})

@app.route('/api/<module_name>/<action>', methods=['GET', 'POST'])
def module_api(module_name, action):
    """Handle API requests for modules"""
    if not module_manager or module_name not in module_manager.loaded_modules:
        return jsonify({"error": "Module not found"}), 404
    
    module = module_manager.loaded_modules[module_name]
    if hasattr(module, 'handle_api'):
        return module.handle_api(action, request)
    
    return jsonify({"error": "Module does not support API"}), 404

@bot.event
async def on_ready():
    print(f'🤖 {bot.user} has connected to Discord!')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    print(f'🌐 Web dashboard running on http://localhost:{WEB_PORT}')

@bot.command(name='reload')
@commands.has_permissions(administrator=True)
async def reload_module_command(ctx, module_name=None):
    """Reload a module or all modules (Admin only)"""
    if not module_manager:
        await ctx.send("❌ Module manager not available")
        return
    
    if module_name:
        success = module_manager.reload_module(module_name)
        if success:
            await ctx.send(f"✅ Reloaded module: `{module_name}`")
        else:
            await ctx.send(f"❌ Failed to reload module: `{module_name}`")
    else:
        # Reload all modules
        module_manager.load_all_modules()
        await ctx.send("🔄 Reloaded all modules")

@bot.command(name='modules')
async def list_modules_command(ctx):
    """List all available modules"""
    if not module_manager:
        await ctx.send("❌ Module manager not available")
        return
    
    info = module_manager.get_module_info()
    
    embed = discord.Embed(title="📦 Bark Modules", color=discord.Color.blue())
    
    if info['loaded']:
        loaded_list = []
        for name, data in info['loaded'].items():
            status = "🟢" if data['enabled'] else "🔴"
            loaded_list.append(f"{status} **{data['name']}** - {data['description']}")
        
        embed.add_field(
            name="Loaded Modules",
            value="\n".join(loaded_list) if loaded_list else "None",
            inline=False
        )
    
    if info['available']:
        available_list = []
        for name, data in info['available'].items():
            status = "⚪" if data['enabled'] else "🔴"
            available_list.append(f"{status} **{name}** (Not loaded)")
        
        embed.add_field(
            name="Available Modules",
            value="\n".join(available_list) if available_list else "None",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.command(name='help', aliases=['commands'])
async def help_command(ctx, command=None):
    """Show available commands"""
    if command:
        # Show help for specific command
        cmd = bot.get_command(command)
        if cmd:
            embed = discord.Embed(
                title=f"Help: {BOT_PREFIX}{cmd.name}",
                description=cmd.help or "No description available",
                color=discord.Color.blue()
            )
            if cmd.aliases:
                embed.add_field(name="Aliases", value=", ".join(cmd.aliases), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ Command `{command}` not found. Use `{BOT_PREFIX}help` to see all commands.")
    else:
        # Show all commands
        embed = discord.Embed(title="🐕 Bark Commands", color=discord.Color.blue())
        
        core_commands = [
            f"`{BOT_PREFIX}help` - Show this help message",
            f"`{BOT_PREFIX}modules` - List all modules", 
            f"`{BOT_PREFIX}reload <module>` - Reload a module (Admin only)"
        ]
        
        embed.add_field(name="Core Commands", value="\n".join(core_commands), inline=False)
        
        # Get commands from loaded modules
        module_commands = []
        for command in bot.commands:
            if command.name not in ['help', 'modules', 'reload']:
                module_commands.append(f"`{BOT_PREFIX}{command.name}` - {command.help or 'No description'}")
        
        if module_commands:
            embed.add_field(name="Module Commands", value="\n".join(module_commands), inline=False)
        
        embed.set_footer(text=f"Use {BOT_PREFIX}help <command> for detailed help on a specific command")
        await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        # Extract the command name from the error
        command_name = ctx.message.content.split()[0][len(BOT_PREFIX):]
        
        # Check if it might be a typo of an existing command
        suggestions = []
        for cmd in bot.commands:
            if command_name.lower() in cmd.name.lower() or cmd.name.lower() in command_name.lower():
                suggestions.append(cmd.name)
        
        embed = discord.Embed(
            title="❌ Command Not Found", 
            color=discord.Color.red()
        )
        embed.add_field(
            name="Unknown Command",
            value=f"The command `{command_name}` was not found.",
            inline=False
        )
        
        if suggestions:
            embed.add_field(
                name="Did you mean?",
                value=", ".join(f"`{BOT_PREFIX}{cmd}`" for cmd in suggestions[:3]),
                inline=False
            )
        
        embed.add_field(
            name="Available Commands",
            value=f"Use `{BOT_PREFIX}help` to see all available commands.",
            inline=False
        )
        
        await ctx.send(embed=embed)
        
    elif isinstance(error, commands.MissingPermissions):
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You don't have permission to use this command.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        
    elif isinstance(error, commands.BadArgument):
        embed = discord.Embed(
            title="❌ Invalid Arguments",
            description=f"Invalid arguments provided. Use `{BOT_PREFIX}help {ctx.command.name}` for help.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        
    elif isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❌ Missing Arguments",
            description=f"Missing required arguments. Use `{BOT_PREFIX}help {ctx.command.name}` for help.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        
    else:
        # Log other errors but don't spam users
        print(f"Unhandled command error: {error}")
        embed = discord.Embed(
            title="❌ Command Error",
            description="An error occurred while processing your command.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)

def cleanup():
    """Cleanup function"""
    global module_manager
    if module_manager:
        print("🧹 Cleaning up modules...")
        module_manager.cleanup()

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
    cleanup()
    sys.exit(0)

def run_flask():
    """Run Flask in a separate thread"""
    try:
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)
    except Exception as e:
        print(f"Flask error: {e}")

def main():
    global module_manager
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create directories
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    
    # Initialize module manager
    print("🔧 Initializing module manager...")
    module_manager = ModuleManager(bot, app)
    
    # Load all modules
    print("📦 Loading modules...")
    module_manager.load_all_modules()
    
    # Start Flask in a separate thread
    print(f"🌐 Starting web dashboard on port {WEB_PORT}...")
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    try:
        # Run the bot
        print("🚀 Starting Discord bot...")
        bot.run(BOT_TOKEN)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")
    except Exception as e:
        print(f"Bot error: {e}")
    finally:
        cleanup()

if __name__ == "__main__":
    main()