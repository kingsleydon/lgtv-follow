import pytest

from lgtv_follow.actions import leave_audio_target

TV, SPK, PODS = "LG TV", "MacBook Pro Speakers", "AirPods"
ALL = [TV, SPK, PODS]


@pytest.mark.parametrize(
    "policy, current, previous, available, expected",
    [
        ("previous", TV, PODS, ALL, PODS),  # back to what was used before
        ("previous", TV, PODS, [TV, SPK], SPK),  # previous gone -> built-in
        ("previous", TV, None, ALL, SPK),  # nothing recorded -> built-in
        ("previous", TV, TV, ALL, SPK),  # never go "back" to the TV itself
        ("previous", PODS, SPK, ALL, None),  # user picked something else: leave it
        ("builtin", TV, PODS, ALL, SPK),
        ("AirPods", TV, None, ALL, PODS),  # a fixed device
        ("AirPods", TV, None, [TV, SPK], SPK),  # fixed device missing -> built-in
        ("none", TV, PODS, ALL, None),
    ],
)
def test_leave_audio_target(policy, current, previous, available, expected):
    assert leave_audio_target(policy, current, TV, previous, available, SPK) == expected
