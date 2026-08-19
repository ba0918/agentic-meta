#!/usr/bin/env bash
# Emit a minimal trace-log conforming stream.
set -eu
printf 'TRC|boot|starting\n'
printf 'TRC|work|processing item\n'
printf 'TRC|end|done\n'
