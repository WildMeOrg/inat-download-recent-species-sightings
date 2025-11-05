#!/usr/bin/env python3
"""
MCP Server for iNaturalist-Wildbook Integration
Provides AI agents with tools to download and process wildlife observations
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Optional
import os

# Add parent directory to path to import the main downloader
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from mcp.server.models import InitializationOptions
    from mcp.server import NotificationOptions, Server
    from mcp.server.stdio import stdio_server
    from mcp import types
except ImportError:
    print("Error: MCP SDK not installed. Install with: pip install mcp", file=sys.stderr)
    sys.exit(1)

# Import the downloader (filename has dashes so we need to use importlib)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "inat_downloader",
    Path(__file__).parent.parent / "inat-download-new-species-sightings.py"
)
inat_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inat_module)
iNaturalistDownloader = inat_module.iNaturalistDownloader

# Create MCP server instance
server = Server("inat-wildbook-integration")

@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    """List available tools for the MCP server."""
    return [
        types.Tool(
            name="download_observations",
            description="""Download wildlife observations from iNaturalist with optional filters.

This tool queries iNaturalist API for observations of specified species, downloads photos,
and prepares data for Wildbook import. Automatically excludes captive animals.

Key features:
- Multiple species support
- Geographic filtering (place names like 'California', 'Brazil', 'Mato Grosso')
- Date range filtering (days back from today)
- Generates HTML review page for manual curation
- Supports social species splitting (one photo per encounter)
- Auto-filters non-organism evidence (tracks, scat, molts)
- Auto-filters skulls/bones from museum collections

Returns: Summary of downloaded observations and output file paths.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "species": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of species names (common or scientific names). Examples: ['Panthera onca', 'jaguar'], ['leafy seadragon']"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days back to search for observations (default: 30)",
                        "default": 30
                    },
                    "place": {
                        "type": "string",
                        "description": "Optional place filter (e.g., 'California', 'Brazil', 'Mato Grosso do Sul', 'United States')"
                    },
                    "location_id": {
                        "type": "string",
                        "description": "Optional location ID to add to Encounter.locationID column (e.g., 'Mato Grosso', 'California')"
                    },
                    "submitter_id": {
                        "type": "string",
                        "description": "Optional submitter ID to add to Encounter.submitterID column"
                    },
                    "output_dir": {
                        "type": "string",
                        "description": "Output directory path (default: './data')",
                        "default": "./data"
                    },
                    "html_review": {
                        "type": "boolean",
                        "description": "Generate interactive HTML review page instead of CSV (default: true)",
                        "default": True
                    },
                    "social_split": {
                        "type": "boolean",
                        "description": "Split multi-photo observations into separate encounters for social species (default: false)",
                        "default": False
                    },
                    "rate_limit": {
                        "type": "number",
                        "description": "Seconds to wait between API calls (default: 1.0)",
                        "default": 1.0
                    }
                },
                "required": ["species"]
            }
        ),
        types.Tool(
            name="get_recent_species_summary",
            description="""Get a summary of recent observations for a species without downloading photos.

Quickly checks iNaturalist for observation counts and recent activity. Useful for determining
if it's worth doing a full download.

Returns: Summary statistics including observation count, date range, top locations, and quality grades.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "species": {
                        "type": "string",
                        "description": "Species name (common or scientific). Example: 'Panthera onca' or 'jaguar'"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days back to check (default: 30)",
                        "default": 30
                    },
                    "place": {
                        "type": "string",
                        "description": "Optional place filter (e.g., 'California', 'Brazil')"
                    }
                },
                "required": ["species"]
            }
        ),
        types.Tool(
            name="list_place_suggestions",
            description="""Search for place names on iNaturalist to help with geographic filtering.

Finds matching place names and returns their details. Useful for determining exact place names
before downloading observations.

Returns: List of matching places with IDs, types (country/state/county), and display names.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "place_query": {
                        "type": "string",
                        "description": "Place name to search for (e.g., 'Pantanal', 'California', 'Mato Grosso')"
                    }
                },
                "required": ["place_query"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any] | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    """Handle tool execution requests."""

    if name == "download_observations":
        return await download_observations_tool(arguments or {})
    elif name == "get_recent_species_summary":
        return await get_species_summary_tool(arguments or {})
    elif name == "list_place_suggestions":
        return await list_places_tool(arguments or {})
    else:
        raise ValueError(f"Unknown tool: {name}")

