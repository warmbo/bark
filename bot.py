import discord
from discord.ext import commands
from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sys
import threading
import time
import logging
import loader 
from dotenv import load_dotenv
from module_manager import ModuleManager

# --------------------
# Setup logging
# --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("BarkBot")

# --------------------
# Load env variables
# --------------------
load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
WEB_PORT = int(os.getenv('WEB_PORT', 5000))
BOT_PREFIX = os.getenv('BOT_PREFIX', 'bark-')
API_KEY = os.getenv('API_KEY')  # Optional

if not BOT_TOKEN:
    log.error("BOT_TOKEN not found in .env file!")
    sys.exit(1)

# --------------------
# Init bot + flask
# --------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=BOT_PREFIX, intents=intents, help_command=None)

app = Flask(__name__)
module_lock = threading.Lock()

# --------------------
# Module Manager placeholder
# --------------------
module_manager = None
stats_cache = {"time": 0, "data": {}}

# --------------------
# Optional API Key Security
# --------------------
@app.before_request
def require_api_key():
    if request.path.startswith("/api/") and API_KEY:
        token = request.headers.get("X-API-KEY")
        if token != API_KEY:
            return jsonify({"error": "Unauthorized"}), 401

# --------------------
# Helpers
# --------------------
def prepare_modules_for_template():
    """
    Build the modules dictionary passed to dashboard.html by:
      1) Starting with all filesystem modules
      2) Updating with loaded module data from module_manager if available
    """
    modules_data = {}

    # 1) Start with filesystem modules to ensure we get everything
    try:
        fs_modules = loader.load_modules()
        for name, info in fs_modules.items():
            modules_data[name] = {
                'name': info.get('name', name),
                'description': info.get('description', ''),
                'icon': info.get('icon', 'settings' if info.get('is_system_module') else 'puzzle'),
                'version': info.get('version', '1.0.0'),
                'is_system_module': info.get('is_system_module', False),
                'dependencies': info.get('dependencies', []),
                'html': info.get('html', '<p>No interface available</p>'),
                'enabled': True,
                'loaded': False
            }
    except Exception:
        log.exception("Failed to load filesystem modules for template")

    # 2) Update with actual loaded module data if module_manager is available
    with module_lock:
        if module_manager and getattr(module_manager, 'loaded_modules', None):
            for module_name, module_instance in module_manager.loaded_modules.items():
                try:
                    is_system = getattr(module_instance, 'is_system_module', False)
                    module_html = getattr(module_instance, 'html', '')
                    
                    # Try to get fresh HTML if get_html method exists
                    if callable(getattr(module_instance, 'get_html', None)):
                        try:
                            module_html = module_instance.get_html()
                        except Exception:
                            log.exception(f"Error in {module_name}.get_html()")
                            module_html = module_html or "<p>Error loading interface</p>"

                    # Update or add the module data
                    modules_data[module_name] = {
                        'name': getattr(module_instance, 'name', module_name),
                        'description': getattr(module_instance, 'description', 'No description'),
                        'icon': getattr(module_instance, 'icon', 'puzzle'),
                        'version': getattr(module_instance, 'version', '1.0.0'),
                        'is_system_module': is_system,
                        'dependencies': getattr(module_instance, 'dependencies', []),
                        'html': module_html or '<p>No interface available</p>',
                        'enabled': module_manager.module_configs.get(module_name, {}).get('enabled', True),
                        'loaded': True
                    }
                except Exception:
                    log.exception(f"Error preparing loaded module {module_name}")

            # Also update enabled status for filesystem modules based on config
            for name in modules_data:
                if name not in module_manager.loaded_modules:
                    modules_data[name]['enabled'] = module_manager.module_configs.get(name, {}).get('enabled', True)

    # 3) Sort: system modules first then alphabetically
    sorted_modules = dict(sorted(modules_data.items(), key=lambda x: (
        not x[1]['is_system_module'],
        x[1]['name'].lower()
    )))

    log.info(f"Template prepared with {len(sorted_modules)} modules")
    system_count = sum(1 for m in sorted_modules.values() if m['is_system_module'])
    loaded_count = sum(1 for m in sorted_modules.values() if m['loaded'])
    log.info(f"  System: {system_count}, Loaded: {loaded_count}")

    return sorted_modules

# --------------------
# Flask Routes
# --------------------
@app.route('/')
def dashboard():
    try:
        modules_data = prepare_modules_for_template()
        log.info(f"Dashboard accessed - {len(modules_data)} modules available")
        return render_template('dashboard.html', modules=modules_data)
    except Exception as e:
        log.exception("Dashboard error")
        return f"Dashboard Error: {str(e)}", 500

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/api/dashboard/stats')
def dashboard_stats():
    try:
        if time.time() - stats_cache["time"] < 10:
            return jsonify(stats_cache["data"])

        if not bot.is_ready():
            return jsonify({"servers": 0, "members": 0, "online": 0})

        total_servers = len(bot.guilds)
        total_members = sum(g.member_count or 0 for g in bot.guilds)
        online_members = sum(
            1 for g in bot.guilds for m in g.members
            if getattr(m, 'status', discord.Status.offline) != discord.Status.offline
        )

        data = {
            "servers": total_servers,
            "members": total_members,
            "online": online_members
        }
        stats_cache.update({"time": time.time(), "data": data})
        return jsonify(data)
    except Exception as e:
        log.error(f"Stats error: {e}")
        return jsonify({"servers": 0, "members": 0, "online": 0})

