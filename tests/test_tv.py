import pytest

from lgtv_follow.tv import power_on


@pytest.mark.parametrize(
    "payload, on",
    [
        ({"state": "Active"}, True),
        ({"state": "Screen Off"}, True),
        ({"state": "Screen Saver"}, True),
        ({"state": "Active Standby", "processing": "Request Active Standby"}, False),
        ({"state": "Power Off"}, False),
        ({"state": "Suspend"}, False),
        ({"state": "Unknown"}, None),  # a guess must never count as on
        ({"state": ""}, None),
        ({"state": ["Active"]}, None),  # unhashable: must not raise inside the library's callback
        ({}, None),  # e.g. an error response
        (None, None),
    ],
)
def test_power_payloads(payload, on):
    assert power_on(payload) == on
