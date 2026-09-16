# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from karapincho import power


@pytest.fixture
def caffeinate(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    launch = Mock(return_value=process)
    monkeypatch.setattr(power, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(power, "Popen", launch)
    return launch, process


@pytest.mark.parametrize("failure", [None, RuntimeError("generation failed"), KeyboardInterrupt()])
def test_keep_awake_releases_assertion_on_every_exit(caffeinate, failure):
    launch, process = caffeinate

    def generate():
        with power.keep_awake():
            launch.assert_called_once()
            command = launch.call_args.args[0]
            assert command == ["/usr/bin/caffeinate", "-i", "-w", str(power.os.getpid())]
            process.terminate.assert_not_called()
            if failure is not None:
                raise failure

    if failure is None:
        generate()
    else:
        with pytest.raises(type(failure)) as caught:
            generate()
        assert caught.value is failure
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=3)
    process.kill.assert_not_called()


def test_keep_awake_is_a_noop_outside_macos(caffeinate, monkeypatch):
    launch, _ = caffeinate
    monkeypatch.setattr(power, "sys", SimpleNamespace(platform="linux"))
    with power.keep_awake():
        pass
    launch.assert_not_called()


def test_unavailable_caffeinate_does_not_fail_generation(caffeinate, caplog):
    launch, process = caffeinate
    launch.side_effect = OSError("caffeinate unavailable")
    completed = False
    with power.keep_awake():
        completed = True
    assert completed
    assert caplog.records
    assert any(record.levelname == "WARNING" for record in caplog.records)
    process.terminate.assert_not_called()


def test_cleanup_kills_and_reaps_an_unresponsive_caffeinate(caffeinate):
    _, process = caffeinate
    process.wait.side_effect = [power.TimeoutExpired("caffeinate", 3), 0]
    with power.keep_awake():
        pass
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert process.wait.call_args.args == ()
    assert process.wait.call_args.kwargs == {}
