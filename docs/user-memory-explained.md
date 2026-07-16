# How the Bot Remembers People — A Plain-English Guide

*Audience: channel admins, moderators, and curious users. No coding required.*

## What is this?

The bot can build a small, private **memory of the regulars** in your channel — little notes
like *"loves 80s action movies,"* *"is learning guitar,"* or *"always rooting for the underdog."*
It uses these notes to reply in a way that feels like it actually knows the people it's talking to, even after a restart or days later.

This guide explains **what it remembers, how it decides, and the safety rails** around it. There's
a separate, technical spec for developers; this is the friendly version.

## What it remembers (and what it doesn't)

**It tries to remember:** durable, harmless personal tidbits people volunteer in chat —
preferences, hobbies, habits, things they used to do, how they describe themselves.

**It deliberately does *not* remember:**
- Emails, phone numbers, home addresses, or long number strings.
- Web links.
- Anything the safety filter flags as sensitive (this runs **twice** — before and after the bot
  writes a note).

If someone says *"forget me,"* an admin can wipe every note about that user with one command.
Memory is also **off by default** — a channel operator has to turn it on.

## How a note gets made

Instead of dumb keyword matching, an **AI reads a short slice of recent chat** and writes a clean,
one-line summary of any fact worth keeping. Crucially, this AI runs on its **own separate
connection** — a smaller, cheaper model of your choosing. It is completely walled off from the
model that writes the bot's chat replies: different endpoint, different key, no sharing. Memory
work never slows down or interferes with the bot talking, and vice-versa.

Before the AI is even consulted, cheap filters throw away obvious non-facts and anything unsafe, so
the AI only looks at messages that might actually matter. This keeps costs low.

## The four things the bot scores

For every candidate note, the system produces a few numbers. Here's what they mean in plain terms:

| Score | Question it answers | Why it matters |
|-------|--------------------|----------------|
| **Confidence** | "Am I sure *who* this is about?" | Chat is chaotic — many people talking at once. The AI looks back over the last several lines to be sure it's crediting the right person. Low-confidence guesses are thrown away, not saved. |
| **Sentiment** | "Is this a positive or negative thing?" | Stored as a tag for later (e.g. so the bot could lean on the cheerful facts). Right now it's just recorded, not acted on. |
| **Novelty** | "Do we already know this?" | Decides whether a note is brand-new, a close cousin of something we know, or an exact repeat. Prevents the memory from filling up with duplicates. |
| **Importance** | "How often does this keep coming up?" | Every time someone repeats a fact, its importance ticks up. Things people mention a lot become *more* important and show up sooner when the bot reaches for a memory. |

### Why "importance" is the clever bit

If User42 mentions three times over two weeks that they love a certain band, the bot doesn't store
three copies. It stores **one** note and quietly bumps its *importance* each time. That repeated
mention is a strong signal that this is a real part of who they are — so that note rises to the top
when the bot decides what to remember about them. Memory ends up reflecting what people talk about
**most**, not just what they said **last**.

## What happens when someone says something

1. A cheap safety + relevance filter looks at the message. Junk and anything sensitive is dropped.
2. Messages worth keeping are collected for a moment (batched per person) to keep things efficient.
3. The **separate memory AI** reads that slice and proposes clean, one-line facts with a
   *confidence* and *sentiment* score.
4. Low-confidence or unsafe notes are discarded.
5. The system checks **novelty**:
   - Already known? → don't duplicate; just bump **importance**.
   - Related but new? → save it, and nudge the related note's importance up.
   - Brand new? → save it fresh.
6. Later, when the bot replies, it pulls the most relevant and most important notes about the
   person it's talking to, and weaves them in.

All of this happens **in the background** — it never makes the bot slower to respond.

## For admins — the controls you have

Everything is tunable in the config file, and the whole feature is opt-in. The knobs that matter
most in everyday terms:

- **On/off:** memory is disabled until you enable it.
- **Which memory model to use:** its own endpoint and key — point it at a cheap local model.
- **How sure is "sure enough":** the confidence cutoff for saving a note.
- **How chatty the memory is:** how many facts it may keep per person, and how aggressively it
  merges near-duplicates.
- **How much repetition boosts a fact:** how strongly "importance" pushes well-known facts to the
  front.
- **Forget commands:** wipe one user's notes, or inspect what's stored.

## The short version

- The bot builds a **small, safe, per-person memory** from what people volunteer in chat.
- A **separate, cheap AI** writes the notes — fully isolated from the chat-reply model.
- It scores each note for **who it's about (confidence)**, **positive/negative (sentiment)**, and
  **is-this-new (novelty)**, and tracks **how often it comes up (importance)**.
- It **never** stores contact info or sensitive data, checks safety twice, is **off by default**,
  and supports **"forget me."**
- The result: a bot that remembers the regulars the way a friendly host would — the things you
  bring up often, not random one-offs.
