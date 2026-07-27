#!/bin/bash
exec > /home/cody/Projects/bark/bark.log 2>&1
cd /home/cody/Projects/bark
source .venv/bin/activate
set -a
source /home/cody/Projects/bark/.env
set +a
exec python app.py
