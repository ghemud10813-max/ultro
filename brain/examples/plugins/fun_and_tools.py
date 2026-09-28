"""Example Nixin plugin. Copy it into your plugins folder (Windows: %USERPROFILE%\\.nixin\\plugins,
or <data dir>/plugins) and restart Nixin — or press "Reload" on the dashboard's Automations tab.

    "sikka uchalo" / "toss a coin"    -> Heads / Tails
    "dice phenko" / "roll a dice"     -> 1..6
    "party mode"                      -> torch on + volume up + a YouTube playlist on the phone
    "pc pe notepad kholo aur likho <text>" -> opens Notepad on the PC and types the text
"""

import asyncio
import random

from nixin.features.plugins import command


@command(r"^(?:sikka|coin)\s+(?:uchalo|uchhalo|toss\s*karo|flip)$|^(?:toss|flip)\s+a\s+coin$", name="coin",
         description="Toss a coin")
async def coin(ctx):
    return random.choice(["Heads!", "Tails!"]) if ctx.lang == "english" else random.choice(["Heads aaya!", "Tails aaya!"])


@command(r"^(?:dice|pasa|paasa)\s+(?:phenko|pheko|feko|roll\s*karo)$|^roll\s+(?:a\s+)?dice$", name="dice",
         description="Roll a dice")
async def dice(ctx):
    n = random.randint(1, 6)
    return f"{n}!" if ctx.lang == "english" else f"{n} aaya!"


@command(r"^party mode(?:\s+on)?$", name="party", description="Torch, volume up and a party playlist", needs_phone=True)
async def party(ctx):
    # ctx.run() executes any Nixin command with the normal safety rules
    await ctx.run("volume full kar do")
    await ctx.run("youtube pe party songs chalao")
    for _ in range(3):  # blink the torch
        await ctx.phone("device.torch", {"on": True})
        await asyncio.sleep(0.4)
        await ctx.phone("device.torch", {"on": False})
        await asyncio.sleep(0.4)
    return "Party mode on! 🎉"


@command(r"^pc pe notepad kholo aur likho\s+(?P<text>.+)$", name="notepad", description="Write a note on the PC")
async def notepad(ctx):
    pc = ctx.pc
    if pc is None:
        return "PC control available nahi hai."
    await pc.open("notepad")
    await asyncio.sleep(1.5)
    await pc.type_text(ctx.groups["text"])
    return "Notepad mein likh diya."
