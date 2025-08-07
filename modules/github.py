import discord
from discord.ext import commands

REPO_URL = "https://github.com/warmbo/bark"
REPO_NAME = "Bark"
REPO_DESC = "A modular Discord bot with a modern web dashboard."
REPO_ICON = "https://github.com/warmbo/bark/raw/main/bark.png"  # Optional: repo logo

class GithubModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "GitHub"
        self.description = "Show info and link to the Bark GitHub repository."
        self.icon = "brand-github"
        self.version = "1.0.0"
        self.commands = []
        self.html = self.get_html()
        
        self._register_commands()

    def _register_commands(self):
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

        # Track the commands we added
        self.commands = ['github']

    def get_html(self):
        return f'''
        <div class="module-header">
            <h2><i data-lucide="github"></i> GitHub</h2>
            <p>Show info and link to the Bark GitHub repository.</p>
        </div>
        
        <div class="github-container">
            <div class="info-section">
                <h3>📋 Commands</h3>
                <div class="command-list">
                    <div class="command-item">
                        <code>bark-github</code>
                        <span>Show GitHub repository information</span>
                    </div>
                </div>
            </div>
            
            <div class="repo-section">
                <h3>🔗 Repository</h3>
                <p><strong>Name:</strong> {REPO_NAME}</p>
                <p><strong>Description:</strong> {REPO_DESC}</p>
                <p><strong>URL:</strong> <a href="{REPO_URL}" target="_blank">{REPO_URL}</a></p>
            </div>
        </div>
        
        <style>
        .github-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
        }}
        
        .info-section, .repo-section {{
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        
        .info-section h3, .repo-section h3 {{
            margin-bottom: 1rem;
            color: var(--text);
        }}
        
        .command-list {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
        }}
        
        .command-item {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}
        
        .command-item code {{
            background: var(--background);
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            color: var(--primary);
            font-weight: bold;
        }}
        
        .command-item span {{
            color: var(--text-muted);
            font-size: 0.9rem;
        }}
        
        .repo-section p {{
            margin: 0.5rem 0;
            color: var(--text-muted);
        }}
        
        .repo-section p strong {{
            color: var(--text);
        }}
        
        .repo-section a {{
            color: var(--primary);
            text-decoration: none;
        }}
        
        .repo-section a:hover {{
            text-decoration: underline;
        }}
        </style>
        '''

    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "get_repo_info":
            return {
                "repo": {
                    "name": REPO_NAME,
                    "description": REPO_DESC,
                    "url": REPO_URL,
                    "icon": REPO_ICON
                }
            }
        
        return {"error": "Unknown action"}, 404

    def cleanup(self):
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return GithubModule(bot, app)