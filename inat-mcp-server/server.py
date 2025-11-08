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

# Import YouTube tools
from youtube_tools import YouTubeSearcher, format_video_results, generate_html_report

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
        ),
        types.Tool(
            name="search_youtube_videos",
            description="""Search YouTube for recent wildlife videos by species name.

Searches YouTube for videos about any species (uses scientific or common names).
Works with any species - mammals, birds, fish, reptiles, invertebrates, plants, etc.

Features:
- Search by scientific name (e.g., "Panthera leo") or common name (e.g., "lion")
- Filter by upload date (last N days)
- Optional keyword filtering (include/exclude specific terms)
- Returns video metadata: title, description, channel, URL, thumbnail

Requires: YOUTUBE_API_KEY environment variable set.

Returns: List of matching videos with metadata.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "species": {
                        "type": "string",
                        "description": "Species name (scientific or common). Examples: 'Rhincodon typus', 'whale shark', 'Panthera onca', 'jaguar'"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days back to search (default: 1)",
                        "default": 1
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of videos to return (default: 25, max: 50)",
                        "default": 25
                    },
                    "additional_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional keywords to include (e.g., ['wild', 'safari', 'encounter'])"
                    },
                    "exclude_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional keywords to exclude (e.g., ['cartoon', 'toy', 'game', 'drawing'])"
                    }
                },
                "required": ["species"]
            }
        ),
        types.Tool(
            name="search_youtube_multilanguage",
            description="""Search YouTube for wildlife videos using multiple language variants of a species name.

Searches YouTube with common names in different languages to find more videos.
Automatically deduplicates results. Works with any species.

Features:
- Multi-language search (provide species names in different languages)
- Automatic deduplication by video ID
- Returns which language matched each video
- Optional keyword filtering

Requires: YOUTUBE_API_KEY environment variable set.

Example usage:
  species_names: {
    "en": "whale shark",
    "es": "tiburón ballena",
    "fr": "requin-baleine",
    "scientific": "Rhincodon typus"
  }

Returns: Deduplicated list of videos across all languages.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "species_names": {
                        "type": "object",
                        "description": "Dictionary of language code to species name. Keys can be language codes (en, es, fr, de, zh) or 'scientific'. Example: {'en': 'lion', 'es': 'león', 'scientific': 'Panthera leo'}"
                    },
                    "days_back": {
                        "type": "integer",
                        "description": "Number of days back to search (default: 1)",
                        "default": 1
                    },
                    "max_results_per_language": {
                        "type": "integer",
                        "description": "Maximum results per language variant (default: 10)",
                        "default": 10
                    },
                    "additional_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional keywords to include in all searches"
                    },
                    "exclude_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional keywords to exclude from all searches (e.g., ['cartoon', 'toy'])"
                    }
                },
                "required": ["species_names"]
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
    elif name == "search_youtube_videos":
        return await search_youtube_tool(arguments or {})
    elif name == "search_youtube_multilanguage":
        return await search_youtube_multilanguage_tool(arguments or {})
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

async def search_youtube_tool(args: dict[str, Any]) -> list[types.TextContent]:
    """Search YouTube for wildlife videos."""

    species = args.get("species")
    days_back = args.get("days_back", 1)
    max_results = args.get("max_results", 25)
    additional_keywords = args.get("additional_keywords")
    exclude_keywords = args.get("exclude_keywords")

    if not species:
        return [types.TextContent(
            type="text",
            text="Error: species parameter is required"
        )]

    try:
        # Check for API key
        api_key = os.environ.get('YOUTUBE_API_KEY')
        if not api_key:
            return [types.TextContent(
                type="text",
                text="Error: YOUTUBE_API_KEY environment variable not set.\n\n"
                     "To use YouTube tools, you need a YouTube Data API v3 key:\n"
                     "1. Go to https://console.cloud.google.com/apis/credentials\n"
                     "2. Create a project (if needed)\n"
                     "3. Enable YouTube Data API v3\n"
                     "4. Create an API key\n"
                     "5. Set environment variable: export YOUTUBE_API_KEY='your-key'"
            )]

        # Create searcher and search
        searcher = YouTubeSearcher(api_key=api_key)

        videos = searcher.search_videos(
            species_query=species,
            days_back=days_back,
            max_results=max_results,
            additional_keywords=additional_keywords,
            exclude_keywords=exclude_keywords
        )

        if not videos:
            result = f"**Species:** {species}\n"
            result += f"**Time period:** Last {days_back} days\n"
            result += f"\n**Result:** No videos found"
            return [types.TextContent(type="text", text=result)]

        # Format results
        result = f"**YouTube Search Results**\n\n"
        result += f"**Species:** {species}\n"
        result += f"**Time period:** Last {days_back} days\n"
        if additional_keywords:
            result += f"**Additional keywords:** {', '.join(additional_keywords)}\n"
        if exclude_keywords:
            result += f"**Excluded keywords:** {', '.join(exclude_keywords)}\n"
        result += f"\n"

        result += format_video_results(videos, include_descriptions=True)

        # Generate HTML report
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        species_safe = species.replace(" ", "-").replace("/", "-")
        html_filename = f"youtube_videos_{species_safe}_{days_back}days_{timestamp}.html"
        html_path = f"./data/youtube_reports/{html_filename}"

        search_params = {
            'species': species,
            'days_back': days_back
        }
        if additional_keywords:
            search_params['additional_keywords'] = additional_keywords
        if exclude_keywords:
            search_params['exclude_keywords'] = exclude_keywords

        html_file = generate_html_report(videos, html_path, search_params)

        result += f"\n\n**HTML Report:** {html_file}\n"
        result += f"Open this file in a web browser to view embedded videos and export selected results."

        return [types.TextContent(type="text", text=result)]

    except Exception as e:
        import traceback
        error_msg = f"Error searching YouTube: {str(e)}\n\n"
        error_msg += "Traceback:\n" + traceback.format_exc()
        return [types.TextContent(type="text", text=error_msg)]

