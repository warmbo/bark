import discord
from discord.ext import commands
from discord.ui import View, Button
import os
import sys
import requests
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


@bot.command(name='bark-help', help='Show help for all modules or a specific module.')
async def bark_help(ctx, module_name: str = None, page: int = 1):
    if not module_manager:
        await ctx.send("❌ Module manager not available.")
        return

    modules = module_manager.loaded_modules
    prefix = BOT_PREFIX

    if module_name:
        # Show help for a specific module
        mod = modules.get(module_name)
        if not mod:
            await ctx.send(f"❌ Module `{module_name}` not found.")
            return
        embed = discord.Embed(
            title=f"Help: {getattr(mod, 'name', module_name)}",
            description=getattr(mod, 'description', 'No description'),
            color=discord.Color.blue()
        )
        commands = getattr(mod, 'commands', [])
        if not commands:
            embed.add_field(name="Commands", value="No commands available.", inline=False)
        else:
            for cmd in commands:
                cmd_obj = bot.get_command(cmd)
                if cmd_obj:
                    embed.add_field(
                        name=f"{prefix}{cmd_obj.name}",
                        value=cmd_obj.help or "No description.",
                        inline=False
                    )
        await ctx.send(embed=embed)
        return

    # Paginated help for all modules
    module_names = list(modules.keys())
    per_page = 4
    total_pages = (len(module_names) + per_page - 1) // per_page
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    embed = discord.Embed(
        title=f"🐕 Bark Modules (Page {page}/{total_pages})",
        description="Use `bark-help <module>` for details.",
        color=discord.Color.blue()
    )
    for mod_name in module_names[start:end]:
        mod = modules[mod_name]
        mod_title = getattr(mod, 'name', mod_name)
        mod_desc = getattr(mod, 'description', 'No description')
        commands = getattr(mod, 'commands', [])
        cmd_list = ', '.join([f"`{prefix}{cmd}`" for cmd in commands]) if commands else "No commands"
        embed.add_field(
            name=mod_title,
            value=f"{mod_desc}\n**Commands:** {cmd_list}",
            inline=False
        )
    embed.set_footer(text=f"Use {prefix}bark-help <module> for module help. Page {page}/{total_pages}")
    await ctx.send(embed=embed)

