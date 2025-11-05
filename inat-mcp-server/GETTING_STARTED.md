# Getting Started with the iNaturalist-Wildbook MCP Server

## ✅ Installation Complete!

The MCP server has been successfully installed with all dependencies in a virtual environment.

## What's Installed

```
inat-mcp-server/
├── venv/                    # Virtual environment with MCP SDK installed
├── server.py                # MCP server implementation
├── run_server.sh           # Launcher script (Unix/WSL/Mac)
└── [documentation files]
```

Dependencies installed in `venv/`:
- ✅ mcp (v1.20.0) - Model Context Protocol SDK
- ✅ Pillow (v12.0.0) - Image processing for GIF handling

## Next Steps

### Option 1: Using from WSL (Recommended for your setup)

Since you're running Python 3.12.3 in WSL with the virtual environment already set up:

**1. Configure Claude Code**

Add to `~/.config/claude-code/mcp_settings.json`:

```json
{
  "mcpServers": {
    "inat-wildbook": {
      "command": "/mnt/c/inat-download-recent-species-sightings/inat-mcp-server/run_server.sh"
    }
  }
}
```

**2. Restart Claude Code**

**3. Test it:**
```
Ask me: "Do you have access to inat-wildbook MCP tools?"
```

### Option 2: Using from Windows Python 3.10

If you want to use your Windows Python 3.10.14 installation instead:

**1. Install MCP in Windows:**
```powershell
cd C:\inat-download-recent-species-sightings\inat-mcp-server
py -3.10 -m pip install mcp Pillow
```

**2. Configure Claude Code for Windows:**

Add to `%APPDATA%\Claude\claude_code_config.json`:

```json
{
  "mcpServers": {
    "inat-wildbook": {
      "command": "py",
      "args": [
        "-3.10",
        "C:\\inat-download-recent-species-sightings\\inat-mcp-server\\server.py"
      ]
    }
  }
}
```

**3. Restart Claude Code**

## Testing the Installation

### Test 1: Verify Server Starts

From WSL:
```bash
cd /mnt/c/inat-download-recent-species-sightings/inat-mcp-server
./venv/bin/python server.py
```

