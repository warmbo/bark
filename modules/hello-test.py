# modules/test.py
import discord
from discord.ext import commands

class TestModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Test Hello Module"
        self.description = "A simple testing and hello module"
        self.icon = "test-tube"
        self.version = "1.0.0"
        self.commands = []  # Track commands we add
        
        # Register commands
        self._register_commands()
    
    def _register_commands(self):
        """Register all commands for this module"""
        
        @self.bot.command(name='test')
        async def test_command(ctx):
            """Test command to verify the module is working"""
            embed = discord.Embed(
                title="✅ Test Successful!",
                description="The test module is working correctly.",
                color=discord.Color.green()
            )
            embed.add_field(name="Module", value=self.name, inline=True)
            embed.add_field(name="Version", value=self.version, inline=True)
            await ctx.send(embed=embed)
        
        @self.bot.command(name='hello')
        async def hello_command(ctx, *, name=None):
            """Say hello to someone"""
            if name:
                message = f"Hello, {name}! 👋"
            else:
                message = f"Hello, {ctx.author.display_name}! 👋"
            
            embed = discord.Embed(
                title="👋 Greetings!",
                description=message,
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
        
        # Track the commands we added
        self.commands = ['test', 'hello']
    
    def cleanup(self):
        """Clean up when module is unloaded"""
        # Remove our commands
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return TestModule(bot, app)