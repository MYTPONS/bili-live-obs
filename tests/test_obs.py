import base64
import hashlib

from bls import obs


class FakeClient:
    def __init__(self):
        self.responses = {}
        self.calls = []
        self.bytes_sequence = None
        self._seq = 0

    def call(self, request_type, data=None):
        payload = dict(data or {})
        self.calls.append((request_type, payload))
        if request_type == "GetStreamStatus" and self.bytes_sequence is not None:
            seq = self.bytes_sequence[min(self._seq, len(self.bytes_sequence) - 1)]
            self._seq += 1
            return {"outputActive": True, "outputBytes": seq}
        return dict(self.responses.get(request_type, {}))


def test_auth_string_matches_protocol():
    password, salt, challenge = "supersecretpassword", "saltvalue", "challengevalue"
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    expected = base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()
    assert obs.auth_string(password, salt, challenge) == expected


def test_sync_stream_starts_when_idle():
    client = FakeClient()
    client.responses = {"GetStreamStatus": {"outputActive": False}}
    assert obs.sync_stream(client, "rtmp://x/", "?k=1") == "started"
    assert (
        "SetStreamServiceSettings",
        {
            "streamServiceType": "rtmp_custom",
            "streamServiceSettings": {"server": "rtmp://x/", "key": "?k=1"},
        },
    ) in client.calls
    assert ("StartStream", {}) in client.calls


def test_sync_stream_restarts_when_key_differs():
    client = FakeClient()
    client.responses = {
        "GetStreamStatus": {"outputActive": True},
        "GetStreamServiceSettings": {
            "streamServiceType": "rtmp_custom",
            "streamServiceSettings": {"server": "rtmp://old/", "key": "?k=old"},
        },
    }
    assert obs.sync_stream(client, "rtmp://new/", "?k=new") == "restarted"
    assert ("StopStream", {}) in client.calls
    assert client.calls.index(("StopStream", {})) < client.calls.index(("StartStream", {}))


def test_sync_stream_unchanged_when_identical():
    client = FakeClient()
    client.responses = {
        "GetStreamStatus": {"outputActive": True},
        "GetStreamServiceSettings": {
            "streamServiceType": "rtmp_custom",
            "streamServiceSettings": {"server": "rtmp://s/", "key": "?k=1"},
        },
    }
    assert obs.sync_stream(client, "rtmp://s/", "?k=1") == "unchanged"
    assert ("StopStream", {}) not in client.calls


def test_wait_streaming_false_when_bytes_stall():
    client = FakeClient()
    client.responses = {"GetStreamStatus": {"outputActive": True, "outputBytes": 0}}
    client.bytes_sequence = [0]
    assert obs.wait_streaming(client, timeout=0.3) is False


def test_wait_streaming_true_after_two_growths():
    client = FakeClient()
    client.responses = {"GetStreamStatus": {"outputActive": True, "outputBytes": 0}}
    client.bytes_sequence = [0, 100, 200]
    assert obs.wait_streaming(client, timeout=2) is True


def test_read_ws_password_missing_file(tmp_path):
    assert obs.read_ws_password(tmp_path) == (False, "")


def test_read_ws_password_reads_config(tmp_path):
    plugin = tmp_path / "plugin_config" / "obs-websocket"
    plugin.mkdir(parents=True)
    (plugin / "config.json").write_text(
        '{"server_enabled": true, "server_password": "pw123"}', encoding="utf-8"
    )
    assert obs.read_ws_password(tmp_path) == (True, "pw123")


def test_wait_streaming_tolerates_delayed_output_start():
    """OBS 的 StartStream 是异步的，连接建立前 outputActive 还是 False，不能据此判失败。"""

    class Delayed:
        def __init__(self):
            self.calls = 0

        def call(self, request_type, data=None):
            self.calls += 1
            if self.calls <= 3:
                return {"outputActive": False, "outputBytes": 0}
            return {"outputActive": True, "outputBytes": 1000 * self.calls}

    assert obs.wait_streaming(Delayed(), timeout=5, start_grace=2) is True


def test_wait_streaming_gives_up_when_output_stays_stopped():
    class Stopped:
        def call(self, request_type, data=None):
            return {"outputActive": False, "outputBytes": 0}

    assert obs.wait_streaming(Stopped(), timeout=3, start_grace=0.2) is False
