import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import chat


def run(replies, inputs):
    """Run the conversation loop with scripted replies; return what was sent and what was shown."""
    sent, shown = [], []
    answers = iter(replies)
    lines = iter(inputs)

    def send(message, conversation_id, confirm):
        sent.append((message, conversation_id, confirm))
        reply = next(answers)
        if isinstance(reply, chat.ChatError):
            raise reply
        return reply

    def ask(prompt):
        try:
            return next(lines)
        except StopIteration:
            raise EOFError from None

    chat.converse(send, ask, shown.append)
    return sent, shown


def test_the_conversation_id_is_kept_between_messages():
    replies = [
        {"conversation_id": "c1", "answer": "One."},
        {"conversation_id": "c1", "answer": "Two."},
    ]

    sent, shown = run(replies, ["first", "second"])

    assert sent == [("first", None, False), ("second", "c1", False)]
    assert shown == ["agent> One.", "agent> Two."]


def test_yes_confirms_only_when_something_is_pending():
    replies = [
        {"conversation_id": "c1", "answer": "Hi."},
        {"conversation_id": "c1", "answer": "Log it?", "pending_action": {"tool": "log_visit"}},
        {"conversation_id": "c1", "answer": "Done."},
    ]

    sent, shown = run(replies, ["yes", "log a visit", "yes"])

    assert [confirm for _, _, confirm in sent] == [False, False, True]
    assert any("type yes" in line for line in shown)


def test_a_failed_message_is_shown_and_the_loop_goes_on():
    replies = [chat.ChatError("INVALID_INPUT: bad"), {"conversation_id": "c1", "answer": "Ok."}]

    sent, shown = run(replies, ["first", "second"])

    assert shown == ["error> INVALID_INPUT: bad", "agent> Ok."]


def test_exit_leaves_the_loop():
    sent, _ = run([], ["exit", "never sent"])

    assert sent == []


class Handler(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Handler.seen.append((self.path, self.headers["Authorization"], body))
        failing = body["message"] == "fail"
        payload = (
            {"error": {"code": "UNAUTHENTICATED", "message": "No."}}
            if failing
            else {"conversation_id": "c1", "answer": "Hello."}
        )
        self.send_response(401 if failing else 200)
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def agent_url():
    Handler.seen.clear()
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_post_chat_sends_the_token_and_the_body(agent_url):
    reply = chat.post_chat(agent_url, "tok", "Hi", "c1", True)

    assert reply["answer"] == "Hello."
    assert Handler.seen == [
        ("/chat", "Bearer tok", {"message": "Hi", "confirm": True, "conversation_id": "c1"})
    ]


def test_post_chat_turns_an_error_body_into_a_message(agent_url):
    with pytest.raises(chat.ChatError, match="UNAUTHENTICATED: No."):
        chat.post_chat(agent_url, "tok", "fail", None, False)


def test_post_chat_reports_an_unreachable_service():
    with pytest.raises(chat.ChatError, match="Could not reach"):
        chat.post_chat("http://127.0.0.1:1", "tok", "Hi", None, False)
