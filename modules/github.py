import discord
from discord.ext import commands

REPO_URL = "https://github.com/warmbo/bark"
REPO_NAME = "Bark"
REPO_DESC = "A modular Discord bot with a modern web dashboard."
REPO_ICON = "https://github.com/warmbo/bark/raw/main/bark.png"  # Optional: repo logo

class GithubModule:
    name = "GitHub"
    description = "Show info and link to the Bark GitHub repository."
    version = "1.0.0"
    icon = "brand-github"
    commands = ["github", "modules"]

    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.register_commands()

    def register_commands(self):
        @self.bot.command(name="github", help="Show the GitHub repository info.")
        async def github_cmd(ctx):
            embed = discord.Embed(
                title=f"{REPO_NAME} Repository",
                description=REPO_DESC,
                color=discord.Color.dark_gray()
            )
            embed.add_field(name="GitHub", value=f"[View on GitHub]({REPO_URL})", inline=False)
            embed.set_thumbnail(url=REPO_ICON)
            await ctx.send(embed=embed)

        @self.bot.command(name="modules", help="List all currently loaded Bark modules.")
        async def modules_cmd(ctx):
            # Try to get loaded modules from the module manager
            module_manager = None
            # Search for module_manager in bot globals
            for cog in self.bot.cogs.values():
                if hasattr(cog, 'loaded_modules'):
                    module_manager = cog
                    break
            # Fallback: try to get from bot attributes
            if not module_manager and hasattr(self.bot, 'module_manager'):
                module_manager = getattr(self.bot, 'module_manager')
            # If not found, try to get from global
            if not module_manager:
                try:
                    import sys
                    module_manager = sys.modules.get('module_manager', None)
                except Exception:
                    module_manager = None

            # If still not found, try to get from app context
            loaded = []
            if hasattr(self.app, 'module_manager'):
                loaded = list(getattr(self.app, 'module_manager').loaded_modules.keys())
            elif module_manager and hasattr(module_manager, 'loaded_modules'):
                loaded = list(module_manager.loaded_modules.keys())
            else:
                # Fallback: try to get from bot attribute
                loaded = getattr(self.bot, 'loaded_modules', [])

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
        # Remove commands when module is unloaded
        self.bot.remove_command("github")
        self.bot.remove_command("modules")

    def get_html(self):
        # Simple dashboard card for this module
        return f"""
        <div class='github-module'>
            <h2><i class='ti ti-brand-github'></i> GitHub</h2>
            <p>Show info and link to the Bark GitHub repository.</p>
            <a href='{REPO_URL}' target='_blank'>View on GitHub</a>
        </div>
        """

def setup(bot, app):
    return GithubModule(bot, app)
