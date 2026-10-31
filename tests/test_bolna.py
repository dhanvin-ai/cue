import json
from uuid import UUID, uuid4

from cue.meetings import bolna, service, store
from cue.runtime.executor import ToolRegistry
from tests.test_meetings import AgentGateway, FakeBot, attendees, memory, tenants  # noqa: F401


def conversation(*turns: str) -> list[dict]:
    messages = [{"role": "system", "content": "You are Cue."},
                {"role": "assistant", "content": service.DISCLOSURE}]
    for text in turns:
        messages.append({"role": "user", "content": text})
    return messages


def bolna_meeting(tenants):
    result = service.join_meeting(
        tenants.a, "alice", "https://meet.google.com/abc-defg-hij", attendees(),
        title="Release review", bot=bolna.BolnaMeetingBot(),
    )
    assert result["bot_id"].startswith(bolna.BOT_PREFIX)
    return UUID(result["meeting_id"])


def test_tenant_key_lookup(monkeypatch):
    tenant = uuid4()
    monkeypatch.setenv("BOLNA_LLM_KEYS", f"{uuid4()}=other, {tenant}=secret-key")
    assert bolna.tenant_for_key("secret-key") == tenant
    assert bolna.tenant_for_key("secret") is None
    monkeypatch.delenv("BOLNA_LLM_KEYS")
    assert bolna.tenant_for_key("secret-key") is None


def test_sse_is_openai_stream_and_ends_with_done():
    lines = [line for line in bolna.sse(iter(["Hello", " there"]), "cue") if line.strip()]
    assert lines[-1] == "data: [DONE]\n\n"
    chunks = [json.loads(line.removeprefix("data: ")) for line in lines[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "Hello there"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert bolna.completion(["Hi", " team"], "cue")["choices"][0]["message"]["content"] == "Hi team"


def test_agent_config_points_llm_at_cue():
    config = bolna.agent_config(name="Cue", base_url="https://cue.example/bolna/v1",
                                model="cue-t", voice={"provider": "elevenlabs"})
    llm = config["agent_config"]["tasks"][0]["tools_config"]["llm_agent"]["llm_config"]
    assert llm["provider"] == "custom" and llm["base_url"] == "https://cue.example/bolna/v1"
    assert config["agent_config"]["agent_welcome_message"] == service.DISCLOSURE


def test_unaddressed_turn_is_silent_but_transcribed(tenants):
    meeting_id = bolna_meeting(tenants)
    spoken = list(bolna.respond(tenants.a, conversation("Let's move the launch to Friday."),
                                gateway=AgentGateway("unused"), registry=ToolRegistry(),
                                memory=memory))
    assert spoken == []
    with store.tenant_connection(tenants.a) as database:
        rows = store.segments(database, tenants.a, meeting_id)
    assert [(row["speaker_id"], row["text"]) for row in rows] == [
        (bolna.CALLER, "Let's move the launch to Friday.")]


def test_addressed_turn_speaks_filler_then_answer_and_records_both(tenants):
    meeting_id = bolna_meeting(tenants)
    messages = conversation("Let's move the launch to Friday.",
                            "Cue, what's blocking the release?")
    spoken = list(bolna.respond(tenants.a, messages, gateway=AgentGateway("PR 412 awaits review."),
                                registry=ToolRegistry(), memory=memory))
    assert spoken[0] == bolna.FILLER
    assert "".join(spoken[1:]).strip() == "PR 412 awaits review."
    # Bolna retries resend the same conversation; the transcript must not duplicate.
    list(bolna.respond(tenants.a, messages[:-1], gateway=AgentGateway("unused"),
                       registry=ToolRegistry(), memory=memory))
    with store.tenant_connection(tenants.a) as database:
        rows = store.segments(database, tenants.a, meeting_id)
        reply = database.execute(
            "SELECT status FROM meeting_replies WHERE tenant_id = %s AND meeting_id = %s",
            (tenants.a, meeting_id)).fetchone()
    speakers = [row["speaker_id"] for row in rows]
    assert speakers.count(bolna.CALLER) == 2 and speakers.count(bolna.CUE_SPEAKER) == 1
    assert reply[0] == "completed"


def test_turn_without_live_bolna_meeting_is_silent(tenants):
    service.join_meeting(tenants.a, "alice", "https://meet.google.com/abc-defg-hij", attendees(),
                         bot=FakeBot())
    assert list(bolna.respond(tenants.a, conversation("Cue, are you there?"),
                              gateway=AgentGateway("yes"), registry=ToolRegistry(),
                              memory=memory)) == []
