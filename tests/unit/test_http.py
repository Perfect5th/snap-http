"""Tests for `snap_http.http`, lower-level functions for interacting with Snapd via HTTP."""

import io
import json
import os
import socket
import threading

import pytest

from snap_http import http, types

FAKE_SNAPD_SOCKET = "/tmp/testsnapd.socket"


@pytest.fixture
def use_snapd_response():
    """A mock Snapd, listening on a socket like the real one does, in another thread."""

    if os.path.exists(FAKE_SNAPD_SOCKET):
        os.remove(FAKE_SNAPD_SOCKET)

    sock = socket.socket(family=socket.AF_UNIX)
    sock.bind(FAKE_SNAPD_SOCKET)

    thread = None

    def run_snapd_thread(code, response_body):
        json_body = json.dumps(response_body)
        encoded_length = len(json_body.encode())
        http_response = (
            f"HTTP/1.1 {code}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {encoded_length}\r\n\r\n{json_body}"
        )

        receiver = io.BytesIO()

        def run():
            sock.listen()
            conn, _ = sock.accept()
            receiver.write(conn.recv(1024))
            conn.sendall(http_response.encode())

        nonlocal thread
        thread = threading.Thread(target=run)
        thread.start()

        return receiver, thread

    yield run_snapd_thread

    if thread is not None:
        thread.join()

    sock.close()


def assert_request_contains(receiver, thread, expected):
    """Checks that the receiver, as written to by the mock snapd running in thread,
    contains the expected content.

    NOTE: intended to be called only at the end of test methods that use
    `use_snapd_response`.
    """
    thread.join()

    assert expected.encode() in receiver.getvalue()


def test_get(use_snapd_response, monkeypatch):
    """`http.get` returns a `types.SnapdResponse`."""
    monkeypatch.setattr(http, "SNAPD_SOCKET", FAKE_SNAPD_SOCKET)
    mock_response = {
        "type": "sync",
        "status_code": 200,
        "status": "OK",
        "result": [{"title": "placeholder1"}, {"title": "placeholder2"}],
    }
    use_snapd_response(200, mock_response)

    result = http.get("/snaps")

    assert result == types.SnapdResponse.from_http_response(mock_response)


def test_get_exception(use_snapd_response, monkeypatch):
    """`http.get` raises a `http.SnapdHttpException` for error response codes."""
    monkeypatch.setattr(http, "SNAPD_SOCKET", FAKE_SNAPD_SOCKET)
    mock_response = {
        "type": "sync",
        "status_code": 404,
        "status": "Not Found",
        "result": None,
    }
    use_snapd_response(404, mock_response)

    with pytest.raises(http.SnapdHttpException):
        _ = http.get("/snaps/placeholder")


def test_post(use_snapd_response, monkeypatch):
    """`http.post` returns a `types.SnapdResponse`."""
    monkeypatch.setattr(http, "SNAPD_SOCKET", FAKE_SNAPD_SOCKET)
    mock_response = {
        "type": "async",
        "status_code": 202,
        "status": "Accepted",
        "result": None,
        "change": "1",
    }
    receiver, thread = use_snapd_response(200, mock_response)

    result = http.post("/snaps/placeholder", {"action": "install"})

    assert result == types.SnapdResponse.from_http_response(mock_response)
    assert_request_contains(receiver, thread, '{"action": "install"}')


def test_post_exception(use_snapd_response, monkeypatch):
    """`http.post` raises a `http.SnapdHttpException` for error response codes."""
    monkeypatch.setattr(http, "SNAPD_SOCKET", FAKE_SNAPD_SOCKET)
    mock_response = {
        "type": "sync",
        "status_code": 404,
        "status": "Not Found",
        "result": None,
    }
    receiver, thread = use_snapd_response(404, mock_response)

    with pytest.raises(http.SnapdHttpException):
        _ = http.post("/snaps/placeholder", {"action": "install"})

    assert_request_contains(receiver, thread, '{"action": "install"}')
