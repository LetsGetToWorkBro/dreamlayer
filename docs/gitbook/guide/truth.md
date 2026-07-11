# The fact-checker

DreamLayer's signature feature is called **Veritas**: while people talk, it
listens for claims and quietly tells you when one does not hold up. This
chapter explains what it does in plain terms — and, just as important, what
it deliberately does not do.

It is **off by default**. You turn it on with one switch in the phone's
Settings ("Live fact-checker").

![The self-contradiction catch, live](../assets/demo/catalog/features/veritas/preview.webp)

## What you see

When Veritas has something to say, one card appears for seven seconds. The
color tells you everything at a glance:

![A red card: they said different before](../assets/cards/fact_check.webp)

- **Red — "They said different before."** The strongest signal. This exact
  person previously said something that contradicts what they just said, and
  the card quotes their earlier words back. This works entirely on your own
  devices, even with no internet at all.
- **Amber — "Check this."** The claim was checked against your brain (your
  Mac's knowledge, or the cloud if you allow it) and it did not hold up.
- **Green — "Verified."** The claim checked out. Green cards are rare on
  purpose — it only bothers confirming when it is very sure.
- **Grey — "Unverified."** It heard a checkable claim but could not settle
  it either way. An honest shrug, not a verdict.

## Why it stays quiet most of the time

A fact-checker that pipes up constantly would be worse than none. Veritas is
built to be picky:

- It only checks **real claims** — numbers, dates, facts. Questions,
  opinions, and hedged statements ("I think...", "maybe...") are ignored.
- It speaks about any one person **at most once every 45 seconds**.
- It needs to be **confident** before it flags anything.
- It holds its tongue entirely during Focus mode, and when privacy is on it
  hears nothing at all.

So when a card does appear, it means something.

## Reading the room, not just the words

Two companion features deepen the picture, both also off until you enable
them:

**The delivery read** looks at *how* something was said — pace, phrasing,
strain — always compared against that same person's normal baseline. It
refuses to judge anyone it has not spent real time with: strangers are
explicitly out of bounds, because everyone's nervous tics look "suspicious"
until you know their normal.

**The combined read** then puts content and delivery together into one
honest headline on the card:

> *"Doesn't add up — and it didn't sound like it, either."*
> *"The claim is off, but they seem to mean it."* — a false claim delivered
> sincerely reads as an honest mistake, not a lie.
> *"Checks out — but the delivery was uneasy."*

That distinction — wrong versus lying — is the whole point of having both.

## What to trust, plainly

- **Trust the red cards most.** "They said different before" comes with the
  receipt quoted on the card.
- **Treat amber as a prompt, not a verdict.** It means "worth checking",
  and the card shows the basis it used.
- **The delivery read is a hint, never an accusation.** It is one signal,
  weighted carefully, and it is honest about its own confidence.
- DreamLayer never announces anything to the room. Every card is for your
  eyes only, and whether to act on it is entirely yours.
