import os

from cue.connectors.calendly import CalendlyConnector
from cue.connectors.calendar import CalendarConnector
from cue.connectors.credentials import Credential
from cue.connectors.github import GitHubConnector
from cue.connectors.gmail import GmailConnector
from cue.connectors.linear import LinearConnector
from cue.connectors.recall import RecallConnector
from cue.connectors.slack import SlackConnector


def make_connector(provider: str, external_id: str, secret_ref: str | None):
    if provider == "github":
        return GitHubConnector()
    if not secret_ref:
        raise ValueError("Connector secret_ref is required")
    credential = Credential(secret_ref, provider)
    if provider == "gmail":
        return GmailConnector(credential)
    if provider == "calendar":
        return CalendarConnector(credential, external_id)
    if provider == "calendly":
        return CalendlyConnector(credential)
    if provider == "slack":
        return SlackConnector(credential)
    if provider == "linear":
        return LinearConnector(credential)
    if provider == "recall":
        return RecallConnector(credential.token(), os.environ["RECALL_REGION"])
    raise ValueError("Unsupported connector provider")
