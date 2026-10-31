"""Public "Meet CUE" demo: isolated from tenant data, connectors and memory.

Runs as its own service (`uvicorn cue.demo.app:app`). It creates Google Meet meetings from Cue's
own Google account, launches the self-hosted face bot, and runs a voice loop (faster-whisper ->
Claude -> Kokoro) that talks to visitors through the bot. It never opens a tenant database.
"""
