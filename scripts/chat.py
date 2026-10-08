"""Chat with the agent service from the terminal. Demo client."""

import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from make_token import load_salespeople, make_token, read_secret

YES = {"y", "yes"}
EXIT = {"exit", "quit"}


class ChatError(Exception):
    pass


def post_chat(
    url: str, token: str, message: str, conversation_id: str | None, confirm: bool
) -> dict[str, Any]:
    body: dict[str, Any] = {"message": message, "confirm": confirm}
    if conversation_id:
        body["conversation_id"] = conversation_id
    request = urllib.request.Request(
        f"{url}/chat",
        json.dumps(body).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = json.loads(error.read())["error"]
        raise ChatError(f"{detail['code']}: {detail['message']}") from None
    except urllib.error.URLError as error:
        raise ChatError(f"Could not reach the agent service: {error.reason}") from None


def converse(
    send: Callable[[str, str | None, bool], dict[str, Any]],
    ask: Callable[[str], str],
    say: Callable[[str], None],
) -> None:
    conversation_id, pending = None, False
    while True:
        try:
            message = ask("you> ").strip()
        except EOFError:
            return
        if message.lower() in EXIT:
            return
        if not message:
            continue
        try:
            reply = send(message, conversation_id, pending and message.lower() in YES)
        except ChatError as error:
            say(f"error> {error}")
            continue
        conversation_id = reply["conversation_id"]
        pending = "pending_action" in reply
        say(f"agent> {reply['answer']}")
        if pending:
            say("       Waiting for your confirmation: type yes to go ahead.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as", dest="salesperson_id", required=True, choices=sorted(load_salespeople())
    )
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    token = make_token(args.salesperson_id, read_secret())
    print(f"Chatting as {args.salesperson_id}. Type exit to leave.")
    converse(
        lambda message, conversation_id, confirm: post_chat(
            args.url, token, message, conversation_id, confirm
        ),
        input,
        print,
    )


if __name__ == "__main__":
    main()
