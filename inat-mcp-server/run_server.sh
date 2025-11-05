#!/bin/bash
# MCP Server Launcher Script
# Activates virtual environment and runs the server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/venv/bin/python" "$SCRIPT_DIR/server.py"
