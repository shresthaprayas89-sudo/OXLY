import discord
from discord.ext import commands
import pytesseract
from PIL import Image
import cv2
import numpy as np
import re
import io
import os

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

RANKS = [
    "Warrior",
    "Elite",
    "Master",
    "Grandmaster",
    "Epic",
    "Legend",
    "Mythic",
    "Mythic Honor",
    "Mythical Glory",
    "Mythical Immortal"
]

user_warnings = {}


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


def preprocess(img):
    try:
        img = np.array(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, th = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
        return Image.fromarray(th)
    except:
        return img


def extract_text(img):
    try:
        img = preprocess(img)
        return pytesseract.image_to_string(img, config="--psm 6")
    except:
        return ""


def extract_player_id(text):
    try:
        match = re.search(r"\d{5,10}\(\d{3,6}\)", text)
        return match.group(0) if match else None
    except:
        return None


def extract_server(text):
    try:
        match = re.search(r"\((\d{3,6})\)", text)
        return match.group(1) if match else None
    except:
        return None


def detect_rank(image):
    try:
        img = np.array(image)
        h, w, _ = img.shape

        y1 = int(h * 0.15)
        y2 = int(h * 0.55)
        x1 = int(w * 0.45)
        x2 = int(w * 0.90)

        if y2 <= y1 or x2 <= x1:
            return None, 0

        crop = img[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    except:
        return None, 0

    best_rank = None
    best_score = 0

    base_ranks = [
        "Warrior",
        "Elite",
        "Master",
        "Grandmaster",
        "Epic",
        "Legend",
        "Mythic",
        "Mythical Glory",
        "Mythical Immortal"
    ]

    for r in base_ranks:
        try:
            filename = f"{r.lower().replace(' ', '_')}.png"
            path = os.path.join("ranks", filename)

            if not os.path.exists(path):
                continue

            template = cv2.imread(path, 0)

            if template is None:
                continue

            if template.shape[0] > gray.shape[0] or template.shape[1] > gray.shape[1]:
                continue

            res = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, _ = cv2.minMaxLoc(res)

            if score > best_score:
                best_score = score
                best_rank = r

        except:
            continue

    if best_score > 0.50:
        return best_rank, best_score

    return None, 0


def detect_stars(image):
    try:
        img = np.array(image)
        h, w, _ = img.shape

        y1 = int(h * 0.60)
        y2 = int(h * 0.95)
        x1 = int(w * 0.55)
        x2 = int(w * 0.95)

        if y2 <= y1 or x2 <= x1:
            return None

        crop = img[y1:y2, x1:x2]

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, th = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

        text = pytesseract.image_to_string(
            th,
            config="--psm 6 -c tessedit_char_whitelist=0123456789"
        )

        match = re.search(r"\d{1,3}", text)

        if match:
            return int(match.group())

    except:
        return None

    return None


def ui_check(text):
    try:
        keywords = ["Player", "Rank", "Like"]

        found = 0
        for k in keywords:
            if k.lower() in text.lower():
                found += 1

        return found >= 2
    except:
        return False


async def remove_old(member):
    try:
        for r in RANKS:
            role = discord.utils.get(member.guild.roles, name=r)
            if role and role in member.roles:
                await member.remove_roles(role)
    except:
        pass


@bot.command()
async def verify(ctx):

    if ctx.guild is None:
        return

    channel_name = getattr(ctx.channel, "name", "")
    if channel_name.lower() != "verify":
        return

    if not ctx.message.attachments:
        await ctx.send("Upload MLBB profile screenshot")
        return

    attachment = ctx.message.attachments[0]

    filename = (attachment.filename or "").lower()
    content_type = attachment.content_type or ""

    if not (
        content_type.startswith("image")
        or filename.endswith((".png", ".jpg", ".jpeg", ".webp"))
    ):
        await ctx.send("Upload image only")
        return

    await ctx.send("Scanning screenshot...")

    try:
        image_bytes = await attachment.read()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except:
        await ctx.send("Invalid image")
        return

    text = extract_text(image)

    player_id = extract_player_id(text)
    server = extract_server(text)

    rank, score = detect_rank(image)
    stars = detect_stars(image)

    if rank == "Mythic" and stars:
        if stars >= 100:
            rank = "Mythical Immortal"
        elif stars >= 50:
            rank = "Mythical Glory"
        elif stars >= 25:
            rank = "Mythic Honor"

    valid_ui = ui_check(text)

    missing = []

    if not player_id:
        missing.append("Player ID")

    if not server:
        missing.append("Server ID")

    if not rank:
        missing.append("Rank")

    if not valid_ui:
        missing.append("Profile UI")

    if rank == "Mythic" and not stars:
        missing.append("Stars")

    user_id = ctx.author.id

    if missing:
        user_warnings[user_id] = user_warnings.get(user_id, 0) + 1

        if user_warnings[user_id] == 1:
            msg = "⚠️ Screenshot incomplete\nMissing:\n"
            for m in missing:
                msg += f"• {m}\n"

            await ctx.send(msg)
            return

        mod = discord.utils.get(ctx.guild.channels, name="mod-review")

        if mod:
            await mod.send(f"⚠️ Repeated invalid from {ctx.author.mention}")
            await mod.send(file=await attachment.to_file())

        await ctx.send("❌ Repeated invalid screenshot. Sent to moderators.")
        return

    suspicious = False

    if score < 0.50:
        suspicious = True

    if stars and stars > 200:
        suspicious = True

    if suspicious:
        mod = discord.utils.get(ctx.guild.channels, name="mod-review")

        if mod:
            await mod.send(f"⚠️ Suspicious screenshot from {ctx.author.mention}")
            await mod.send(file=await attachment.to_file())

        await ctx.send("❌ Screenshot looks edited. Sent to moderators.")
        return

    user_warnings[user_id] = 0

    await remove_old(ctx.author)

    role = discord.utils.get(ctx.guild.roles, name=rank)

    if role:
        await ctx.author.add_roles(role)

    embed = discord.Embed(title="MLBB Verified", color=discord.Color.green())

    embed.add_field(name="User", value=ctx.author.mention)
    embed.add_field(name="Player ID", value=player_id)
    embed.add_field(name="Server", value=server)
    embed.add_field(name="Rank", value=rank)

    if stars:
        embed.add_field(name="Stars", value=str(stars))

    await ctx.send(embed=embed)


bot.run(os.getenv("TOKEN"))
