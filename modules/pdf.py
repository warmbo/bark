import requests
from discord import Embed

class PDFModule:
    name = "PDF Generator"
    version = "1.0.0"
    description = "Generate a PDF of a website using Microlink API."
    icon = "file-pdf"

    API_URL = "https://api.microlink.io"

    def __init__(self, bot):
        self.bot = bot
        self.api_key = None  # Add your Microlink API key here if you have one

    def generate_pdf(self, url):
        params = {
            "pdf": "true",
            "meta": "false"
        }
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        try:
            resp = requests.get(self.API_URL, params={"url": url, **params}, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "success":
                return data["data"]["pdf"]["url"]
            return None
        except Exception as e:
            print(f"Error generating PDF: {e}")
            return None

    async def send_pdf(self, ctx, url):
        if not url.startswith("http"):
            url = "https://" + url
        pdf_url = self.generate_pdf(url)
        if not pdf_url:
            await ctx.send(f"❌ Could not generate PDF for `{url}`.")
            return

        embed = Embed(
            title=f"📄 PDF of {url}",
            description=f"[Click here to download the PDF]({pdf_url})",
            color=0xff4444
        )
        embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/337/337946.png")
        await ctx.send(embed=embed)

    def register_commands(self):
        if "pdf" in self.bot.all_commands:
            self.bot.remove_command("pdf")

        @self.bot.command(name="pdf", help="Generate a PDF of a website. Usage: !pdf <url>")
        async def pdf_cmd(ctx, url: str = None):
            if not url:
                await ctx.send("❌ Please provide a URL. Example: `!pdf example.com`")
                return
            await self.send_pdf(ctx, url)

def setup(bot, app=None):
    mod = PDFModule(bot)
    mod.register_commands()
    return mod