@app.route('/api/<module_name>/<action>', methods=['GET', 'POST'])
def module_api(module_name, action):
    try:
        with module_lock:
            if not module_manager or module_name not in module_manager.loaded_modules:
                return jsonify({"error": f"Module '{module_name}' not found", "success": False}), 404

            module = module_manager.loaded_modules[module_name]

        if hasattr(module, 'handle_api'):
            try:
                return module.handle_api(action, request)
            except Exception as e:
                log.exception(f"Module API error in {module_name}.{action}")
                return jsonify({"error": f"Module API error: {str(e)}", "success": False}), 500

        return jsonify({"error": "Module does not support API", "success": False}), 404
    except Exception as e:
        log.exception("General API error")
        return jsonify({"error": f"API error: {str(e)}", "success": False}), 500

# --------------------
# Discord Events
# --------------------
@bot.event
async def on_ready():
    log.info(f"{bot.user} connected to Discord!")
    log.info(f"Connected to {len(bot.guilds)} servers")
    for guild in bot.guilds:
        log.info(f"  - {guild.name} ({guild.id}) - {guild.member_count} members")
    log.info(f"Dashboard: http://localhost:{WEB_PORT}")
    if module_manager:
        log.info(f"{len(module_manager.loaded_modules)} modules active")

# --------------------
# Discord Commands
# --------------------
@bot.command(name='ping')
async def ping(ctx):
    """Check bot latency"""
    await ctx.send(f"Pong! Latency is {round(bot.latency * 1000)}ms")

@bot.command(name='modules')
async def list_modules(ctx):
    """List all loaded modules"""
    with module_lock:
        if not module_manager or not module_manager.loaded_modules:
            await ctx.send("No modules loaded.")
            return

        embed = discord.Embed(title="Loaded Modules", color=discord.Color.green())
        for name, module in module_manager.loaded_modules.items():
            status = "✅ Enabled" if module_manager.module_configs.get(name, {}).get("enabled", True) else "❌ Disabled"
            embed.add_field(name=name, value=status, inline=False)

        await ctx.send(embed=embed)

@bot.command(name='reload')
async def reload_module(ctx, module_name: str = None):
    """Reload a specific module or all modules"""
    if not module_name:
        await ctx.send("Please specify a module name or 'all'")
        return

    with module_lock:
        try:
            if module_name.lower() == "all":
                module_manager.reload_all_modules()
                await ctx.send("All modules reloaded.")
            else:
                success = module_manager.reload_module(module_name)
                if success:
                    await ctx.send(f"Module '{module_name}' reloaded.")
                else:
                    await ctx.send(f"Failed to reload module '{module_name}'.")
        except Exception as e:
            await ctx.send(f"Error reloading module: {e}")

# --------------------
# Startup Functions
# --------------------
def run_flask():
    try:
        app.run(host='0.0.0.0', port=WEB_PORT, debug=False, use_reloader=False)
    except Exception as e:
        log.error(f"Flask server error: {e}")

def main():
    global module_manager

    # Create directories
    for directory in ['templates', 'static/css', 'static/js', 'modules', 'system_modules']:
        os.makedirs(directory, exist_ok=True)

    log.info("Initializing Bark Discord Bot...")

    try:
        module_manager = ModuleManager(bot, app)
        bot.module_manager = module_manager
        app.config['module_manager'] = module_manager
        log.info("Module manager initialized")
    except Exception as e:
        log.error(f"Failed to initialize module manager: {e}")
        sys.exit(1)

    try:
        module_manager.load_all_modules()
        log.info("Module loading completed")
    except Exception as e:
        log.error(f"Module loading errors: {e}")

    with module_lock:
        loaded_modules = module_manager.loaded_modules
    if loaded_modules:
        log.info(f"Module Summary ({len(loaded_modules)} total):")
        system_modules = [n for n, i in loaded_modules.items() if getattr(i, 'is_system_module', False)]
        regular_modules = [n for n, i in loaded_modules.items() if not getattr(i, 'is_system_module', False)]
        if system_modules:
            log.info(f"  System: {', '.join(system_modules)}")
        if regular_modules:
            log.info(f"  Regular: {', '.join(regular_modules)}")
    else:
        log.warning("No modules loaded")

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    log.info("Starting Discord bot...")
    try:
        bot.run(BOT_TOKEN)
    except Exception as e:
        log.error(f"Bot failed to start: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()