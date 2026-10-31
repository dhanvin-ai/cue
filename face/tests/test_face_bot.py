"""face_bot.py tests. The join flow runs against tests/fake_meet.html (same accessible names as
Meet, loopback WebRTC) so admission, devices, events, stop and shutdown are exercised locally.
A real Google Meet join is a manual test; see face/README.md."""

import asyncio
import json
import re

import face_bot
import pytest
from websockets.asyncio.client import connect


def test_init_script_bundles_index_scripts_in_order():
    scripts = face_bot.face_scripts()
    assert [p.name for p in scripts] == ["core.js", "speech.js", "mascot.js", "overlay.js", "app.js", "mock.js", "boot.js"]
    init = face_bot.build_init_script({"captions": False, "mock": True})
    assert "window.top !== window" in init
    assert json.dumps(face_bot.MEET_HOST_PATTERN) in init
    assert '"captions": false' in init and '"mock": true' in init and '"emitBinding": "__cueFaceEmit"' in init
    assert "data:font/woff2;base64," in init
    positions = [init.index(p.read_text()[:80]) for p in scripts]
    assert positions == sorted(positions)


@pytest.mark.parametrize(
    "text,status",
    [
        ("Asking to be let in...", "waiting"),
        ("Please wait until a meeting host brings you into the call", "waiting"),
        ("Someone in the call denied your request to join", "denied"),
        ("You can't join this video call", "denied"),
        ("No one responded to your request to join the call", "denied"),
        ("You've been removed from the meeting", "denied"),
        ("You left the meeting\nReturn to home screen", "ended"),
        ("Check your meeting code", "invalid"),
        ("Ready to join?\nJoin now", None),
    ],
)
def test_classify_meet_text(text, status):
    assert face_bot.classify(text) == status


def test_cli_validates_urls():
    with pytest.raises(SystemExit):
        face_bot.parse_args(["join", "meet.google.com/abc"])
    with pytest.raises(SystemExit):
        face_bot.parse_args(["join", "https://meet.google.com/abc", "--ws", "http://x"])
    args = face_bot.parse_args(["join", "https://meet.google.com/abc-defg-hij", "--ws", "ws://127.0.0.1:8765/ws", "--guest"])
    assert args.guest and args.ws_url.startswith("ws://") and args.name == "Cue"


def options(server, query="", **extra):
    return face_bot.BotOptions(
        meeting_url=f"{server['http']}/tests/fake_meet.html{query}",
        ws_url=server["ws"],
        guest=True,
        browser="chromium",
        headless=True,
        join_timeout=20,
        admission_timeout=20,
        host_pattern=r"^127\.0\.0\.1$",
        **extra,
    )


async def wait_for(predicate, timeout=20.0, step=0.1):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        value = await predicate()
        if value:
            return value
        await asyncio.sleep(step)
    raise AssertionError("condition not met in time")


def test_bot_joins_shows_mascot_handles_events_and_leaves(server):
    async def scenario():
        bot = face_bot.FaceBot(options(server))
        statuses = []
        async with connect(server["ws"], max_size=face_bot.MAX_FRAME) as backend:
            async def collect():
                async for frame in backend:
                    msg = json.loads(frame)
                    if msg.get("type") == "bot_status":
                        statuses.append(msg)
                    elif msg.get("type") in ("speak_started", "speak_ended", "state_changed"):
                        statuses.append(msg)

            collector = asyncio.create_task(collect())
            run = asyncio.create_task(bot.run())
            try:
                return await exercise(bot, backend, statuses, run, collector)
            finally:
                bot.request_stop("test teardown")
                await asyncio.wait_for(asyncio.shield(run), 30)
                collector.cancel()

    async def exercise(bot, backend, statuses, run, collector):
        await wait_for(lambda: _async(any(s.get("status") == "video_full_resolution" for s in statuses)), timeout=40)
        live = next(s for s in statuses if s.get("status") == "video_live")
        full = next(s for s in statuses if s.get("status") == "video_full_resolution")
        assert live["seconds_after_admission"] < 15 and full["seconds_after_admission"] < 15
        assert (full["frame_width"], full["frame_height"]) == (1280, 720)

        page = bot.page
        meet = await page.evaluate("() => ({name: fakeMeet.name, camOn: fakeMeet.camOn, micOn: fakeMeet.micOn})")
        assert meet["name"] == "Cue" and meet["camOn"] and meet["micOn"]
        await asyncio.sleep(3)
        stats = await page.evaluate("() => CueFace.outboundStats()")
        assert stats["frameWidth"] == 1280 and stats["framesPerSecond"] >= 20, stats
        received = await wait_for(lambda: page.evaluate("() => receivedVideo()"))
        assert (received["width"], received["height"]) == (1280, 720) and received["darkSamples"] > 50

        # Contract events from the "backend" reach the face inside the meeting tab.
        await backend.send(json.dumps({"type": "state", "state": "thinking"}))
        await wait_for(lambda: page.evaluate("() => CueFace.app.snapshot().state === 'thinking'"))
        await backend.send(json.dumps({"type": "action", "id": "x", "status": "needs_approval", "title": "Post"}))
        await wait_for(lambda: page.evaluate("() => CueFace.app.snapshot().cards.length === 1"))

        # Speech reaches the meeting's received audio, then `stop` silences it.
        wav = await page.evaluate("() => CueFace.synthPhrase('one two three four five six seven eight nine ten eleven twelve', 5)")
        await backend.send(json.dumps({"type": "speak", "id": "s1", "format": "wav", "audio": wav, "text": "counting"}))
        await wait_for(lambda: page.evaluate("() => fakeMeet.remoteLevel > 0.01"), timeout=10)
        await backend.send(json.dumps({"type": "stop"}))
        await wait_for(lambda: page.evaluate("() => !CueFace.app.speech.speaking && CueFace.app.speech.analyserRms() < 0.001"), timeout=2)
        await wait_for(lambda: _async(any(s.get("type") == "speak_ended" and s.get("reason") == "stopped" for s in statuses)), timeout=5)

        bot.request_stop("test finished")
        code = await asyncio.wait_for(asyncio.shield(run), 20)
        return code, statuses, meet

    code, statuses, _ = asyncio.run(scenario())
    assert code == face_bot.EXIT_OK
    names = [s.get("status") for s in statuses if s.get("type") == "bot_status"]
    assert names.index("joining") < names.index("waiting_admission") < names.index("in_call") < names.index("video_live")
    assert names[-1] == "left"


