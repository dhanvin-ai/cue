"""Send Cue into a Google Meet through the self-hosted Attendee bot (local demo, no Firebase)."""

import argparse
from uuid import UUID

from cue.meetings import attendee, service


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("meeting_url")
    parser.add_argument("--uid", default="dev-local-user", help="member who owns the meeting")
    parser.add_argument("--attendee", action="append", default=[],
                        help="attendee email; repeat. Names on captions are matched to these.")
    parser.add_argument("--title")
    args = parser.parse_args()
    result = service.join_meeting(args.tenant_id, args.uid, args.meeting_url, args.attendee,
                                  title=args.title, bot=attendee.attendee_bot(args.tenant_id))
    print(f"meeting {result['meeting_id']}  bot {result['bot_id']}")
    print("Admit 'Cue' in Meet. Address it by name, e.g. \"Cue, what's open on GitHub?\"")


if __name__ == "__main__":
    main()
