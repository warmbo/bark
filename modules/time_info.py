import datetime
import pytz
from discord import Embed
from flask import jsonify

class TimeModule:
    name = "Time Info"
    version = "1.1.1"
    description = "Shows local/server time and major timezones."
    icon = "clock"

    def __init__(self, bot):
        self.bot = bot
        self.start_time = datetime.datetime.now(datetime.timezone.utc)

    def get_time_json(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        zones = {
            "UTC": pytz.utc,
            "EST (US Eastern)": pytz.timezone("US/Eastern"),
            "PST (US Pacific)": pytz.timezone("US/Pacific"),
            "CET (Central Europe)": pytz.timezone("Europe/Berlin"),
            "IST (India)": pytz.timezone("Asia/Kolkata"),
            "JST (Japan)": pytz.timezone("Asia/Tokyo"),
        }
        times = {}
        for label, tz in zones.items():
            times[label] = now_utc.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')

        # Local time (server)
        times["Server Time"] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Uptime
        uptime_delta = datetime.datetime.now(datetime.timezone.utc) - self.start_time
        hours, remainder = divmod(int(uptime_delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        times["Uptime"] = f"{hours}h {minutes}m {seconds}s"

        return times

    async def send_time_embed(self, ctx):
        times = self.get_time_json()

        embed = Embed(
            title="Time Information",
            color=0x3498db
        )
        embed.add_field(name="Server Time", value=times["Server Time"], inline=False)
        embed.add_field(name="Uptime", value=times["Uptime"], inline=False)
        embed.add_field(name="Timezones", value="", inline=False)
        for label in ["UTC", "EST (US Eastern)", "PST (US Pacific)", "CET (Central Europe)", "IST (India)", "JST (Japan)"]:
            embed.add_field(name=label, value=times[label], inline=True)
        await ctx.send(embed=embed)

    def register_commands(self):
        # Remove old command if it exists to prevent registration errors
        if "timeinfo" in self.bot.all_commands:
            self.bot.remove_command("timeinfo")

        @self.bot.command(name="timeinfo", help="Show current time in major timezones.")
        async def barktime_cmd(ctx):
            await self.send_time_embed(ctx)

def setup(bot, app=None):
    mod = TimeModule(bot)
    mod.register_commands()
    return mod

mod_for_api = None

def setup(bot, app=None):
    global mod_for_api
    mod = TimeModule(bot)
    mod.register_commands()
    mod_for_api = mod
    return mod

# Register Flask route at import time if app is available
try:
    from flask import current_app
    import flask
    # This will only work if 'app' is globally available at import time
    # If not, you should register this route in your main Flask app setup
    # For now, we check if 'app' is in globals and is a Flask app
    if 'app' in globals() and isinstance(globals()['app'], flask.Flask):
        app = globals()['app']
        @app.route('/api/time/zones')
        def api_time_zones():
            if mod_for_api:
                return jsonify(mod_for_api.get_time_json())
            else:
                return jsonify({"error": "Time module not loaded"}), 500
except Exception:
    pass
