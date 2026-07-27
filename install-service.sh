#!/bin/bash
# Installs Bark as a systemd user service using the protected .env file.
set -e
mkdir -p ~/.config/systemd/user/
install -m 600 /home/cody/Projects/bark/bark.service ~/.config/systemd/user/bark.service
systemctl --user daemon-reload
systemctl --user enable bark
systemctl --user restart bark
echo "Bark systemd service installed and started."
echo "Dashboard: https://bark.warx.org"
echo "Status: systemctl --user status bark"
echo "Logs: journalctl --user -u bark -f"
