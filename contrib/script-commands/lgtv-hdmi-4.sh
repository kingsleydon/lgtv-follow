#!/bin/bash

# Raycast / Tinycast script command: switch the LG TV to HDMI 4.

# @raycast.schemaVersion 1
# @raycast.title TV HDMI 4
# @raycast.mode silent
# @raycast.packageName lgtv-follow
# @raycast.icon 📺
# @raycast.description Switch the LG TV to HDMI 4

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
lgtv-follow switch HDMI_4
