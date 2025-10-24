# iNaturalist Species Observations Downloader for Wildbook Bulk Import

A Python utility for downloading recent observations of specific species from iNaturalist, including observation data (CSV) and photos. Created for the Wildbook program to help incorporate iNaturalist sightings into Wildbook via bulk import.

## Features

- Downloads observations from iNaturalist for specified species
- Configurable time range (number of days back)
- Geographic filtering by place (country, state, county, etc.)
- Downloads all photos associated with each observation
- **Two output modes:**
  - **CSV mode**: Direct export to CSV for immediate bulk import
  - **Interactive HTML review**: Visual review interface to select high-quality observations before export
- Includes observation metadata: date, location, observer, quality grade, etc.
- Custom location ID and submitter ID assignment for Wildbook bulk import
- Handles pagination automatically for large result sets
- Uses only Python standard library (no external dependencies)

## Requirements

- Python 3.6 or higher
- Internet connection
- No API key required (uses public iNaturalist API)

## Installation

1. Download the script:
```bash
chmod +x inat-download-new-species-sightings.py
```

## Usage

### Basic Syntax

```bash
python3 inat-download-new-species-sightings.py --species SPECIES_NAME [OPTIONS]
```

### Required Arguments

- `--species`: One or more species names (common or scientific names)
  - Can specify multiple species separated by spaces
  - Use quotes for multi-word names

### Optional Arguments

- `--days`: Number of days back to search (default: 30)
- `--output`: Output directory for CSV and photos (default: ./inat_data)
- `--rate-limit`: Seconds to wait between iNaturalist API calls (default: 1.0)
- `--html-review`: Generate interactive HTML review page instead of direct CSV export
- `--place`: Filter observations by place (e.g., "California", "Oregon", "United States")
- `--use-locationID`: Location ID to add to Encounter.locationID column for all observations
- `--use-submitterID`: Submitter ID to add to Encounter.submitterID column for all observations

### Examples

#### Download seadragon observations from the last 30 days (direct CSV)

```bash
python3 inat-download-new-species-sightings.py \
  --species "Phycodurus eques" "Phyllopteryx taeniolatus" \
  --days 30 \
  --output ./seadragon_data
```

#### Generate HTML review page for manual quality control

```bash
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 60 \
  --html-review \
  --output ./data
```

This creates an interactive HTML page where you can:
- View photo thumbnails for each observation
- Review observation metadata (date, location, quality grade, etc.)
- Select/deselect observations using checkboxes
- See the resulting CSV content update dynamically
- Copy the CSV to clipboard or download it directly

#### Download leafy seadragon observations from the last 7 days

```bash
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 7 \
  --output ./data
```

#### Download using common names

```bash
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" "weedy seadragon" \
  --days 14 \
  --output ./seadragons_fortnight
```

#### Download with custom rate limit

```bash
# Use a 2-second delay between API calls (more conservative)
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 7 \
  --rate-limit 2.0 \
  --output ./data

# Use a 0.5-second delay (faster, but use with caution)
python3 inat-download-new-species-sightings.py \
  --species "weedy seadragon" \
  --days 14 \
  --rate-limit 0.5 \
  --output ./data
```

#### Filter observations by geographic location

```bash
# Download only observations from California
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 60 \
  --place "California" \
  --output ./data

# Download only observations from Oregon
python3 inat-download-new-species-sightings.py \
  --species "weedy seadragon" \
  --days 30 \
  --place "Oregon" \
  --output ./data

# Combine with HTML review mode
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 60 \
  --place "California" \
  --html-review \
  --output ./data
```

#### Add a location ID to all observations

```bash
# Add a custom location ID to the Encounter.locationID column
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 30 \
  --use-locationID "AquariumOfThePacific" \
  --output ./data

# Combine place filter with location ID
python3 inat-download-new-species-sightings.py \
  --species "weedy seadragon" \
  --days 60 \
  --place "California" \
  --use-locationID "CA-Coast-001" \
  --output ./data
```

#### Add a submitter ID to all observations

```bash
# Add a custom submitter ID to the Encounter.submitterID column
python3 inat-download-new-species-sightings.py \
  --species "leafy seadragon" \
  --days 30 \
  --use-submitterID "myWildbookUsername" \
  --output ./data

# Combine location ID and submitter ID
python3 inat-download-new-species-sightings.py \
  --species "weedy seadragon" \
  --days 60 \
  --place "California" \
  --use-locationID "CA-Coast-001" \
  --use-submitterID "myWildbookUsername" \
  --output ./data
```

## Output Structure

### CSV Mode (default)

The utility creates the following structure:

```
output_directory/
├── inat_observations_YYYYMMDD_HHMMSS.csv
└── photos/
    ├── 12345_1.jpg
    ├── 12345_2.jpg
    ├── 67890_1.jpg
    └── ...
```

