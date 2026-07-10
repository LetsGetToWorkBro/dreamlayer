# DreamLayer

> Glasses that remember for you.

DreamLayer is software for smart glasses that gives you a better memory and
a sharper ear. Wear them through a normal day and it quietly keeps what
matters — where you left things, who you met, what you promised, what was
said — and hands it back the moment you need it. When someone tells you
something that does not add up, it lets you know. Quietly. Just you.

It runs on your own devices, works without the internet, and goes fully deaf
and blind with one press of a button. Privacy is not a setting here; it is
how the thing is built.

![The whole product in ninety seconds — the real interface, over an illustrative world](assets/demo/catalog/master/preview.gif)

## Read this book two ways

**If you will wear it — start with the guide.** Plain language, no jargon,
built around what you actually see and say:

- [Start here](guide/start-here.md) — what it is and what it does for you
- [Setting up](guide/setup.md) — paired and working in minutes
- [A day with DreamLayer](guide/a-day-with-dreamlayer.md) — what it is like
- [Talking to it](guide/talking-to-oracle.md) — everything "Hey Oracle" can do
- [What just appeared on my glasses?](guide/cards.md) — the glance guide
- [The fact-checker](guide/truth.md) — what to trust, plainly
- [Your privacy](guide/privacy.md) — the contract, in plain words
- [The phone and the Mac](guide/apps.md) — the two companion apps
- [Questions people ask](guide/faq.md)

**If you are building on it — the second half is for you.** Under the hood:
the full architecture, every card and every setting, the exact thresholds
and timings of the truth stack, the complete API, and how to run and test
all four runtimes. Start at [Ecosystem architecture](architecture.md).

## Three honesty rules

This book holds itself to the product's own standard — its flagship feature
is a fact-checker, after all:

1. **The interface is always real.** Every HUD card, overlay, and app screen
   is produced by the product's own software — the actual renderer, the actual
   apps; nothing about the interface is a mockup. The dim, blurred environments
   now shown *behind* the glass are illustrative — the kind of moment a card
   appears in — exactly as on the website and simulator, where the interface is
   real and the world behind it is a stand-in.
2. **Built versus pending is always labeled.** DreamLayer is pre-hardware:
   the software is complete and tested (1,909 passing tests), and the places
   where physical hardware plugs in are called out honestly wherever they
   matter.
3. **Accuracy over hype.** Where the technical half states a number, it is
   the number in the source code.
