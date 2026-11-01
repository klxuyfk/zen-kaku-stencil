#!/bin/sh
# Build fonts/ttf from the UFO sources with the Google Fonts tool chain.
#   pip install -r requirements.txt
#   sh sources/build.sh
set -e
cd "$(dirname "$0")/.."
gftools builder sources/config.yaml
