# modules/member_info.py
import discord
from discord.ext import commands
from flask import jsonify, request

class MemberInfoModule:
    def __init__(self, bot, app):
        self.bot = bot
        self.app = app
        self.name = "Member Info"
        self.description = "View information about Discord members."
        self.icon = "users"
        self.version = "1.0.0"
        self.commands = []
        self.html = self.get_html()
        self._register_commands()

    def _register_commands(self):
        @self.bot.command(name='memberinfo')
        async def memberinfo_command(ctx, member: discord.Member = None):
            """Show info about a Discord member."""
            if member is None:
                member = ctx.author
            embed = discord.Embed(title=f"Info for {member.display_name}", color=discord.Color.green())
            embed.set_thumbnail(url=member.avatar.url if member.avatar else discord.Embed.Empty)
            embed.add_field(name="Username", value=f"{member.name}#{member.discriminator}", inline=True)
            embed.add_field(name="ID", value=member.id, inline=True)
            embed.add_field(name="Joined Server", value=member.joined_at.strftime('%Y-%m-%d'), inline=True)
            embed.add_field(name="Account Created", value=member.created_at.strftime('%Y-%m-%d'), inline=True)
            embed.add_field(name="Roles", value=", ".join([role.name for role in member.roles if role.name != "@everyone"]) or "None", inline=False)
            embed.add_field(name="Status", value=str(member.status).title(), inline=True)
            await ctx.send(embed=embed)
            
        self.commands = ['memberinfo']

    def get_html(self):
        return '''
        <div class="module-header">
            <h2><i data-lucide="users"></i> Member Info</h2>
            <p>View information about Discord members.</p>
        </div>
        <div class="memberinfo-container">
            <div class="info-section">
                <h3>📋 Commands</h3>
                <div class="command-list">
                    <div class="command-item">
                        <code>bark-memberinfo @username</code>
                        <span>Show info about a Discord member</span>
                    </div>
                </div>
            </div>
            <div class="test-section">
                <h3>🧪 Test API</h3>
                <input type="text" id="test-member-id" placeholder="Enter Member ID">
                <button class="btn btn-primary" onclick="testMemberInfoAPI()">
                    <i data-lucide="users"></i>
                    Get Member Info
                </button>
                <div id="memberinfo-result" class="api-result"></div>
            </div>
        </div>
        <script>
        async function testMemberInfoAPI() {
            const memberId = document.getElementById('test-member-id').value;
            const resultDiv = document.getElementById('memberinfo-result');
            resultDiv.textContent = 'Loading member info...';
            resultDiv.className = 'api-result loading';
            try {
                const response = await fetch(`/api/member_info/get_member?member_id=${memberId}`);
                const data = await response.json();
                if (data.member) {
                    resultDiv.textContent = JSON.stringify(data.member, null, 2);
                    resultDiv.className = 'api-result';
                } else {
                    resultDiv.textContent = data.error || 'Member not found.';
                    resultDiv.className = 'api-result error';
                }
            } catch (error) {
                resultDiv.textContent = 'Error: ' + error.message;
                resultDiv.className = 'api-result error';
            }
        }
        </script>
        <style>
        .memberinfo-container { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1.5rem; }
        .info-section, .test-section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
        .command-list { display: flex; flex-direction: column; gap: 1rem; }
        .command-item { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; }
        .api-result { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-top: 1rem; min-height: 60px; text-align: left; color: var(--text); font-style: italic; white-space: pre-wrap; }
        .api-result.loading { color: var(--text-muted); }
        .api-result.error { color: #ef4444; }
        </style>
        '''

    def handle_api(self, action, request):
        if action == "get_member":
            member_id = request.args.get('member_id')
            for guild in self.bot.guilds:
                member = guild.get_member(int(member_id)) if member_id else None
                if member:
                    return jsonify({
                        "member": {
                            "id": member.id,
                            "name": member.name,
                            "display_name": member.display_name,
                            "discriminator": member.discriminator,
                            "avatar": member.avatar.url if member.avatar else None,
                            "joined_at": member.joined_at.strftime('%Y-%m-%d') if member.joined_at else None,
                            "created_at": member.created_at.strftime('%Y-%m-%d') if member.created_at else None,
                            "roles": [role.name for role in member.roles if role.name != "@everyone"],
                            "status": str(member.status)
                        }
                    })
            return jsonify({"error": "Member not found"}), 404
        return jsonify({"error": "Unknown action"}), 404

    def cleanup(self):
        for cmd_name in self.commands:
            if cmd_name in self.bot.all_commands:
                self.bot.remove_command(cmd_name)
        print(f"🧹 Cleaned up {len(self.commands)} commands from {self.name}")

def setup(bot, app):
    return MemberInfoModule(bot, app)
