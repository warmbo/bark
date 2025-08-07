import discord
from discord.ext import commands

class ModuleListModule:
    name = "Module List"
    description = "List all currently loaded Bark modules."
    version = "1.0.0"
    icon = "list"
    commands = ["modules"]

    def __init__(self, bot, app, module_manager):
        self.bot = bot
        self.app = app
        self.module_manager = module_manager
        self.register_commands()

    def register_commands(self):
        @self.bot.command(name="modules", help="List all currently loaded Bark modules.")
        async def modules_cmd(ctx):
            loaded = list(self.module_manager.loaded_modules.keys()) if self.module_manager else []
            embed = discord.Embed(
                title="Loaded Bark Modules",
                color=discord.Color.blue()
            )
            if loaded:
                embed.description = "\n".join(f"• {name}" for name in loaded)
            else:
                embed.description = "No modules are currently loaded."
            await ctx.send(embed=embed)

    def cleanup(self):
        self.bot.remove_command("modules")

    def get_html(self):
        return """
        <div class='module-list-module'>
            <h2><i class='ti ti-list'></i> Module List</h2>
            <p>List all currently loaded Bark modules with the <code>!modules</code> command.</p>
        </div>
        """

def setup(bot, app, module_manager):
    return ModuleListModule(bot, app, module_manager)
