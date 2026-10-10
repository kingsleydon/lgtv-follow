#!/bin/bash

# Raycast / Tinycast script command: switch the LG TV to HDMI 1.

# @raycast.schemaVersion 1
# @raycast.title TV HDMI 1
# @raycast.mode silent
# @raycast.packageName lgtv-follow
# @raycast.icon 📺
# @raycast.description Switch the LG TV to HDMI 1

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
lgtv-follow switch HDMI_1
