#!/bin/bash
exec > /home/cody/Projects/bark-avc/bark.log 2>&1
cd /home/cody/Projects/bark-avc
source .venv/bin/activate
set -a
source /home/cody/Projects/bark-avc/.env
set +a
exec python app.py
