"""Operator registers Cue as a Bolna custom LLM and creates the tenant's meeting-line agent.

Afterwards, buy or attach a phone number in Bolna, set it as this agent's inbound number, and add
`TENANT_UUID=KEY` to BOLNA_LLM_KEYS and the number to BOLNA_PHONE_NUMBER on the API.
"""

import argparse
import json
import os
import secrets

from cue.meetings import bolna


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id")
    parser.add_argument("public_base_url", help="Public Cue API URL, e.g. https://abc.ngrok.app")
    parser.add_argument("--name", default="Cue")
    parser.add_argument("--voice", default='{"provider": "elevenlabs", "provider_config": '
                        '{"voice": "Angelica", "voice_id": "IkSv4tkouLJ6kYsQA7XD", '
                        '"model": "eleven_turbo_v2_5"}}',
                        help="Bolna synthesizer JSON (provider plus provider_config)")
    parser.add_argument("--telephony", default="plivo", choices=("plivo", "twilio", "exotel"))
    args = parser.parse_args()
    key = secrets.token_urlsafe(32)
    base_url = args.public_base_url.rstrip("/") + "/bolna/v1"
    client = bolna.BolnaClient(os.environ["BOLNA_API_KEY"])
    model_name = f"cue-{args.tenant_id}"
    client.add_custom_model(model_name, base_url, key)
    agent = client.create_agent(bolna.agent_config(
        name=args.name, base_url=base_url, model=model_name,
        voice=json.loads(args.voice), telephony=args.telephony,
    ))
    print(json.dumps({"agent_id": agent.get("agent_id"),
                      "BOLNA_LLM_KEYS": f"{args.tenant_id}={key}"}, indent=2))


if __name__ == "__main__":
    main()