### HTML Review Mode (--html-review)

The utility creates the following structure:

```
output_directory/
├── inat_observations_review_YYYYMMDD_HHMMSS.html
└── photos/
    ├── 12345_1.jpg
    ├── 12345_2.jpg
    ├── 67890_1.jpg
    └── ...
```

The HTML file can be opened in any web browser. It contains:
- **Tab 1 - Review Observations**: Interactive table with photo thumbnails, checkboxes for selection, and observation details
- **Tab 2 - CSV Export**: Dynamically generated CSV content based on your selections, with copy/download buttons

**Note:** Keep the HTML file and `photos/` folder in the same directory for images to display correctly.

### CSV Format

The CSV file contains the following columns:

| Column | Description |
|--------|-------------|
| observation_id | Unique iNaturalist observation ID |
| observed_on | Date the observation was made (YYYY-MM-DD) |
| Encounter.year | Year of observation (parsed from observed_on) |
| Encounter.month | Month of observation (parsed from observed_on) |
| Encounter.day | Day of observation (parsed from observed_on) |
| scientific_name | Scientific name of the species |
| Encounter.genus | Genus name (first word of scientific name) |
| Encounter.specificEpithet | Specific epithet (second word of scientific name) |
| common_name | Common name of the species |
| Encounter.decimalLatitude | Latitude coordinate in decimal degrees |
| Encounter.decimalLongitude | Longitude coordinate in decimal degrees |
| Encounter.verbatimLocality | Location description as entered by observer |
| Encounter.locationID | Custom location ID (set via --use-locationID) |
| Encounter.livingStatus | Living status of organism ("alive", "dead", or empty) |
| Encounter.submitterID | Custom submitter ID (set via --use-submitterID) |
| observer | iNaturalist username of observer |
| quality_grade | Quality grade (research, needs_id, casual) |
| url | Link to observation on iNaturalist |
| Encounter.researcherComments | Download metadata including date and source URL |
| photo_count | Number of photos for this observation |
| photo_filenames | Semicolon-separated list of photo filenames |
| Encounter.mediaAsset0 | Filename of first photo (if present) |
| Encounter.mediaAsset1 | Filename of second photo (if present) |
| Encounter.mediaAsset2... | Additional photo columns (dynamically created) |

**Note:** The number of `Encounter.mediaAsset` columns is determined by the maximum number of photos across all observations in the dataset. Observations with fewer photos will have empty cells in the extra columns.

### Photo Files

- Photos are named: `{observation_id}_{photo_number}.{extension}`
- Original quality photos are downloaded when available
- Photos are stored in the `photos/` subdirectory

## Species Names

You can use either common names or scientific names:

### Seadragon Species

- **Leafy Seadragon**
  - Common: "leafy seadragon"
  - Scientific: "Phycodurus eques"

- **Weedy Seadragon** (also called Common Seadragon)
  - Common: "weedy seadragon"
  - Scientific: "Phyllopteryx taeniolatus"

The script will automatically find the correct species in the iNaturalist database.

## Rate Limiting

The script includes configurable rate limiting to be respectful of iNaturalist's servers. By default, it waits 1 second between API calls, which is a safe and recommended value.

**Important considerations:**
- The default 1-second delay is recommended for most use cases
- You can increase the delay (e.g., 2.0 seconds) to be more conservative
- You can decrease the delay (e.g., 0.5 seconds) for faster downloads, but use with caution
- iNaturalist may throttle or block requests if you make too many calls too quickly
- Large queries with many pages of results may take several minutes to complete

**Usage:**
```bash
# Default (1 second between calls)
python3 inat-download-new-species-sightings.py --species "leafy seadragon" --days 7

# More conservative (2 seconds between calls)
python3 inat-download-new-species-sightings.py --species "leafy seadragon" --days 7 --rate-limit 2.0

# Faster (0.5 seconds between calls) - use carefully
python3 inat-download-new-species-sightings.py --species "leafy seadragon" --days 7 --rate-limit 0.5
```

## Troubleshooting

### Species not found

If a species is not found, try:
- Using the scientific name instead of common name
- Checking the spelling
- Searching on iNaturalist.org first to confirm the species name

### No observations found

This could mean:
- No observations exist in the specified time period
- The species name didn't match any taxa
- All observations lack photos (script only downloads observations with photos)

### Download errors

- Check your internet connection
- Ensure you have write permissions in the output directory
- Some photos may fail to download due to broken links (script will continue)

## API Information

This script uses the [iNaturalist API v1](https://api.inaturalist.org/v1/docs/), which is free and doesn't require authentication for basic queries.


## Support

For issues or questions, please check the iNaturalist API documentation or community forums.

Copyright Conservation X Labs 2025.