async def download_observations_tool(args: dict[str, Any]) -> list[types.TextContent]:
    """Execute the download_observations tool."""

    # Extract arguments
    species_list = args.get("species", [])
    days_back = args.get("days_back", 30)
    place = args.get("place")
    location_id = args.get("location_id")
    submitter_id = args.get("submitter_id")
    output_dir = args.get("output_dir", "./data")
    html_review = args.get("html_review", True)
    social_split = args.get("social_split", False)
    rate_limit = args.get("rate_limit", 1.0)

    # Validate
    if not species_list:
        return [types.TextContent(
            type="text",
            text="Error: At least one species must be specified"
        )]

    try:
        # Create downloader
        downloader = iNaturalistDownloader(
            output_dir=output_dir,
            days_back=days_back,
            species_list=species_list,
            rate_limit=rate_limit,
            html_review=html_review,
            place=place,
            location_id=location_id,
            submitter_id=submitter_id,
            social_split=social_split
        )

        # Resolve place if specified
        if place:
            downloader.place_id = downloader.resolve_place(place)
            if downloader.place_id is None:
                return [types.TextContent(
                    type="text",
                    text=f"Error: Could not resolve place '{place}'. Try using list_place_suggestions first."
                )]

        # Process each species
        all_observations_data = []
        species_results = []

        for species_name in species_list:
            # Get taxon ID
            taxon_id = downloader.search_species(species_name)

            if taxon_id is None:
                species_results.append(f"⚠️  Species '{species_name}': Not found")
                continue

            # Get observations
            observations = downloader.get_observations(taxon_id)

            if not observations:
                species_results.append(f"ℹ️  Species '{species_name}': No observations found")
                continue

            # Process and download
            processed_data = downloader.process_observations(observations, species_name)
            all_observations_data.extend(processed_data)

            species_results.append(
                f"✓ Species '{species_name}': {len(observations)} observations downloaded"
            )

        # Generate output
        if all_observations_data:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Build filename components
            species_part = "_".join([s.replace(" ", "-") for s in species_list[:2]])
            place_part = f"_{place.replace(' ', '-')}" if place else ""

            output_files = []

            if html_review:
                html_filename = f"inat_observations_review_{species_part}{place_part}_{timestamp}.html"
                downloader.write_html(all_observations_data, html_filename)
                output_files.append(f"HTML review: {output_dir}/{html_filename}")
            else:
                csv_filename = f"inat_observations_{species_part}{place_part}_{timestamp}.csv"
                downloader.write_csv(all_observations_data, csv_filename)
                output_files.append(f"CSV export: {output_dir}/{csv_filename}")

            output_files.append(f"Photos directory: {downloader.photos_dir}")

            # Build result summary
            result_text = "✅ **Download Complete**\n\n"
            result_text += "**Summary:**\n"
            result_text += "\n".join(species_results)
            result_text += f"\n\n**Total observations processed:** {len(all_observations_data)}\n"
            result_text += f"**Date range:** Last {days_back} days\n"
            if place:
                result_text += f"**Place filter:** {place}\n"
            result_text += "\n**Output files:**\n"
            result_text += "\n".join(f"- {f}" for f in output_files)

            if html_review:
                result_text += "\n\n**Next steps:**\n"
                result_text += f"1. Open the HTML file in a web browser\n"
                result_text += f"2. Review observations and deselect any you don't want to import\n"
                result_text += f"3. Use the 'CSV Export' tab to download the final CSV for Wildbook import"

            return [types.TextContent(type="text", text=result_text)]
        else:
            return [types.TextContent(
                type="text",
                text="No observations found for any of the specified species.\n\n" +
                     "\n".join(species_results)
            )]

    except Exception as e:
        import traceback
        error_msg = f"Error during download: {str(e)}\n\n"
        error_msg += "Traceback:\n" + traceback.format_exc()
        return [types.TextContent(type="text", text=error_msg)]

