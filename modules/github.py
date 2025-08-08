# modules/github.py
import discord
import aiohttp
import asyncio
from utils import BaseModule, APIHelpers, format_module_html

REPO_OWNER = "warmbo"
REPO_NAME = "bark"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"

class GithubModule(BaseModule):
    def __init__(self, bot, app):
        self.name = "GitHub"
        self.description = "Show live GitHub repository information and statistics."
        self.icon = "github"
        self.version = "2.0.0"
        
        super().__init__(bot, app)

    async def fetch_github_data(self):
        """Fetch repository data from GitHub API"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(GITHUB_API_URL, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            print(f"GitHub API Error: {e}")
            return None

    async def fetch_latest_release(self):
        """Fetch latest release information"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{GITHUB_API_URL}/releases/latest", timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    return None
        except Exception as e:
            print(f"GitHub Releases API Error: {e}")
            return None

    def _register_commands(self):
        @self.command(name="github", help="Show live GitHub repository information.")
        async def github_cmd(ctx):
            async with ctx.typing():
                repo_data = await self.fetch_github_data()
                
                if not repo_data:
                    embed = self.create_embed(
                        title="❌ GitHub Error",
                        description="Failed to fetch repository information from GitHub API.",
                        color=discord.Color.red()
                    )
                    await ctx.send(embed=embed)
                    return

                # Create rich embed with live data
                embed = self.create_embed(
                    title=f"📦 {repo_data.get('name', REPO_NAME)}",
                    description=repo_data.get('description', 'No description available'),
                    color=discord.Color.from_rgb(33, 37, 41)  # GitHub dark theme color
                )
                
                # Repository stats
                embed.add_field(
                    name="⭐ Stars", 
                    value=str(repo_data.get('stargazers_count', 0)), 
                    inline=True
                )
                embed.add_field(
                    name="🍴 Forks", 
                    value=str(repo_data.get('forks_count', 0)), 
                    inline=True
                )
                embed.add_field(
                    name="👁️ Watchers", 
                    value=str(repo_data.get('watchers_count', 0)), 
                    inline=True
                )
                embed.add_field(
                    name="📝 Language", 
                    value=repo_data.get('language', 'Unknown'), 
                    inline=True
                )
                embed.add_field(
                    name="📊 Size", 
                    value=f"{repo_data.get('size', 0)} KB", 
                    inline=True
                )
                embed.add_field(
                    name="🔓 License", 
                    value=repo_data.get('license', {}).get('name', 'None') if repo_data.get('license') else 'None', 
                    inline=True
                )
                
                # Links
                embed.add_field(
                    name="🔗 Links",
                    value=f"[Repository]({repo_data.get('html_url', REPO_URL)}) • [Issues]({repo_data.get('html_url', REPO_URL)}/issues) • [Releases]({repo_data.get('html_url', REPO_URL)}/releases)",
                    inline=False
                )
                
                # Last updated
                if repo_data.get('updated_at'):
                    updated_at = repo_data['updated_at'].replace('T', ' ').replace('Z', ' UTC')
                    embed.set_footer(text=f"Last updated: {updated_at}")
                
                await ctx.send(embed=embed)

        @self.command(name="release", help="Show the latest release information.")
        async def release_cmd(ctx):
            async with ctx.typing():
                release_data = await self.fetch_latest_release()
                
                if not release_data:
                    embed = self.create_embed(
                        title="❌ No Releases",
                        description="No releases found or failed to fetch release information.",
                        color=discord.Color.orange()
                    )
                    await ctx.send(embed=embed)
                    return

                embed = self.create_embed(
                    title=f"🚀 Latest Release: {release_data.get('tag_name', 'Unknown')}",
                    description=release_data.get('body', 'No release notes available')[:2000],  # Discord limit
                    color=discord.Color.green()
                )
                
                embed.add_field(
                    name="📅 Published", 
                    value=release_data.get('published_at', 'Unknown').replace('T', ' ').replace('Z', ' UTC'), 
                    inline=True
                )
                embed.add_field(
                    name="👤 Author", 
                    value=release_data.get('author', {}).get('login', 'Unknown'), 
                    inline=True
                )
                embed.add_field(
                    name="🔗 Download", 
                    value=f"[View Release]({release_data.get('html_url', REPO_URL)})", 
                    inline=True
                )
                
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
                    <span>Show live GitHub repository information with stats</span>
                </div>
                <div class="command-item">
                    <code>bark-release</code>
                    <span>Show the latest release information</span>
                </div>
            </div>
        </div>
        
        <div class="repo-section">
            <h3 class="section-title">
                <i data-lucide="database"></i>
                Live Repository Data
            </h3>
            <div class="api-test-section">
                <button class="btn btn-primary" onclick="fetchRepoData()">
                    <i data-lucide="refresh-cw"></i>
                    Fetch Live Data
                </button>
                <div id="repo-data" class="api-result"></div>
            </div>
        </div>
        
        <div class="links-section">
            <h3 class="section-title">
                <i data-lucide="link"></i>
                Quick Links
            </h3>
            <div class="repo-actions">
                <a href="{REPO_URL}" target="_blank" class="btn btn-primary">
                    <i data-lucide="external-link"></i>
                    View Repository
                </a>
                <a href="{REPO_URL}/issues" target="_blank" class="btn btn-secondary">
                    <i data-lucide="bug"></i>
                    Report Issue
                </a>
                <a href="{REPO_URL}/releases" target="_blank" class="btn btn-secondary">
                    <i data-lucide="download"></i>
                    Releases
                </a>
                <a href="{REPO_URL}/wiki" target="_blank" class="btn btn-secondary">
                    <i data-lucide="book"></i>
                    Documentation
                </a>
            </div>
        </div>
        
        <script>
        async function fetchRepoData() {{
            const resultDiv = document.getElementById('repo-data');
            const button = document.querySelector('button[onclick="fetchRepoData()"]');
            
            // Show loading state
            resultDiv.className = 'api-result loading';
            resultDiv.textContent = 'Fetching repository data...';
            button.disabled = true;
            
            try {{
                const response = await fetch('/api/github/get_repo_data');
                const data = await response.json();
                
                if (data.success && data.repo) {{
                    const repo = data.repo;
                    resultDiv.className = 'api-result success';
                    resultDiv.innerHTML = `
                        <div class="repo-stats">
                            <div class="stat-row">
                                <span class="stat-label">⭐ Stars:</span>
                                <span class="stat-value">${{repo.stargazers_count || 0}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">🍴 Forks:</span>
                                <span class="stat-value">${{repo.forks_count || 0}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">👁️ Watchers:</span>
                                <span class="stat-value">${{repo.watchers_count || 0}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">📝 Language:</span>
                                <span class="stat-value">${{repo.language || 'Unknown'}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">📊 Size:</span>
                                <span class="stat-value">${{repo.size || 0}} KB</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">🔓 License:</span>
                                <span class="stat-value">${{repo.license?.name || 'None'}}</span>
                            </div>
                            <div class="stat-row">
                                <span class="stat-label">📅 Updated:</span>
                                <span class="stat-value">${{new Date(repo.updated_at).toLocaleDateString()}}</span>
                            </div>
                        </div>
                        <div class="repo-description">
                            <strong>Description:</strong> ${{repo.description || 'No description available'}}
                        </div>
                    `;
                }} else {{
                    throw new Error(data.error || 'Failed to fetch repository data');
                }}
            }} catch (error) {{
                resultDiv.className = 'api-result error';
                resultDiv.textContent = 'Error: ' + error.message;
            }} finally {{
                button.disabled = false;
            }}
        }}
        
        // Auto-fetch data when module loads
        document.addEventListener('DOMContentLoaded', function() {{
            // Only fetch if this module is active
            if (document.getElementById('github') && document.getElementById('github').classList.contains('active')) {{
                fetchRepoData();
            }}
        }});
        </script>
        
        <style>
        .repo-section, .links-section {{
            background: var(--glass-bg);
            backdrop-filter: var(--blur);
            border: 1px solid var(--glass-border);
            border-radius: 12px;
            padding: 1.5rem;
        }}
        
        .api-test-section {{
            margin-top: 1rem;
        }}
        
        .repo-stats {{
            display: grid;
            gap: 0.5rem;
            margin-bottom: 1rem;
        }}
        
        .stat-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem;
            background: var(--surface);
            border-radius: 6px;
            border: 1px solid var(--border);
        }}
        
        .stat-label {{
            color: var(--text-muted);
            font-size: 0.9rem;
        }}
        
        .stat-value {{
            color: var(--text);
            font-weight: 500;
        }}
        
        .repo-description {{
            background: var(--surface);
            padding: 1rem;
            border-radius: 6px;
            border: 1px solid var(--border);
            color: var(--text-muted);
            line-height: 1.5;
        }}
        
        .repo-description strong {{
            color: var(--text);
        }}
        
        .repo-actions {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }}
        
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.75rem 1rem;
            border-radius: 6px;
            text-decoration: none;
            font-weight: 500;
            transition: all 0.2s ease;
            text-align: center;
        }}
        
        .btn-primary {{
            background: var(--primary);
            color: white;
            border: none;
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
        
        .btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }}
        
        @media (max-width: 768px) {{
            .repo-actions {{
                grid-template-columns: 1fr;
            }}
        }}
        </style>
        '''
        
        return format_module_html('github', self.name, self.description, self.icon, content)

    def handle_api(self, action, request):
        """Handle API requests for this module"""
        if action == "get_repo_data":
            try:
                # Run async function in bot's event loop
                repo_data = self.run_async_in_bot_loop(self.fetch_github_data())
                
                if repo_data:
                    return APIHelpers.standard_success_response({
                        "repo": repo_data
                    })
                else:
                    return APIHelpers.standard_error_response("Failed to fetch repository data from GitHub API")
                    
            except Exception as e:
                return APIHelpers.standard_error_response(str(e), 500)
        
        elif action == "get_release_data":
            try:
                # Run async function in bot's event loop
                release_data = self.run_async_in_bot_loop(self.fetch_latest_release())
                
                if release_data:
                    return APIHelpers.standard_success_response({
                        "release": release_data
                    })
                else:
                    return APIHelpers.standard_error_response("No releases found or failed to fetch release data")
                    
            except Exception as e:
                return APIHelpers.standard_error_response(str(e), 500)
        
        return APIHelpers.standard_error_response("Unknown action", 404)

def setup(bot, app):
    return GithubModule(bot, app)