@bot.command(name='modules')
async def modules_command(ctx):
    """List all currently loaded Bark modules"""
    if not module_manager:
        embed = discord.Embed(
            title="❌ Module Manager Not Available",
            description="Module manager is not initialized.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    loaded_modules = module_manager.loaded_modules
    
    embed = discord.Embed(
        title="🔧 Loaded Bark Modules",
        color=discord.Color.blue()
    )
    
    if loaded_modules:
        module_list = []
        for module_name, module_instance in loaded_modules.items():
            # Get display name and version if available
            display_name = getattr(module_instance, 'name', module_name)
            version = getattr(module_instance, 'version', '1.0.0')
            module_list.append(f"• **{display_name}** (`{module_name}`) - v{version}")
        
        embed.description = "\n".join(module_list)
        embed.set_footer(text=f"Total: {len(loaded_modules)} modules loaded")
    else:
        embed.description = "No modules are currently loaded."
        embed.color = discord.Color.orange()
    
    await ctx.send(embed=embed)

@bot.command(name='reload')
@commands.has_permissions(administrator=True)
async def reload_command(ctx, module_name: str = None):
    """Reload a specific module (Admin only)"""
    if not module_manager:
        embed = discord.Embed(
            title="❌ Module Manager Not Available",
            description="Module manager is not initialized.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    if not module_name:
        embed = discord.Embed(
            title="❌ Module Name Required",
            description="Please specify a module to reload.\nExample: `!reload weather`",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    if module_name not in module_manager.loaded_modules:
        embed = discord.Embed(
            title="❌ Module Not Found",
            description=f"Module `{module_name}` is not currently loaded.",
            color=discord.Color.red()
        )
        await ctx.send(embed=embed)
        return
    
    try:
        success = module_manager.reload_module(module_name)
        if success:
            embed = discord.Embed(
                title="✅ Module Reloaded",
                description=f"Successfully reloaded module `{module_name}`.",
                color=discord.Color.green()
            )
        else:
            embed = discord.Embed(
                title="❌ Reload Failed",
                description=f"Failed to reload module `{module_name}`. Check console for details.",
                color=discord.Color.red()
            )
    except Exception as e:
        embed = discord.Embed(
            title="❌ Reload Error",
            description=f"Error reloading module `{module_name}`: {str(e)}",
            color=discord.Color.red()
        )
    
    await ctx.send(embed=embed)




# New paginator: one module per page, first page is built-in commands
class HelpPaginator(View):
    def __init__(self, ctx, modules, prefix, page):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.modules = modules
        self.prefix = prefix
        self.page = page
        self.module_names = list(modules.keys())
        self.total_pages = len(self.module_names) + 1  # +1 for built-in commands

    async def interaction_check(self, interaction):
        return interaction.user == self.ctx.author

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.primary)
    async def previous(self, interaction: discord.Interaction, button: Button):
        if self.page > 1:
            self.page -= 1
            embed = build_help_embed(self.modules, self.prefix, self.page)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction: discord.Interaction, button: Button):
        if self.page < self.total_pages:
            self.page += 1
            embed = build_help_embed(self.modules, self.prefix, self.page)
            await interaction.response.edit_message(embed=embed, view=self)

def build_help_embed(modules, prefix, page):
    module_names = list(modules.keys())
    total_pages = len(module_names) + 1
    page = max(1, min(page, total_pages))
    if page == 1:
        # Built-in commands
        embed = discord.Embed(
            title=f"🐕 Bark Built-in Commands (Page 1/{total_pages})",
            description="These are always available. Use `help <module>` for module help.",
            color=discord.Color.blue()
        )
        cmd_lines = []
        for cmd in bot.commands:
            # Only show commands not associated with a module
            if not hasattr(cmd, 'module') or getattr(cmd, 'module', None) is None:
                cmd_lines.append(f"`{prefix}{cmd.name}` - {cmd.help or 'No description.'}")
        cmd_block = "\n".join(cmd_lines) if cmd_lines else "No built-in commands"
        embed.add_field(
            name="Commands\n\u200b",
            value=f"\n{cmd_block}\n\u200b",
            inline=False
        )
        embed.set_footer(text=f"Use {prefix}help <module> for module help. Page {page}/{total_pages}")
        return embed
    else:
        mod_name = module_names[page-2]
        mod = modules[mod_name]
        mod_title = getattr(mod, 'name', mod_name)
        mod_desc = getattr(mod, 'description', 'No description')
        commands = getattr(mod, 'commands', [])
        if not commands:
            commands = [cmd.name for cmd in bot.commands if getattr(cmd, 'module', None) == mod_name]
        if not commands:
            commands = [cmd.name for cmd in bot.commands if cmd.name.startswith(mod_name)]
        cmd_lines = []
        for cmd in commands:
            cmd_obj = bot.get_command(cmd)
            if cmd_obj:
                cmd_lines.append(f"`{prefix}{cmd_obj.name}` - {cmd_obj.help or 'No description.'}")
        cmd_block = "\n".join(cmd_lines) if cmd_lines else "No commands"
        embed = discord.Embed(
            title=f"Help: {mod_title} (Page {page}/{total_pages})",
            description=mod_desc,
            color=discord.Color.blue()
        )
        embed.add_field(
            name="Commands\n\u200b",
            value=f"\n{cmd_block}\n\u200b",
            inline=False
        )
        embed.set_footer(text=f"Use {prefix}help <module> for module help. Page {page}/{total_pages}")
        return embed


@bot.command(name='help', help='Show help for all modules or a specific module.')
async def help_command(ctx, module_name: str = None, page: int = 1):
    if not module_manager:
        await ctx.send("❌ Module manager not available.")
        return

    modules = module_manager.loaded_modules
    prefix = BOT_PREFIX

    if module_name:
        mod = modules.get(module_name)
        if not mod:
            await ctx.send(f"❌ Module `{module_name}` not found.")
            return
        embed = build_help_embed(modules, prefix, list(modules.keys()).index(module_name)+2 if module_name in modules else 1)
        await ctx.send(embed=embed)
        return

    view = HelpPaginator(ctx, modules, prefix, page)
    embed = build_help_embed(modules, prefix, view.page)
    await ctx.send(embed=embed, view=view)

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