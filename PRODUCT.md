# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Plain HTML/CSS/JS served by FastAPI at `/ui`, no build step (user's choice).

## Users

A startup engineering or product lead. Cue sits in their team's Google Meet calls; afterwards (or during, on a second screen) they check what Cue heard and said, ask it follow-ups, and approve the actions it proposes.

## Product Purpose

Cue is an AI teammate for engineering teams. It listens in meetings, answers aloud from the team's own memory (GitHub, Gmail, Calendar, Calendly), and takes actions across tools, asking for approval first. Success: the team moves faster and trusts what Cue says and does.

## Positioning

Cue is a participant in the call, not a recorder: it is addressed by name, answers in voice with sources, and acts across connected tools under per-person permissions and tiered approvals.

## Capabilities and Constraints

- Voice in Meet via self-hosted Attendee; captions in, Edge TTS out.
- Memory query with citations; agent tasks with tool calls; tier 2+ tools need human approval.
- Meeting notes (summary, decisions, action items) written when a meeting ends.
- Open-source/free tooling only. Built for the Bolna AI Buildathon demo.

## Brand Commitments

- Name "Cue" with a sparkle; tagline "The AI teammate for engineering teams."
- Mascot: round white robot with a dark visor face, cyan eyes and a blue fin. Poses: idle/listening, thinking, talking, acting, waiting for approval. Source art: moodboard supplied by the user (crops in `cue/static/mascot/`).
- Personality: friendly, smart, lightweight, trustworthy, playful, modern. "A calm, capable presence in every meeting."
- Visual references the user made binding: light frosted app shell on a soft blue-lavender gradient, left icon rail, large readable transcript with avatars and timestamps, dark pill buttons, greeting home with suggestion cards and composer chips.

## Evidence on Hand

Real connected data: GitHub repo SaiAvinashPatoju/1mcp.in, Gmail and Calendar of cue.teammate@gmail.com. No customers, testimonials or metrics exist; do not invent them.

## Product Principles

1. Show the source: every answer Cue gives links back to where it came from.
2. Nothing external happens without a human yes.
3. Cue speaks only when spoken to.
4. Calm over clever: the console should feel like a capable colleague, not a control room.
