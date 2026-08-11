#!/bin/sh
# Bark — one-line installer (universal shell launcher).
#
#   curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | fish
#   ...and any other POSIX shell (zsh, dash, ksh).
#
# fish and other non-POSIX shells cannot parse a bash script (e.g. POSIX
# parameter expansion like "${VAR:-default}" is a hard parse error in fish),
# so this tiny launcher always hands the real installer off to bash — which is
# a prerequisite Bark installs anyway. The launcher itself is written in the
# tiny subset of syntax shared by fish, sh, bash, zsh, and dash (a plain
# command with `&&`), so it parses and runs under all of them.
#
# All overrides pass straight through via the environment (no need to repeat
# them here):
#   BARK_REPO_URL      git URL to install from (default: warmbo/bark on GitHub)
#   BARK_BRANCH        branch to check out (default: main)
#   BARK_INSTALL_DIR   where to install (default: $HOME/bark)
#   BARK_SYSTEMD       auto | yes | no
#   BARK_INSTALL_HOST  dashboard bind address (default: 127.0.0.1)
#   BARK_INSTALL_PORT  dashboard port (default: 8090)
#   BARK_NO_START      set to 1 to install without launching anything
#   BARK_TMPDIR        writable temp dir (default: $HOME/.bark-tmp) — for hosts
#                      whose /tmp is not writable. Bark never relies on /tmp.
#
# Example:  BARK_BRANCH=dev curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install.sh | bash
#
# We stage install-main.sh in $HOME, not /tmp: /tmp is often a tiny or
# read-only tmpfs, and when it fills up curl dies with a cryptic
# "curl: (23) client returned ERROR on write" before the installer ever runs.
# $HOME is always writable for the installing user, so the bootstrap cannot
# fail that way. install-main.sh cleans this file up once it is running.
curl -fsSL https://raw.githubusercontent.com/warmbo/bark/main/install-main.sh -o "$HOME/bark-install-main.sh" && bash "$HOME/bark-install-main.sh"