def test_bot_reports_denied_admission(server):
    async def scenario():
        bot = face_bot.FaceBot(options(server, "?deny=1"))
        return await asyncio.wait_for(bot.run(), 40)

    assert asyncio.run(scenario()) == face_bot.EXIT_NOT_ADMITTED


def test_bot_mock_mode_without_backend(server):
    async def scenario():
        opts = options(server, "?signed_in=1")
        opts.ws_url = None
        opts.mock = True
        bot = face_bot.FaceBot(opts)
        run = asyncio.create_task(bot.run())
        try:
            await wait_for(lambda: _async(bot.status == "in_call"), timeout=30)
            await wait_for(lambda: bot.page.evaluate("() => CueFace.app.snapshot().state === 'thinking'"), timeout=20)
            await wait_for(lambda: bot.page.evaluate("() => fakeMeet.remoteLevel > 0.01"), timeout=15)
        finally:
            bot.request_stop("done")
        return await asyncio.wait_for(run, 20)

    assert asyncio.run(scenario()) == face_bot.EXIT_OK


async def _async(value):
    return value


def test_bot_profile_and_secrets_are_gitignored():
    from pathlib import Path

    ignore = (Path(face_bot.ROOT) / "face" / ".gitignore").read_text()
    for pattern in (".profile/", "*.session", ".env"):
        assert re.search(re.escape(pattern), ignore), pattern


def test_ctrl_c_to_the_process_group_still_leaves_cleanly(server, tmp_path):
    """A terminal Ctrl-C reaches the bot, Playwright's driver and Chrome at once. The browser must
    survive long enough for the bot to stop speech and click Leave call."""
    import os
    import signal
    import subprocess
    import sys
    import time

    log = tmp_path / "bot.log"
    with log.open("w") as out:
        bot = subprocess.Popen(
            [sys.executable, str(face_bot.ROOT / "scripts" / "face_bot.py"), "join", f"{server['http']}/tests/fake_meet.html",
             "--guest", "--browser", "chromium", "--headless", "--host-pattern", r"^127\.0\.0\.1$", "--mock"],
            stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
        )
        deadline = time.time() + 40
        while time.time() < deadline and "Mascot is live" not in log.read_text():
            time.sleep(0.2)
        time.sleep(1)
        os.killpg(bot.pid, signal.SIGINT)
        code = bot.wait(30)
    text = log.read_text()
    assert "Left the call" in text, text
    assert code == face_bot.EXIT_INTERRUPTED


def test_verbose_flag_before_or_after_subcommand():
    assert face_bot.parse_args(["join", "https://meet.google.com/x", "-v"]).verbose
    assert face_bot.parse_args(["-v", "join", "https://meet.google.com/x"]).verbose
    assert not face_bot.parse_args(["join", "https://meet.google.com/x"]).verbose


def test_signed_in_chrome_keeps_the_real_keychain(tmp_path):
    import os

    assert "--use-mock-keychain" in face_bot.ignored_default_args("chrome", guest=False)
    assert face_bot.ignored_default_args(None, guest=False) == ["--enable-automation"]
    assert face_bot.ignored_default_args("chrome", guest=True) == ["--enable-automation"]
    assert face_bot.profile_in_use(tmp_path) is None
    os.symlink(f"host-{os.getpid()}", tmp_path / "SingletonLock")
    assert face_bot.profile_in_use(tmp_path) == os.getpid()
