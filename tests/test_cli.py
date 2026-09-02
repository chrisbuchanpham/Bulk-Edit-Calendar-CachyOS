import pytest

from bulk_edit_calendar.cli import available_port, parser


def test_cli_defaults_to_loopback_and_dynamic_port(monkeypatch):
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def bind(self, address):
            assert address == ("127.0.0.1", 0)

        def getsockname(self):
            return ("127.0.0.1", 45678)

    monkeypatch.setattr("bulk_edit_calendar.cli.socket.socket", lambda *_args: FakeSocket())
    args = parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 0
    assert available_port(0) == 45678


def test_cli_refuses_remote_binding():
    with pytest.raises(SystemExit):
        parser().parse_args(["--host", "0.0.0.0"])