You should see the server waiting for input (it's an stdio server). Press Ctrl+C to exit.

From Windows:
```powershell
cd C:\inat-download-recent-species-sightings\inat-mcp-server
py -3.10 server.py
```

### Test 2: Check MCP Tools with Claude

Ask Claude:
```
Do you have access to inat-wildbook MCP tools? If so, list them.
```

Expected response should mention three tools:
- download_observations
- get_recent_species_summary
- list_place_suggestions

### Test 3: Simple Query

```
How many jaguar observations are on iNaturalist from Brazil in the last 7 days?
```

Claude should use `get_recent_species_summary` and return statistics.

### Test 4: Full Download

```
Download those observations with HTML review
```

Claude should use `download_observations` and create:
- HTML review file in `data/`
- Photos in `data/photos/`

## Example Conversations

### Conversation 1: Exploratory Research
```
You: I'm interested in studying sea turtles in Costa Rica
Claude: Let me check recent observations...
        [Uses get_recent_species_summary]
Claude: There are 23 observations in the last 30 days. Would you like me to download them?
You: Yes, with HTML review
Claude: [Uses download_observations]
        ✅ Downloaded 23 observations
        📄 HTML review: data/inat_observations_review_sea-turtle_Costa-Rica_...html
```

### Conversation 2: Precise Geographic Filtering
```
You: What places match "Pantanal" on iNaturalist?
Claude: [Uses list_place_suggestions]
        Found: Pantanal, Mato Grosso, Brazil (ID: 1234)
You: Download jaguar observations from there in the last 60 days
Claude: [Uses download_observations with place="Pantanal"]
        ✅ Downloaded 47 observations...
```

### Conversation 3: Social Species Processing
```
You: Download bottlenose dolphin observations from Israel,
     split multi-photo observations since they're social
Claude: [Uses download_observations with social_split=true]
        ✅ Downloaded 23 observations (split into 67 encounters)
        Each photo becomes a separate encounter with shared sighting ID
```

## Troubleshooting

### Issue: "No such file or directory: mcp_settings.json"

**Solution:** The file doesn't exist yet. Create it:
```bash
mkdir -p ~/.config/claude-code
nano ~/.config/claude-code/mcp_settings.json
# Paste the JSON configuration
```

### Issue: Server doesn't appear in Claude

**Checklist:**
1. ✅ Is the path to `run_server.sh` absolute (not relative)?
2. ✅ Is `run_server.sh` executable? (`chmod +x run_server.sh`)
3. ✅ Did you restart Claude Code completely?
4. ✅ Check Claude Code logs for MCP errors

### Issue: "ModuleNotFoundError: No module named 'mcp'"

**Solution:** MCP is not installed in the active Python environment.

For WSL:
```bash
cd /mnt/c/inat-download-recent-species-sightings/inat-mcp-server
./venv/bin/pip install mcp Pillow
```

For Windows:
```powershell
py -3.10 -m pip install mcp Pillow
```

### Issue: "Could not resolve place 'X'"

**Solution:** Use the `list_place_suggestions` tool first:
```
What places match "X" on iNaturalist?
```
Then use the exact name returned.

### Issue: Photos not downloading

**Check:**
1. Internet connection
2. Disk space in output directory
3. iNaturalist API availability

## Configuration Options

### Change Output Directory

Ask Claude:
```
Download observations to ./my-research-data/ instead of ./data/
```

Claude will use the `output_dir` parameter.

### Adjust API Rate Limiting

For slower connections or to be more conservative:
```
Download observations with 2 second delays between API calls
```

Claude will set `rate_limit=2.0`.

### Use Specific Location IDs

For standardized geographic attribution:
```
Download observations and set location ID to "Mato Grosso"
```

Claude will set `location_id="Mato Grosso"` in the output CSV.

## Advanced Usage

### Multi-Species Comparison
```
Compare recent observation counts for jaguars, pumas, and ocelots in Brazil
```

Claude will:
1. Query each species with `get_recent_species_summary`
2. Aggregate results
3. Present comparison table

### Temporal Analysis
```
Which month had the most jaguar observations in the Pantanal over the last year?
```

Claude will:
1. Query each month separately
2. Compare counts
3. Identify peak period
4. Optionally download from peak month

### Quality-Focused Downloads
```
Download only research-grade observations with clear photos for photo-ID
```

Claude will apply appropriate filters and remind you to review in HTML interface.

## File Locations

### Configuration
- WSL/Linux: `~/.config/claude-code/mcp_settings.json`
- Windows: `%APPDATA%\Claude\claude_code_config.json`
- Mac: `~/Library/Application Support/Claude/claude_code_config.json`

### Server Files
- WSL: `/mnt/c/inat-download-recent-species-sightings/inat-mcp-server/`
- Windows: `C:\inat-download-recent-species-sightings\inat-mcp-server\`

### Output Files
- Default: `./data/` (relative to where you run Claude)
- HTML reviews: `data/inat_observations_review_*.html`
- Photos: `data/photos/`
- CSV exports: Downloaded from HTML review interface

## Support Resources

- **INSTALL.md** - Detailed installation steps
- **README.md** - Complete tool documentation
- **AGENTIC_WORKFLOW.md** - Architecture and workflow patterns
- **SUMMARY.md** - Quick reference

## What's Next?

1. ✅ Install dependencies (DONE)
2. ⬜ Configure Claude Code with MCP settings
3. ⬜ Restart Claude Code
4. ⬜ Test with: "Do you have inat-wildbook tools?"
5. ⬜ Try your first download!

---

**You're ready to start using natural language to download wildlife observations! 🎉**

Try this to get started:
```
How many observations are there for [your species] from [your location] this month?
```