async def get_species_summary_tool(args: dict[str, Any]) -> list[types.TextContent]:
    """Get summary statistics for a species without downloading."""

    species = args.get("species")
    days_back = args.get("days_back", 30)
    place = args.get("place")

    if not species:
        return [types.TextContent(
            type="text",
            text="Error: species parameter is required"
        )]

    try:
        # Create temporary downloader just for the API call
        downloader = iNaturalistDownloader(
            output_dir="./temp",
            days_back=days_back,
            species_list=[species],
            rate_limit=1.0,
            html_review=False,
            place=place
        )

        # Resolve place if specified
        if place:
            downloader.place_id = downloader.resolve_place(place)

        # Get taxon ID
        taxon_id = downloader.search_species(species)

        if taxon_id is None:
            return [types.TextContent(
                type="text",
                text=f"Species '{species}' not found on iNaturalist"
            )]

        # Get observations (without downloading photos)
        observations = downloader.get_observations(taxon_id)

        if not observations:
            result = f"**Species:** {species}\n"
            result += f"**Time period:** Last {days_back} days\n"
            if place:
                result += f"**Place:** {place}\n"
            result += f"\n**Result:** No observations found"
            return [types.TextContent(type="text", text=result)]

        # Calculate statistics
        quality_counts = {}
        locations = {}
        has_photos = 0

        for obs in observations:
            quality = obs.get('quality_grade', 'unknown')
            quality_counts[quality] = quality_counts.get(quality, 0) + 1

            if obs.get('photos'):
                has_photos += 1

            place_guess = obs.get('place_guess', 'Unknown')
            locations[place_guess] = locations.get(place_guess, 0) + 1

        # Build summary
        result = f"**Species:** {species}\n"
        result += f"**Time period:** Last {days_back} days\n"
        if place:
            result += f"**Place filter:** {place}\n"
        result += f"\n**Total observations:** {len(observations)}\n"
        result += f"**Observations with photos:** {has_photos}\n"

        result += f"\n**Quality grades:**\n"
        for quality, count in sorted(quality_counts.items(), key=lambda x: x[1], reverse=True):
            result += f"- {quality}: {count}\n"

        result += f"\n**Top locations:**\n"
        top_locations = sorted(locations.items(), key=lambda x: x[1], reverse=True)[:5]
        for location, count in top_locations:
            result += f"- {location}: {count}\n"

        return [types.TextContent(type="text", text=result)]

    except Exception as e:
        import traceback
        error_msg = f"Error getting species summary: {str(e)}\n\n"
        error_msg += "Traceback:\n" + traceback.format_exc()
        return [types.TextContent(type="text", text=error_msg)]

async def list_places_tool(args: dict[str, Any]) -> list[types.TextContent]:
    """Search for places on iNaturalist."""

    place_query = args.get("place_query")

    if not place_query:
        return [types.TextContent(
            type="text",
            text="Error: place_query parameter is required"
        )]

    try:
        import urllib.request
        import urllib.parse
        import json

        params = urllib.parse.urlencode({'q': place_query})
        url = f"https://api.inaturalist.org/v1/places/autocomplete?{params}"

        with urllib.request.urlopen(url) as response:
            data = json.loads(response.read().decode())

        places = data.get('results', [])

        if not places:
            return [types.TextContent(
                type="text",
                text=f"No places found matching '{place_query}'"
            )]

        result = f"**Places matching '{place_query}':**\n\n"

        for place in places[:10]:  # Limit to top 10
            place_id = place.get('id')
            name = place.get('name')
            display_name = place.get('display_name', name)
            place_type = place.get('place_type', 'unknown')

            result += f"**{display_name}**\n"
            result += f"- Type: {place_type}\n"
            result += f"- ID: {place_id}\n"
            result += f"- Use in filter: `{name}`\n\n"

        return [types.TextContent(type="text", text=result)]

    except Exception as e:
        import traceback
        error_msg = f"Error searching places: {str(e)}\n\n"
        error_msg += "Traceback:\n" + traceback.format_exc()
        return [types.TextContent(type="text", text=error_msg)]

async def main():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="inat-wildbook-integration",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                )
            )
        )

if __name__ == "__main__":
    asyncio.run(main())
