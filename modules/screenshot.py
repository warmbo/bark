import requests
from discord import Embed
from flask import jsonify

class ScreenshotModule:
    name = "Screenshot"
    version = "1.0.0"
    description = "Takes a screenshot of a given website using Microlink API."
    icon = "camera"

    def __init__(self, bot):
        self.bot = bot
        # If you have a Microlink API key, put it here (not required for basic usage)
        self.api_key = None

    def take_screenshot(self, target_url):
        api_url = "https://api.microlink.io"
        params = {
            "url": target_url,
            "screenshot": "true",
            "meta": "false"
        }
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        resp = requests.get(api_url, params=params, headers=headers)
        data = resp.json()

        if data.get("status") == "success":
            return data["data"]["screenshot"]["url"]
        return None

    async def send_screenshot(self, ctx, target_url):
        screenshot_url = self.take_screenshot(target_url)
        if not screenshot_url:
            await ctx.send(f"❌ Could not take a screenshot of `{target_url}`.")
            return

        embed = Embed(
            title=f"📸 Screenshot of {target_url}",
            description=f"Here’s what I found:",
            color=0x00ff99
        )
        embed.set_image(url=screenshot_url)
        await ctx.send(embed=embed)

    def register_commands(self):
        # Remove old command if exists
        if "screenshot" in self.bot.all_commands:
            self.bot.remove_command("screenshot")

        @self.bot.command(name="screenshot", help="Take a screenshot of a website. Usage: !screenshot <url>")
        async def screenshot_cmd(ctx, url: str = None):
            if not url:
                await ctx.send("❌ Please provide a URL. Example: `!screenshot google.com`")
                return
            if not url.startswith("http"):
                url = "https://" + url
            await self.send_screenshot(ctx, url)

def setup(bot, app=None):
    mod = ScreenshotModule(bot)
    mod.register_commands()
    if app:
        @app.route('/api/screenshot/<path:target_url>')
        def api_screenshot(target_url):
            screenshot_url = mod.take_screenshot(target_url)
            return jsonify({"url": screenshot_url})
    return mod
