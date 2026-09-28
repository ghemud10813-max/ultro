# Plugins

A plugin is a Python file in `<data dir>/plugins/` (default data dir: `~/.nixin`, see `nixin doctor`) or in any folder
listed in `[plugins] dirs`. Nixin loads every `*.py` there at start (files starting with `_` are skipped); the
dashboard's **Automations → Plugins → Reload** reloads them without restarting. A broken plugin is reported on the
dashboard and never stops Nixin.

```python
from nixin.features.plugins import command

@command(r"^(?:sikka|coin) uchalo$", name="coin", description="Toss a coin")
async def coin(ctx):
    import random
    return random.choice(["Heads!", "Tails!"])
```

- The pattern is a regex matched (case-insensitive, `re.search`) against the **cleaned** command: lowercase, wake word
  and fillers ("please", "yaar"…) removed, Devanagari transliterated. Use `^…$` to match whole commands.
- Plugins are checked **before** the built-in router, so a plugin can override a built-in phrase.
- Return a string (Nixin speaks/shows it) or `None`.
- `needs_phone=True` makes Nixin answer "phone connected nahi hai" instead of calling you when offline.

## `ctx` (PluginContext)

| | |
|---|---|
| `ctx.text`, `ctx.lang` | the command and reply language (`hinglish`/`english`) |
| `ctx.match`, `ctx.groups` | the regex match / named groups |
| `await ctx.phone(method, params)` | call any phone method from `shared/protocol/methods.json` (phone-side safety rules apply) |
| `await ctx.run("torch on karo")` | run any Nixin command (router → classifier → agent). Messages/calls started this way **ask for confirmation** |
| `await ctx.say(text)` / `await ctx.notify(title, text)` | speak / notify on PC + phone |
| `ctx.pc` | the PC controller (`lock`, `volume`, `open`, `type_text`, `screenshot`, `clipboard_get/set`, `notify`…) |
| `ctx.http` | a shared `httpx.AsyncClient` |
| `ctx.remember(fact)` | add to Nixin's memory |

A complete example lives in [`brain/examples/plugins/fun_and_tools.py`](../brain/examples/plugins/fun_and_tools.py).

**Security:** plugins run inside Nixin on your PC with your user's permissions — only install plugins you wrote or read.
