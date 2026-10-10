#!/bin/bash

# Raycast / Tinycast script command: Mac input <-> previous input.

# @raycast.schemaVersion 1
# @raycast.title TV Toggle Mac
# @raycast.mode silent
# @raycast.packageName lgtv-follow
# @raycast.icon 📺
# @raycast.description Switch the LG TV to the Mac (HDMI 4), or back to the previous input
# @raycast.argument1 { "type": "text", "placeholder": "Mac input", "optional": true }

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
lgtv-follow toggle "${1:-HDMI_4}"
