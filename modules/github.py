# modules/github.py
import discord
from utils import BaseModule, APIHelpers, format_module_html

REPO_URL = "https://github.com/warmbo/bark"
REPO_NAME = "Bark"
REPO_DESC = "A modular Discord bot with a modern web dashboard."
REPO_ICON = "https://github.com/warmbo/bark/raw/main/bark.png"  # Optional: repo logo

class GithubModule(BaseModule):
    def __init__(self, bot, app):
        self.name = "GitHub"
        self.description = "Show info and link to the Bark GitHub repository."
        self.icon = "github"
        self.version = "1.0.0"
        
        super().__init__(bot, app)

    def _register_commands(self):
        @self.command(name="github", help="Show the GitHub repository info.")
        async def github_cmd(ctx):
            embed = self.create_embed(
                title=f"{REPO_NAME} Repository",
                description=REPO_DESC,
                color=discord.Color.dark_gray()
            )
            embed.add_field(name="GitHub", value=f"[View on GitHub]({REPO_URL})", inline=False)
            embed.set_thumbnail(url=REPO_ICON)
            await ctx.send(embed=embed)

    def get_html(self):
        content = f'''
        <div class="info-section">
            <h3 class="section-title">
                <i data-lucide="terminal"></i>
                Commands
            </h3>
            <div class="command-list">
                <div class="command-item">
                    <code>bark-github</code>
                    <span>Show GitHub repository information</span>
                </div>
            </div>
        </div>
        
        <div class="repo-section">
            <h3 class="section-title">
                <i data-lucide="link"></i>
                Repository
            </h3>
            <div class="repo-info">
                <div class="repo-detail">
                    <strong>Name:</strong> {REPO_NAME}
                </div>
                <div class="repo-detail">
                    <strong>Description:</strong> {REPO_DESC}
                </div>
                <div class="repo-detail">
                    <strong>URL:</strong> 
                    <a href="{REPO_URL}" target="_blank" class="repo-link">
                        {REPO_URL}
                    </a>
                </div>
            </div>
            
            <div class="repo-actions">
                <a href="{REPO_URL}" target="_blank" class="btn btn-primary">
                    <i data-lucide="external-link"></i>
                    View on GitHub
                </a>
                <a href="{REPO_URL}/issues" target="_blank" class="btn btn-secondary">
                    <i data-lucide="bug"></i>
                    Report Issue
                </a>
            </div>
        </div>
        
        <style>
        .repo-section {{
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        
        .repo-info {{
            margin: 1rem 0;
        }}
        
        .repo-detail {{
            margin: 0.75rem 0;
            color: var(--text-muted);
        }}
        
        .repo-detail strong {{
            color: var(--text);
        }}
        
        .repo-link {{
            color: var(--primary);
            text-decoration: none;
            word-break: break-all;
        }}
        
        .repo-link:hover {{
            text-decoration: underline;
        }}
        
        .repo-actions {{
            display: flex;
            gap: 1rem;
            margin-top: 1.5rem;
        }}
        
        .btn {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s ease;
        }}
        
        .btn-primary {{
            background: var(--primary);
            color: white;
        }}
        
        .btn-secondary {{
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--border);
        }}
        
        .btn:hover {{
            opacity: 0.9;
            transform: translateY(-1px);
        }}
        
        @media (max-width: 768px) {{
            .repo-actions {{
                flex-direction: column;
            }}
        }}
        </style>
        '''
        
        return format_module_html('github', self.name, self.description, self.icon, content)

    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "get_repo_info":
            return APIHelpers.standard_success_response({
                "repo": {
                    "name": REPO_NAME,
                    "description": REPO_DESC,
                    "url": REPO_URL,
                    "icon": REPO_ICON
                }
            })
        
        return APIHelpers.standard_error_response("Unknown action", 404)

def setup(bot, app):
    return GithubModule(bot, app)