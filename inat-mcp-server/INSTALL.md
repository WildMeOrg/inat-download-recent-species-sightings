# Quick Installation Guide

## Step 1: Create Virtual Environment and Install Dependencies

The MCP server uses a virtual environment to avoid conflicts with system packages.

```bash
cd inat-mcp-server

# Create virtual environment (already created)
python3 -m venv venv

# Install MCP SDK and Pillow
./venv/bin/pip install mcp Pillow
```

**Note:** If you're on Windows and using Python separately, you'll need to:
1. Install MCP in your Windows Python environment: `py -3.10 -m pip install mcp Pillow`
2. Use the Windows paths in the configuration below

## Step 2: Configure Claude Code (or Claude Desktop)

### For Claude Code (WSL/Linux/Mac):

1. Edit your MCP settings file:
   ```bash
   nano ~/.config/claude-code/mcp_settings.json
   ```

2. Add this configuration using the launcher script:
   ```json
   {
     "mcpServers": {
       "inat-wildbook": {
         "command": "/mnt/c/inat-download-recent-species-sightings/inat-mcp-server/run_server.sh"
       }
     }
   }
   ```

   **Alternative:** Call Python directly from the virtual environment:
   ```json
   {
     "mcpServers": {
       "inat-wildbook": {
         "command": "/mnt/c/inat-download-recent-species-sightings/inat-mcp-server/venv/bin/python",
         "args": [
           "/mnt/c/inat-download-recent-species-sightings/inat-mcp-server/server.py"
         ]
       }
     }
   }
   ```

3. Save and restart Claude Code

### For Claude Code (Windows):

1. Edit your MCP settings file:
   ```powershell
   notepad %APPDATA%\Claude\claude_code_config.json
   ```

2. Add this configuration (update the path to match your installation):
   ```json
   {
     "mcpServers": {
       "inat-wildbook": {
         "command": "python",
         "args": [
           "C:\\inat-download-recent-species-sightings\\inat-mcp-server\\server.py"
         ]
       }
     }
   }
   ```

3. Save and restart Claude Code

### For Claude Desktop:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

Same JSON format as above.

## Step 4: Verify Installation

Ask Claude:

```
Do you have access to the inat-wildbook MCP tools?
```

Claude should respond with information about the three available tools:
- `download_observations`
- `get_recent_species_summary`
- `list_place_suggestions`

## Step 5: Test with a Simple Query

```
How many jaguar observations are on iNaturalist from Brazil in the last 7 days?
```

Claude should use the `get_recent_species_summary` tool and return statistics.

## Troubleshooting

### "ModuleNotFoundError: No module named 'mcp'"

**Solution:** Install MCP SDK:
```bash
pip install mcp
```

### "Error: MCP SDK not installed"

**Solution:** Make sure you're using the same Python that has MCP installed:
```bash
# Check which Python has MCP
python3 -c "import mcp; print('MCP installed')"

# If that fails, try:
python -c "import mcp; print('MCP installed')"
```

Update your MCP configuration to use the correct Python command.

### Server not appearing in Claude

1. Check the config file path is correct
2. Check the path to `server.py` is absolute (not relative)
3. Restart Claude completely
4. Check Claude's logs for MCP errors

### "Could not resolve place"

Use the `list_place_suggestions` tool first:
```
What places match "Pantanal" on iNaturalist?
```

Then use the exact name returned in your download query.

## Testing the Server Directly

You can test the server standalone:

```bash
# This will start the server in stdio mode
python3 inat-mcp-server/server.py
```

If it starts without errors, the server is working. Press Ctrl+C to exit.

## Next Steps

Once installed, try these example queries with Claude:

1. **Quick check:**
   ```
   How many recent leafy seadragon observations are there from Australia?
   ```

2. **Simple download:**
   ```
   Download jaguar observations from Brazil in the last 30 days
   ```

3. **Complex research query:**
   ```
   Download bottlenose dolphin observations from Israel in the last week,
   split multi-photo observations since they're social, and set the
   location ID to "Israel"
   ```

4. **Geographic exploration:**
   ```
   What places are available for "Mato Grosso" on iNaturalist?
   Then download jaguar observations from there in the last 60 days.
   ```