async def search_youtube_multilanguage_tool(args: dict[str, Any]) -> list[types.TextContent]:
    """Search YouTube with multiple language variants."""

    species_names = args.get("species_names")
    days_back = args.get("days_back", 1)
    max_results_per_language = args.get("max_results_per_language", 10)
    additional_keywords = args.get("additional_keywords")
    exclude_keywords = args.get("exclude_keywords")

    if not species_names:
        return [types.TextContent(
            type="text",
            text="Error: species_names parameter is required"
        )]

    if not isinstance(species_names, dict):
        return [types.TextContent(
            type="text",
            text="Error: species_names must be a dictionary (e.g., {'en': 'whale shark', 'es': 'tiburón ballena'})"
        )]

    try:
        # Check for API key
        api_key = os.environ.get('YOUTUBE_API_KEY')
        if not api_key:
            return [types.TextContent(
                type="text",
                text="Error: YOUTUBE_API_KEY environment variable not set.\n\n"
                     "To use YouTube tools, you need a YouTube Data API v3 key:\n"
                     "1. Go to https://console.cloud.google.com/apis/credentials\n"
                     "2. Create a project (if needed)\n"
                     "3. Enable YouTube Data API v3\n"
                     "4. Create an API key\n"
                     "5. Set environment variable: export YOUTUBE_API_KEY='your-key'"
            )]

        # Create searcher and search
        searcher = YouTubeSearcher(api_key=api_key)

        videos = searcher.search_multi_language(
            species_names=species_names,
            days_back=days_back,
            max_results_per_language=max_results_per_language,
            additional_keywords=additional_keywords,
            exclude_keywords=exclude_keywords
        )

        if not videos:
            result = f"**Multi-Language YouTube Search**\n\n"
            result += f"**Languages searched:** {', '.join(species_names.keys())}\n"
            result += f"**Time period:** Last {days_back} days\n"
            result += f"\n**Result:** No videos found"
            return [types.TextContent(type="text", text=result)]

        # Format results
        result = f"**Multi-Language YouTube Search Results**\n\n"
        result += f"**Species names searched:**\n"
        for lang, name in species_names.items():
            result += f"  - {lang}: {name}\n"
        result += f"**Time period:** Last {days_back} days\n"
        if additional_keywords:
            result += f"**Additional keywords:** {', '.join(additional_keywords)}\n"
        if exclude_keywords:
            result += f"**Excluded keywords:** {', '.join(exclude_keywords)}\n"
        result += f"\n"

        result += format_video_results(videos, include_descriptions=True)

        # Add language match statistics
        language_counts = {}
        for video in videos:
            lang = video.get('matched_language', 'unknown')
            language_counts[lang] = language_counts.get(lang, 0) + 1

        result += f"\n**Videos by matched language:**\n"
        for lang, count in sorted(language_counts.items(), key=lambda x: x[1], reverse=True):
            result += f"- {lang}: {count}\n"

        # Generate HTML report
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Use first species name as filename base
        first_species = list(species_names.values())[0] if species_names else "multilang"
        species_safe = first_species.replace(" ", "-").replace("/", "-")
        html_filename = f"youtube_multilang_{species_safe}_{days_back}days_{timestamp}.html"
        html_path = f"./data/youtube_reports/{html_filename}"

        search_params = {
            'species_names': species_names,
            'days_back': days_back
        }
        if additional_keywords:
            search_params['additional_keywords'] = additional_keywords
        if exclude_keywords:
            search_params['exclude_keywords'] = exclude_keywords

        html_file = generate_html_report(videos, html_path, search_params)

        result += f"\n\n**HTML Report:** {html_file}\n"
        result += f"Open this file in a web browser to view embedded videos and export selected results."

        return [types.TextContent(type="text", text=result)]

    except Exception as e:
        import traceback
        error_msg = f"Error searching YouTube (multi-language): {str(e)}\n\n"
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
