
import discord
from discord.ext import commands
import asyncio

class ModerationModule:
    name = "Moderation"
    version = "1.0.0"
    description = "Server moderation commands: erase chat, mute, unmute, kick, ban, userinfo."
    icon = "shield"

    def __init__(self, bot):
        self.bot = bot
        self.register_commands()

    def register_commands(self):
        @self.bot.command(name="erasechat", help="Delete the last N messages. Usage: !erasechat 50")
        @commands.has_permissions(manage_messages=True)
        async def erasechat(ctx, limit: int = 10):
            if limit < 1 or limit > 100:
                await ctx.send("❌ Please specify a number between 1 and 100.")
                return
            deleted = await ctx.channel.purge(limit=limit + 1)
            await ctx.send(f"🧹 Deleted {len(deleted)-1} messages.", delete_after=5)

        @self.bot.command(name="mute", help="Mute a user. Usage: !mute @user [minutes]")
        @commands.has_permissions(manage_roles=True)
        async def mute(ctx, member: discord.Member, minutes: int = 0):
            guild = ctx.guild
            mute_role = discord.utils.get(guild.roles, name="Muted")
            if not mute_role:
                mute_role = await guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False, speak=False))
                for channel in guild.channels:
                    await channel.set_permissions(mute_role, send_messages=False, speak=False)
            await member.add_roles(mute_role)
            await ctx.send(f"🔇 Muted {member.display_name}" + (f" for {minutes} minutes." if minutes > 0 else "."))
            if minutes > 0:
                await asyncio.sleep(minutes * 60)
                if mute_role in member.roles:
                    await member.remove_roles(mute_role)
                    await ctx.send(f"🔊 Unmuted {member.display_name} after {minutes} minutes.")

        @self.bot.command(name="unmute", help="Unmute a user. Usage: !unmute @user")
        @commands.has_permissions(manage_roles=True)
        async def unmute(ctx, member: discord.Member):
            mute_role = discord.utils.get(ctx.guild.roles, name="Muted")
            if mute_role in member.roles:
                await member.remove_roles(mute_role)
                await ctx.send(f"🔊 Unmuted {member.display_name}")
            else:
                await ctx.send(f"⚠️ {member.display_name} is not muted.")

        @self.bot.command(name="kick", help="Kick a user. Usage: !kick @user [reason]")
        @commands.has_permissions(kick_members=True)
        async def kick(ctx, member: discord.Member, *, reason: str = None):
            await member.kick(reason=reason)
            await ctx.send(f"👢 Kicked {member.display_name}" + (f" for: {reason}" if reason else "."))

        @self.bot.command(name="ban", help="Ban a user. Usage: !ban @user [reason]")
        @commands.has_permissions(ban_members=True)
        async def ban(ctx, member: discord.Member, *, reason: str = None):
            await member.ban(reason=reason)
            await ctx.send(f"🔨 Banned {member.display_name}" + (f" for: {reason}" if reason else "."))

        @self.bot.command(name="userinfo", help="Get info about a user. Usage: !userinfo @user")
        async def userinfo(ctx, member: discord.Member = None):
            member = member or ctx.author
            roles = [role.name for role in member.roles if role.name != "@everyone"]
            embed = discord.Embed(title=f"User Info - {member}", color=0x3498db)
            embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
            embed.add_field(name="ID", value=member.id, inline=True)
            embed.add_field(name="Display Name", value=member.display_name, inline=True)
            embed.add_field(name="Joined Server", value=member.joined_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            embed.add_field(name="Account Created", value=member.created_at.strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            embed.add_field(name="Roles", value=", ".join(roles) or "None", inline=False)
            await ctx.send(embed=embed)

def setup(bot, app=None):
    mod = ModerationModule(bot)
    return mod