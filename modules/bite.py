# modules/bite.py
import discord
from discord.ext import commands
import aiohttp
import asyncio
from flask import jsonify

class BiteModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Bite"
        self.description = "Generate playful insults using the Evil Insult Generator API"
        self.icon = "zap"
        self.version = "1.0.1"
        self.commands = []
        self.html = self.get_html()
        
        # Register commands
        self._register_commands()
    
    def _register_commands(self):
        """Register all commands for this module"""
        
        @self.bot.command(name='bite')
        async def bite_command(ctx, target: discord.Member = None):
            """Bite someone with a random insult!"""
            if target is None:
                await ctx.send(f"🐕 Who should I bite? Try `bark-bite @username`")
                return
            
            # Don't let people bite themselves
            if target.id == ctx.author.id:
                await ctx.send(f"🤔 {ctx.author.mention}, you can't bite yourself! That's just weird.")
                return
            
            # Don't bite the bot
            if target.id == self.bot.user.id:
                await ctx.send(f"😤 {ctx.author.mention}, I'm not biting myself! Try someone else.")
                return
            
            # Don't bite other bots (usually)
            if target.bot:
                await ctx.send(f"🤖 {ctx.author.mention}, I don't bite other bots. That's not very nice!")
                return
            
            # Get insult from API
            insult = await self.get_insult()
            
            if insult:
                embed = discord.Embed(
                    title="🐕💨 Bark Bite!",
                    description=f"{target.mention}, {insult}",
                    color=discord.Color.orange()
                )
                embed.set_footer(text=f"Requested by {ctx.author.display_name} • Powered by Evil Insult Generator")
                await ctx.send(embed=embed)
            else:
                # Fallback if API fails
                fallback_insults = [
                    "you're about as useful as a chocolate teapot!",
                    "you have the personality of a wet mop!",
                    "you're so boring, you make watching paint dry seem exciting!",
                    "you're like a human participation trophy!",
                    "you have the charm of a soggy biscuit!"
                ]
                import random
                insult = random.choice(fallback_insults)
                
                embed = discord.Embed(
                    title="🐕💨 Bark Bite! (Offline Mode)",
                    description=f"{target.mention}, {insult}",
                    color=discord.Color.red()
                )
                embed.set_footer(text=f"Requested by {ctx.author.display_name} • API temporarily unavailable")
                await ctx.send(embed=embed)
        
        @self.bot.command(name='gentlebite', aliases=['nicebite'])
        async def gentle_bite_command(ctx, target: discord.Member = None):
            """A gentler version of bite for sensitive servers"""
            if target is None:
                await ctx.send(f"🐕 Who should I gently nibble? Try `bark-gentlebite @username`")
                return
            
            if target.id == ctx.author.id:
                await ctx.send(f"🤗 {ctx.author.mention}, you give yourself a gentle pat instead!")
                return
            
            if target.id == self.bot.user.id:
                await ctx.send(f"😊 {ctx.author.mention}, *wags tail happily*")
                return
            
            gentle_teases = [
                "you're so silly sometimes!",
                "you probably put pineapple on pizza!",
                "you're the type of person who reads instruction manuals!",
                "you probably fold your fitted sheets perfectly!",
                "you're suspiciously good at untangling Christmas lights!",
                "you probably enjoy elevator music!",
                "you're the person who actually reads terms and conditions!",
                "you probably have strong opinions about which way toilet paper should hang!"
            ]
            
            import random
            tease = random.choice(gentle_teases)
            
            embed = discord.Embed(
                title="🐕✨ Gentle Bark Nibble!",
                description=f"{target.mention}, {tease}",
                color=discord.Color.blue()
            )
            embed.set_footer(text=f"Requested by {ctx.author.display_name} • Just playful teasing!")
            await ctx.send(embed=embed)
        
        # Track the commands we added
        self.commands = ['bite', 'gentlebite']
    
    async def get_insult(self):
        """Get an insult from the Evil Insult Generator API"""
        try:
            async with aiohttp.ClientSession() as session:
                # Request plain text format for simpler parsing
                async with session.get('https://evilinsult.com/generate_insult.php?lang=en&type=text', timeout=5) as response:
                    if response.status == 200:
                        insult = await response.text()
                        # Clean up the insult (remove extra whitespace, etc.)
                        insult = insult.strip()
                        # Make sure it ends with proper punctuation
                        if not insult.endswith(('.', '!', '?')):
                            insult += '!'
                        return insult
                    else:
                        print(f"Evil Insult API returned status {response.status}")
                        return None
        except asyncio.TimeoutError:
            print("Evil Insult API timeout")
            return None
        except Exception as e:
            print(f"Error fetching insult: {e}")
            return None
    
    def get_html(self):
        """Return the HTML for this module's interface"""
        return '''
        <div class="module-header">
            <h2><i data-lucide="zap"></i> Bite (Insult Generator)</h2>
            <p>Generate playful insults using the Evil Insult Generator API.</p>
        </div>
        
        <div class="bite-container">
            <div class="info-section">
                <h3>📋 Commands</h3>
                <div class="command-list">
                    <div class="command-item">
                        <code>bark-bite @username</code>
                        <span>Send a random insult to someone</span>
                    </div>
                    <div class="command-item">
                        <code>bark-gentlebite @username</code>
                        <span>Send a gentle, playful tease instead</span>
                    </div>
                </div>
            </div>
            
            <div class="test-section">
                <h3>🧪 Test API</h3>
                <button class="btn btn-primary" onclick="testInsultAPI()">
                    <i data-lucide="zap"></i>
                    Get Random Insult
                </button>
                <div id="insult-result" class="api-result"></div>
            </div>
            
            <div class="stats-section">
                <h3>📊 Usage Info</h3>
                <p><strong>API:</strong> Evil Insult Generator</p>
                <p><strong>Rate Limit:</strong> No known limits</p>
                <p><strong>Fallback:</strong> Local insults if API fails</p>
                <p><strong>Safety:</strong> Prevents self-targeting and bot-targeting</p>
            </div>
        </div>
        
        <style>
        .bite-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }
        
        .info-section, .test-section, .stats-section {
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1.5rem;
        }
        
        .info-section h3, .test-section h3, .stats-section h3 {
            margin-bottom: 1rem;
            color: var(--text);
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .command-list {
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }
        
        .command-item {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }
        
        .command-item code {
            background: var(--background);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            color: var(--primary);
            font-weight: bold;
        }
        
        .command-item span {
            color: var(--text-muted);
            font-size: 0.9rem;
        }
        
        .api-result {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin-top: 1rem;
            min-height: 60px;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            color: var(--text);
            font-style: italic;
        }
        
        .api-result.loading {
            color: var(--text-muted);
        }
        
        .api-result.error {
            color: #ef4444;
        }
        
        .stats-section p {
            margin: 0.5rem 0;
            color: var(--text-muted);
        }
        
        .stats-section p strong {
            color: var(--text);
        }
        </style>
        
        <script>
        async function testInsultAPI() {
            const resultDiv = document.getElementById('insult-result');
            resultDiv.textContent = 'Loading insult...';
            resultDiv.className = 'api-result loading';
            
            try {
                const response = await fetch('/api/bite/test_insult');
                const data = await response.json();
                
                if (data.insult) {
                    resultDiv.textContent = data.insult;
                    resultDiv.className = 'api-result';
                } else {
                    resultDiv.textContent = 'Failed to get insult from API';
                    resultDiv.className = 'api-result error';
                }
            } catch (error) {
                resultDiv.textContent = 'Error testing API: ' + error.message;
                resultDiv.className = 'api-result error';
            }
        }
        </script>
        '''
    
    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "test_insult":
            # We need to run the async function in the bot's event loop
            if hasattr(self.bot, 'loop') and self.bot.loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    self.get_insult(),
                    self.bot.loop
                )
                try:
                    insult = future.result(timeout=10)
                    return jsonify({"insult": insult or "API temporarily unavailable"})
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
            else:
                return jsonify({"error": "Bot not ready"}), 503
        
        return jsonify({"error": "Unknown action"}), 404
    
    def cleanup(self):
        """Clean up when module is unloaded"""
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return BiteModule(bot, app)