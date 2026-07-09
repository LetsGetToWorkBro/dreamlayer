"""Hello, Lens — the smallest real DreamLayer plugin.

Registers one custom HUD card type. When the host renders a card with
type "HelloCard", this draws it: your text, centered, on the 256px glass.
That's a complete lens — everything bigger (TasteLens, the Beacon, Face
Synth) is this pattern with more ideas.
"""
from dreamlayer.plugins import make_plugin


def draw_hello_card(draw, card):
    """fn(draw, card): paint onto the round 256x256 canvas. `draw` is a
    Pillow ImageDraw in RGBA mode; keep it glanceable — one thought."""
    text = str(card.get("text", "hello, world"))[:24]
    draw.text((128, 118), text, fill=(44, 199, 154, 255), anchor="mm")
    draw.text((128, 148), "from your first lens", fill=(168, 184, 192, 160),
              anchor="mm")


def register(ctx):
    ctx.add_card_renderer("HelloCard", draw_hello_card)


def make():
    """The manifest's entry point: module:factory -> a plugin object."""
    return make_plugin("hello-lens", register, requires=("cards",))
