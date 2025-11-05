# iNaturalist-Wildbook MCP Server

An MCP (Model Context Protocol) server that enables AI assistants like Claude to download and process wildlife observations from iNaturalist for import into Wildbook mark-recapture databases.

## Features

This MCP server provides AI agents with three powerful tools:

### 1. `download_observations`
Download wildlife observations from iNaturalist with intelligent filtering:
- Multi-species support
- Geographic filtering (countries, states, counties)
- Date range filtering
- Automatic exclusion of captive/cultivated animals
- Auto-filtering of non-organism evidence (tracks, scat, molts)
- Auto-filtering of skulls/bones from museum collections
- HTML review interface for manual curation
- Social species mode (split multi-photo observations)
- Animated GIF frame extraction

### 2. `get_recent_species_summary`
Quick statistics about recent observations without downloading photos:
- Observation counts
- Quality grade distribution
- Top locations
- Photo availability

### 3. `list_place_suggestions`
Search for place names on iNaturalist to help with geographic filtering:
- Autocomplete place search
- Returns place types (country, state, county, etc.)
- Provides exact names for filtering

## Installation

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Step 1: Install MCP SDK

```bash
pip install mcp
```

### Step 2: Install Pillow (for GIF handling)

```bash
pip install Pillow
```

### Step 3: Make the server executable

```bash
chmod +x inat-mcp-server/server.py
```

## Configuration

### For Claude Desktop

Add this to your Claude Desktop configuration file:

**On macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**On Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "inat-wildbook": {
      "command": "python3",
      "args": [
        "/absolute/path/to/inat-download-recent-species-sightings/inat-mcp-server/server.py"
      ]
    }
  }
}
```

**Important:** Replace `/absolute/path/to/` with the actual full path to your project directory.

### For Claude Code

Add this to your Claude Code MCP settings (`~/.config/claude-code/mcp_settings.json`):

```json
{
  "mcpServers": {
    "inat-wildbook": {
      "command": "python3",
      "args": [
        "/absolute/path/to/inat-download-recent-species-sightings/inat-mcp-server/server.py"
      ]
    }
  }
}
```

## Usage Examples

Once configured, you can use natural language with Claude:

### Example 1: Download jaguar observations from Brazil

```
Download jaguar observations from Mato Grosso, Brazil from the last 30 days
```

Claude will use the `download_observations` tool with:
- species: ["Panthera onca"]
- days_back: 30
- place: "Mato Grosso"
- html_review: true (generates interactive review page)

### Example 2: Check recent activity before downloading

```
How many leafy seadragon observations have been posted to iNaturalist
in California in the last week?
```

Claude will use `get_recent_species_summary` to quickly check without downloading photos.

### Example 3: Find the right place name

```
What places are available for "Pantanal" on iNaturalist?
```

Claude will use `list_place_suggestions` to find matching places.

### Example 4: Multi-species download with social splitting

```
Download recent observations of bottlenose dolphins from Israel,
split multi-photo observations since they're a social species
```

Claude will use `download_observations` with:
- species: ["Tursiops truncatus"]
- place: "Israel"
- social_split: true

### Example 5: Complex research query

```
I'm studying jaguars in the Pantanal. Download observations from
Mato Grosso and Mato Grosso do Sul from the last 60 days,
set location ID to the state name, and generate an HTML review
```

Claude will intelligently:
1. Determine the species (Panthera onca)
2. Download from both states
3. Use location_id parameter
4. Generate HTML review for manual curation

## Tool Details

### download_observations

**Parameters:**
- `species` (required): Array of species names (common or scientific)
- `days_back` (default: 30): Number of days to look back
- `place`: Place name filter (e.g., "California", "Brazil")
- `location_id`: Value for Encounter.locationID column
- `submitter_id`: Value for Encounter.submitterID column
- `output_dir` (default: "./data"): Output directory
- `html_review` (default: true): Generate HTML review page
- `social_split` (default: false): Split multi-photo observations
- `rate_limit` (default: 1.0): Seconds between API calls

**Returns:**
- Summary of downloaded observations
- Output file paths
- Next steps for review/import

### get_recent_species_summary

**Parameters:**
- `species` (required): Species name (common or scientific)
- `days_back` (default: 30): Number of days to look back
- `place`: Place name filter

**Returns:**
- Observation count
- Quality grade breakdown
- Top locations
- Photo availability statistics

### list_place_suggestions

**Parameters:**
- `place_query` (required): Place name to search for

**Returns:**
- List of matching places with:
  - Display name
  - Place type (country, state, county, etc.)
  - Place ID
  - Exact name for filtering

## Output Files

### HTML Review Mode (default)

The tool generates an interactive HTML page with:
- Photo previews for each observation
- Filtering controls (select/deselect observations)
- Quality indicators (research grade, needs ID, casual)
- License information
- Merge functionality for social species
- CSV export tab for Wildbook import

**Workflow:**
1. Open HTML file in web browser
2. Review observations (auto-filtered for quality)
3. Deselect unwanted observations
4. Click "CSV Export" tab
5. Download CSV for Wildbook import

### CSV Export Mode

Direct CSV output in Wildbook bulk import format with columns:
- `Encounter.mediaAsset0...N` - Photo filenames
- `Encounter.genus`, `Encounter.specificEpithet` - Taxonomy
- `Encounter.decimalLatitude`, `Encounter.decimalLongitude` - GPS
- `Encounter.locationID` - Location identifier
- `Encounter.state` - Approval state (always "unapproved")
- `Sighting.sightingID` - For grouping social observations
- And many more...

### Photo Downloads

All photos are saved to `{output_dir}/photos/` with naming:
- `{observation_id}_{photo_number}.jpg`
- For animated GIFs: `{observation_id}_{photo_number}_frame{N}.jpg`

## Automated Workflows

The MCP server enables powerful automated workflows:

### Scheduled Monitoring

```python
# Example: Daily check for new observations
"Check for new jaguar observations in Brazil and notify me if
there are more than 10 research-grade observations"
```

### Data Quality Pipeline

```python
"Download jaguar observations from last week, filter out
observations without coordinates or with 'needs_id' quality,
and prepare for Wildbook import"
```

### Cross-Platform Integration

```python
"Download observations for all species in my Wildbook project
from the last month, deduplicate against existing database
entries, and generate import CSV"
```

## Troubleshooting

### Server won't start

**Issue:** `ModuleNotFoundError: No module named 'mcp'`

**Solution:** Install MCP SDK: `pip install mcp`

---

**Issue:** `Warning: PIL/Pillow not installed. Cannot convert animated GIFs.`

**Solution:** Install Pillow: `pip install Pillow`

### Place filter not working

**Issue:** "Could not resolve place 'Pantanal'"

**Solution:** Use `list_place_suggestions` first to find exact place names

### API rate limiting

**Issue:** Getting rate-limited by iNaturalist API

**Solution:** Increase `rate_limit` parameter (e.g., 2.0 seconds between calls)

## Architecture

```
┌─────────────────┐
│  Claude/AI      │
│  Assistant      │
└────────┬────────┘
         │ MCP Protocol
         │
┌────────▼────────┐
│  MCP Server     │
│  (server.py)    │
└────────┬────────┘
         │ Python imports
         │
┌────────▼───────────────────────┐
│  iNaturalistDownloader         │
│  (inat-download-new-species-   │
│   sightings.py)                │
└────────┬───────────────────────┘
         │ HTTPS
         │
┌────────▼────────┐
│  iNaturalist    │
│  API            │
└─────────────────┘
```

## Development

### Testing the server directly

```bash
# Run server in stdio mode
python3 inat-mcp-server/server.py
```

### Adding new tools

1. Add tool definition to `handle_list_tools()`
2. Implement handler function
3. Add case to `handle_call_tool()`
4. Update README documentation

## License

This MCP server wraps the iNaturalist downloader tool and inherits its usage policies. Observations downloaded from iNaturalist retain their original licenses as specified by contributors.

## Contributing

Issues and pull requests welcome! Key areas for contribution:
- Additional filtering options
- Integration with other biodiversity platforms (GBIF, eBird, etc.)
- Computer vision quality assessment (CLIP-based filtering)
- Duplicate detection across platforms
- Enhanced geographic mapping

## Related Projects

- **Wildbook**: Wildlife individual identification platform
- **iNaturalist**: Citizen science biodiversity observation platform
- **MCP (Model Context Protocol)**: Anthropic's protocol for AI tool integration
