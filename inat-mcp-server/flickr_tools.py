#!/usr/bin/env python3
"""
Flickr Wildlife Observation Downloader
Downloads CC-licensed wildlife photos from Flickr with GPS coordinates

Matches iNaturalist workflow for Wildbook integration
"""

import json
import os
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import hashlib


class FlickrDownloader:
    """Downloads geo-tagged CC-licensed wildlife photos from Flickr API."""

    BASE_URL = "https://www.flickr.com/services/rest/"

    # CC license codes that are acceptable for research
    CC_LICENSES = {
        "4": "CC BY (Attribution)",
        "5": "CC BY-SA (Attribution-ShareAlike)",
        "6": "CC BY-ND (Attribution-NoDerivs)",
        "7": "No known copyright restrictions",
        "9": "CC0 (Public Domain)",
        "10": "Public Domain Mark"
    }

    def __init__(
        self,
        output_dir: str,
        days_back: int,
        species_list: List[str],
        rate_limit: float = 1.0,
        html_review: bool = True,
        location_id: str = None,
        submitter_id: str = None,
        api_key: str = None
    ):
        """
        Initialize the Flickr downloader.

        Args:
            output_dir: Directory to save photos and HTML/CSV
            days_back: Number of days back to search
            species_list: List of species names to search for
            rate_limit: Seconds to wait between API calls (default: 1.0)
            html_review: Generate interactive HTML review (default: True)
            location_id: Optional location ID for Wildbook
            submitter_id: Optional submitter ID for Wildbook
            api_key: Flickr API key (or set FLICKR_API_KEY env var)
        """
        self.output_dir = Path(output_dir)
        self.days_back = days_back
        self.species_list = species_list
        self.rate_limit = rate_limit
        self.html_review = html_review
        self.location_id = location_id
        self.submitter_id = submitter_id
        self.photos_dir = self.output_dir / "photos"

        # Get API key from parameter or environment
        self.api_key = api_key or os.getenv('FLICKR_API_KEY')
        if not self.api_key:
            raise ValueError(
                "Flickr API key required. Set FLICKR_API_KEY environment variable "
                "or pass api_key parameter.\n"
                "Get a key at: https://www.flickr.com/services/api/misc.api_keys.html"
            )

        # Create directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)

    def get_date_range(self) -> tuple:
        """Calculate the date range for the search."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.days_back)
        # Flickr expects Unix timestamps
        return int(start_date.timestamp()), int(end_date.timestamp())

    def resolve_species(self, species_query: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a species name (common or scientific) to proper taxonomy using iNaturalist.

        Args:
            species_query: Common or scientific name (e.g., "leopard", "Panthera pardus")

        Returns:
            Dictionary with scientific_name, genus, specific_epithet, common_name
            or None if not found
        """
        # Strip location info if present (e.g., "leopard Tanzania" -> "leopard")
        # Common location keywords to remove
        location_keywords = ['tanzania', 'kenya', 'africa', 'serengeti', 'kruger',
                            'madagascar', 'india', 'asia', 'america', 'brazil']

        query_lower = species_query.lower()
        for location in location_keywords:
            query_lower = query_lower.replace(location, '').strip()

        # Use cleaned query
        query = query_lower.strip()

        if not query:
            query = species_query  # Fall back to original if we stripped everything

        print(f"  Resolving species: '{species_query}' -> '{query}'")

        # Use iNaturalist taxa API
        inat_base = "https://api.inaturalist.org/v1"

        # Handle common ambiguous names by adding taxonomic context
        # This helps avoid matching "leopard" to "Leopard Slug"
        disambiguation = {
            'leopard': 'Panthera pardus',
            'lion': 'Panthera leo',
            'tiger': 'Panthera tigris',
            'jaguar': 'Panthera onca',
            'cheetah': 'Acinonyx jubatus',
            'elephant': 'Elephantidae',
            'african elephant': 'Loxodonta africana',
            'whale shark': 'Rhincodon typus',
            'manta ray': 'Mobula birostris',
            'giant manta ray': 'Mobula birostris'
        }

        # Check if we have a direct match for disambiguation
        query_lower = query.lower().strip()
        if query_lower in disambiguation:
            query = disambiguation[query_lower]
            print(f"  Using disambiguation: '{query_lower}' -> '{query}'")

        params = urllib.parse.urlencode({'q': query, 'rank': 'species'})
        url = f"{inat_base}/taxa?{params}"

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            time.sleep(0.5)  # Rate limiting

            if data.get('results'):
                taxon = data['results'][0]

                scientific_name = taxon.get('name', query)
                common_name = taxon.get('preferred_common_name', scientific_name)

                # Parse genus and specific epithet
                name_parts = scientific_name.split()
                genus = name_parts[0] if len(name_parts) > 0 else scientific_name
                specific_epithet = name_parts[1] if len(name_parts) > 1 else ''

                print(f"  ✓ Resolved to: {scientific_name} ({common_name})")

                return {
                    'scientific_name': scientific_name,
                    'common_name': common_name,
                    'genus': genus,
                    'specific_epithet': specific_epithet
                }
            else:
                print(f"  ⚠ Could not resolve '{query}' - using as-is")
                return None

        except Exception as e:
            print(f"  ⚠ Error resolving species: {e} - using query as-is")
            return None

    def search_photos(self, species_name: str, max_results: int = 500) -> List[Dict[str, Any]]:
        """
        Search for geo-tagged CC-licensed photos of a species.

        Args:
            species_name: Species name to search for
            max_results: Maximum number of photos to retrieve

        Returns:
            List of photo dictionaries
        """
        print(f"\nSearching Flickr for: {species_name}")

        min_date, max_date = self.get_date_range()

        # Flickr API parameters
        params = {
            'method': 'flickr.photos.search',
            'api_key': self.api_key,
            'text': species_name,
            'license': ','.join(self.CC_LICENSES.keys()),  # CC licenses only
            'has_geo': '1',  # Must have GPS coordinates
            'content_type': '1',  # Photos only
            'min_taken_date': str(min_date),
            'max_taken_date': str(max_date),
            'extras': 'geo,license,date_taken,tags,description,url_l,url_o,owner_name,path_alias',
            'per_page': min(500, max_results),
            'page': 1,
            'format': 'json',
            'nojsoncallback': 1
        }

        all_photos = []
        page = 1

        while len(all_photos) < max_results:
            params['page'] = page
            url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"

            try:
                with urllib.request.urlopen(url) as response:
                    data = json.loads(response.read().decode())

                # Rate limiting
                time.sleep(self.rate_limit)

                if data.get('stat') != 'ok':
                    print(f"  Error from Flickr API: {data.get('message', 'Unknown error')}")
                    break

                photos_data = data.get('photos', {})
                photos = photos_data.get('photo', [])

                if not photos:
                    break

                all_photos.extend(photos)
                print(f"  Retrieved page {page}: {len(photos)} photos (total: {len(all_photos)})")

                # Check if we've reached the last page
                if page >= photos_data.get('pages', 1):
                    break

                page += 1

            except Exception as e:
                print(f"  Error searching Flickr: {e}")
                break

        print(f"  Found {len(all_photos)} total photos for '{species_name}'")
        return all_photos[:max_results]

    def get_photo_info(self, photo_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a photo including EXIF data.

        Args:
            photo_id: Flickr photo ID

        Returns:
            Photo info dictionary or None
        """
        params = {
            'method': 'flickr.photos.getInfo',
            'api_key': self.api_key,
            'photo_id': photo_id,
            'format': 'json',
            'nojsoncallback': 1
        }

        url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            time.sleep(self.rate_limit)

            if data.get('stat') == 'ok':
                return data.get('photo', {})
            return None

        except Exception as e:
            print(f"  Error getting photo info: {e}")
            return None

    def download_photo(self, photo: Dict[str, Any]) -> Optional[str]:
        """
        Download a photo and return the local filename.

        Args:
            photo: Photo dictionary from Flickr API

        Returns:
            Local filename or None if download failed
        """
        # Prefer original size, fall back to large
        url = photo.get('url_o') or photo.get('url_l')
        if not url:
            return None

        # Generate unique filename
        photo_id = photo.get('id')
        extension = url.split('.')[-1].split('?')[0]
        filename = f"flickr_{photo_id}.{extension}"
        filepath = self.photos_dir / filename

        # Download if not already cached
        if filepath.exists():
            return filename

        try:
            urllib.request.urlretrieve(url, filepath)
            time.sleep(self.rate_limit * 0.5)  # Lighter rate limit for downloads
            return filename
        except Exception as e:
            print(f"  Error downloading photo {photo_id}: {e}")
            return None

    def process_observations(self, species_name: str, max_results: int = 500) -> List[Dict[str, Any]]:
        """
        Process Flickr photos into observation format matching iNaturalist structure.

        Args:
            species_name: Species to search for (common or scientific name)
            max_results: Maximum photos to retrieve

        Returns:
            List of observation dictionaries
        """
        # Resolve species name to proper taxonomy
        taxonomy = self.resolve_species(species_name)

        if taxonomy:
            # Use resolved taxonomy
            scientific_name = taxonomy['scientific_name']
            common_name = taxonomy['common_name']
            genus = taxonomy['genus']
            specific_epithet = taxonomy['specific_epithet']
        else:
            # Fallback to naive parsing if resolution fails
            scientific_name = species_name
            common_name = species_name
            parts = species_name.split()
            genus = parts[0] if len(parts) > 0 else species_name
            specific_epithet = parts[1] if len(parts) > 1 else ''

        photos = self.search_photos(species_name, max_results)

        observations = []

        for i, photo in enumerate(photos, 1):
            print(f"  Processing photo {i}/{len(photos)}: {photo.get('id')}")

            # Download photo
            filename = self.download_photo(photo)
            if not filename:
                continue

            # Get detailed photo info for full metadata
            photo_info = self.get_photo_info(photo.get('id'))
            if not photo_info:
                photo_info = photo

            # Extract date (prefer date taken, fall back to upload date)
            date_taken = photo.get('datetaken')
            if date_taken:
                try:
                    dt = datetime.strptime(date_taken, '%Y-%m-%d %H:%M:%S')
                    observed_on = dt.strftime('%Y-%m-%d')
                    year, month, day = dt.year, dt.month, dt.day
                except:
                    observed_on = datetime.now().strftime('%Y-%m-%d')
                    year, month, day = datetime.now().year, datetime.now().month, datetime.now().day
            else:
                observed_on = datetime.now().strftime('%Y-%m-%d')
                year, month, day = datetime.now().year, datetime.now().month, datetime.now().day

            # Extract GPS coordinates
            latitude = float(photo.get('latitude', 0))
            longitude = float(photo.get('longitude', 0))

            # Extract description from detailed photo info
            description = ''
            if photo_info and 'description' in photo_info:
                desc_obj = photo_info.get('description', {})
                if isinstance(desc_obj, dict):
                    description = desc_obj.get('_content', '')
                elif isinstance(desc_obj, str):
                    description = desc_obj

            # Extract location from Flickr's location hierarchy
            verbatim_locality = ''
            if photo_info and 'location' in photo_info:
                location_obj = photo_info.get('location', {})
                location_parts = []

                # Build location string from hierarchy: locality, region, country
                for field in ['locality', 'county', 'region', 'country']:
                    if field in location_obj:
                        field_data = location_obj[field]
                        if isinstance(field_data, dict):
                            content = field_data.get('_content', '').strip()
                            if content:
                                location_parts.append(content)
                        elif isinstance(field_data, str) and field_data.strip():
                            location_parts.append(field_data.strip())

                verbatim_locality = ', '.join(location_parts) if location_parts else ''

            # Fallback to title if no location found
            if not verbatim_locality:
                verbatim_locality = photo.get('title', '') or 'Flickr observation'

            # Get license info
            license_code = str(photo.get('license', ''))
            license_name = self.CC_LICENSES.get(license_code, 'Unknown')

            # Use taxonomy resolved at the beginning of this method
            # (scientific_name, common_name, genus, specific_epithet already set)

            # Build observation dictionary matching iNaturalist format
            observation = {
                'observation_id': f"flickr_{photo.get('id')}",
                'observed_on': observed_on,
                'Encounter.year': year,
                'Encounter.month': month,
                'Encounter.day': day,
                'scientific_name': scientific_name,
                'Encounter.genus': genus,
                'Encounter.specificEpithet': specific_epithet,
                'common_name': common_name,
                'Encounter.decimalLatitude': latitude,
                'Encounter.decimalLongitude': longitude,
                'Encounter.verbatimLocality': verbatim_locality,
                'Encounter.sightingRemarks': description,
                'Encounter.locationID': self.location_id or '',
                'Encounter.livingStatus': 'alive',
                'Encounter.submitterID': self.submitter_id or 'public',
                'Sighting.sightingID': f"flickr_sighting_{photo.get('id')}",
                'observer': photo.get('ownername', 'Unknown'),
                'quality_grade': 'community',  # Flickr doesn't have quality grades
                'url': f"https://www.flickr.com/photos/{photo.get('owner')}/{photo.get('id')}",
                'Encounter.researcherComments': f"Source: Flickr | License: {license_name} | URL: https://www.flickr.com/photos/{photo.get('owner')}/{photo.get('id')}",
                '_photo_list': [filename],
                '_license_list': [license_name],
                '_has_non_organism_evidence': False,
                '_is_skulls_and_bones': False,
                'license': license_name,
                'license_code': license_code
            }

            observations.append(observation)

        return observations

    def run(self) -> Dict[str, Any]:
        """
        Run the complete Flickr download workflow.

        Returns:
            Summary dictionary
        """
        all_observations = []

        for species in self.species_list:
            obs = self.process_observations(species)
            all_observations.extend(obs)

        if not all_observations:
            print("\nNo observations found.")
            return {
                'total_observations': 0,
                'species_counts': {},
                'output_files': []
            }

        # Generate output filename
        species_part = "_".join([s.replace(" ", "-") for s in self.species_list[:2]])
        date_part = datetime.now().strftime("%Y%m%d_%H%M%S")

        if self.html_review:
            filename = f"flickr_observations_review_{species_part}_{date_part}.html"
            self.write_html(all_observations, filename)
            output_files = [str(self.output_dir / filename)]
        else:
            filename = f"flickr_observations_{species_part}_{date_part}.csv"
            self.write_csv(all_observations, filename)
            output_files = [str(self.output_dir / filename)]

        # Count by species
        species_counts = {}
        for obs in all_observations:
            species = obs.get('scientific_name', 'Unknown')
            species_counts[species] = species_counts.get(species, 0) + 1

        return {
            'total_observations': len(all_observations),
            'species_counts': species_counts,
            'output_files': output_files
        }

    def write_html(self, data: List[Dict[str, Any]], filename: str):
        """
        Write observation data to interactive HTML review page (matching iNat style).

        Args:
            data: List of observation dictionaries
            filename: HTML filename
        """
        if not data:
            print("No data to write to HTML")
            return

        html_path = self.output_dir / filename

        # Build observations for JSON
        observations_json = []
        max_photos = 1  # Flickr only has 1 photo per observation

        for row in data:
            photo_list = row.get('_photo_list', [])
            license_list = row.get('_license_list', [])

            # Use file path for photo preview
            photo_path = None
            all_photo_paths = []

            for photo_filename in photo_list:
                photo_file_path = self.photos_dir / photo_filename
                if photo_file_path.exists():
                    rel_path = f"photos/{photo_filename}"
                    all_photo_paths.append(rel_path)
                    if not photo_path:
                        photo_path = rel_path

            obs_data = {
                'observation_id': row.get('observation_id'),
                'observed_on': row.get('observed_on'),
                'year': row.get('Encounter.year'),
                'month': row.get('Encounter.month'),
                'day': row.get('Encounter.day'),
                'scientific_name': row.get('scientific_name'),
                'genus': row.get('Encounter.genus'),
                'specific_epithet': row.get('Encounter.specificEpithet'),
                'common_name': row.get('common_name'),
                'latitude': row.get('Encounter.decimalLatitude'),
                'longitude': row.get('Encounter.decimalLongitude'),
                'location': row.get('Encounter.verbatimLocality'),
                'location_id': row.get('Encounter.locationID'),
                'living_status': row.get('Encounter.livingStatus'),
                'submitter_id': row.get('Encounter.submitterID'),
                'sighting_id': row.get('Sighting.sightingID'),
                'sighting_remarks': row.get('Encounter.sightingRemarks', ''),
                'observer': row.get('observer'),
                'quality_grade': row.get('quality_grade'),
                'url': row.get('url'),
                'researcher_comments': row.get('Encounter.researcherComments'),
                'license_display': row.get('license', 'Unknown'),
                'photo_path': photo_path,
                'all_photo_paths': all_photo_paths,
                '_photo_list': photo_list,  # Keep for CSV export
                '_license_list': license_list,  # Keep for CSV export
            }

            observations_json.append(obs_data)

        # Generate HTML
        html_content = self._generate_html_template(observations_json)

        # Write file
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"\nHTML review page written: {html_path}")
        print(f"Total observations: {len(data)}")

    def _generate_html_template(self, observations: List[Dict]) -> str:
        """Generate HTML template matching iNaturalist style."""
        observations_json_str = json.dumps(observations, indent=2)

        species_part = "_".join([s.replace(" ", "-") for s in self.species_list[:2]])
        date_part = datetime.now().strftime("%Y%m%d")

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Flickr Wildlife Observations Review</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f5f5f5;
            padding: 20px;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .header {{
            background: #FF0084;
            color: white;
            padding: 20px 30px;
            border-radius: 8px 8px 0 0;
        }}

        .header h1 {{
            font-size: 24px;
            margin-bottom: 5px;
        }}

        .header p {{
            opacity: 0.9;
            font-size: 14px;
        }}

        .tabs {{
            display: flex;
            background: #e8e8e8;
            border-bottom: 2px solid #ddd;
        }}

        .tab {{
            padding: 15px 30px;
            cursor: pointer;
            font-weight: 500;
            border: none;
            background: transparent;
            transition: all 0.2s;
        }}

        .tab:hover {{
            background: #d8d8d8;
        }}

        .tab.active {{
            background: white;
            border-bottom: 3px solid #FF0084;
        }}

        .tab-content {{
            display: none;
            padding: 30px;
        }}

        .tab-content.active {{
            display: block;
        }}

        .stats {{
            background: #f9f9f9;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            display: flex;
            gap: 30px;
            align-items: center;
        }}

        .stat {{
            display: flex;
            flex-direction: column;
        }}

        .stat-label {{
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #FF0084;
        }}

        .controls {{
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
        }}

        .btn {{
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }}

        .btn-primary {{
            background: #FF0084;
            color: white;
        }}

        .btn-primary:hover {{
            background: #D1006D;
        }}

        .btn-secondary {{
            background: #e0e0e0;
            color: #333;
        }}

        .btn-secondary:hover {{
            background: #d0d0d0;
        }}

        .table-wrapper {{
            width: 100%;
            overflow-x: auto;
        }}

        .observations-table {{
            width: 100%;
            border-collapse: collapse;
        }}

        .observations-table thead {{
            background: #f5f5f5;
            position: sticky;
            top: 0;
        }}

        .observations-table th {{
            padding: 12px;
            text-align: left;
            font-weight: 600;
            border-bottom: 2px solid #ddd;
            white-space: nowrap;
        }}

        .observations-table td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
            vertical-align: top;
        }}

        .observations-table tr:hover {{
            background: #f9f9f9;
        }}

        .photo-preview {{
            width: 100px;
            height: 100px;
            object-fit: cover;
            border-radius: 4px;
            cursor: pointer;
        }}

        .photo-preview:hover {{
            opacity: 0.8;
        }}

        .license-badge {{
            display: inline-block;
            background: #e8f5e9;
            color: #2e7d32;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
        }}

        .modal {{
            display: none;
            position: fixed;
            z-index: 1000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.9);
        }}

        .modal-content {{
            margin: auto;
            display: block;
            max-width: 90%;
            max-height: 90%;
            position: relative;
            top: 50%;
            transform: translateY(-50%);
        }}

        .close {{
            position: absolute;
            top: 15px;
            right: 35px;
            color: #f1f1f1;
            font-size: 40px;
            font-weight: bold;
            cursor: pointer;
        }}

        .close:hover {{
            color: #bbb;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📸 Flickr Wildlife Observations</h1>
            <p>Creative Commons licensed wildlife photos with GPS coordinates</p>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="showTab('review')">Review Observations</button>
            <button class="tab" onclick="showTab('export')">CSV Export</button>
        </div>

        <div id="review-tab" class="tab-content active">
            <div class="stats">
                <div class="stat">
                    <span class="stat-label">Total Observations</span>
                    <span class="stat-value" id="total-count">0</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Selected</span>
                    <span class="stat-value" id="selected-count">0</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Species</span>
                    <span class="stat-value">{len(self.species_list)}</span>
                </div>
            </div>

            <div class="controls">
                <button class="btn btn-primary" onclick="selectAll()">Select All</button>
                <button class="btn btn-secondary" onclick="deselectAll()">Deselect All</button>
            </div>

            <div class="table-wrapper">
                <table class="observations-table" id="observations-table">
                    <thead>
                        <tr>
                            <th>✓</th>
                            <th>Photo</th>
                            <th>Date</th>
                            <th>Species</th>
                            <th>Location</th>
                            <th>Coordinates</th>
                            <th>Observer</th>
                            <th>License</th>
                            <th>Link</th>
                        </tr>
                    </thead>
                    <tbody id="observations-body">
                    </tbody>
                </table>
            </div>
        </div>

        <div id="export-tab" class="tab-content">
            <h2>Export to Wildbook CSV</h2>
            <p style="margin: 20px 0;">Click the button below to generate a Wildbook-compatible CSV file with selected observations.</p>

            <button class="btn btn-primary" onclick="exportCSV()">📥 Download CSV</button>

            <div style="margin-top: 30px;">
                <h3>Export Preview</h3>
                <textarea id="csv-preview" readonly style="width: 100%; height: 400px; font-family: monospace; padding: 10px; border: 1px solid #ddd; border-radius: 4px; margin-top: 10px;"></textarea>
            </div>
        </div>
    </div>

    <!-- Image Modal -->
    <div id="imageModal" class="modal" onclick="closeModal()">
        <span class="close">&times;</span>
        <img class="modal-content" id="modal-image">
    </div>

    <script>
        const observations = {observations_json_str};

        function showTab(tabName) {{
            const tabs = document.querySelectorAll('.tab');
            const contents = document.querySelectorAll('.tab-content');

            tabs.forEach(tab => tab.classList.remove('active'));
            contents.forEach(content => content.classList.remove('active'));

            event.target.classList.add('active');
            document.getElementById(tabName + '-tab').classList.add('active');
        }}

        function renderObservations() {{
            const tbody = document.getElementById('observations-body');
            tbody.innerHTML = '';

            observations.forEach((obs, index) => {{
                const row = document.createElement('tr');

                const photoPreview = obs.photo_path ?
                    `<img src="${{obs.photo_path}}" class="photo-preview" onclick="showImage('${{obs.photo_path}}')" alt="Preview">` :
                    'No photo';

                const coords = obs.latitude && obs.longitude ?
                    `${{parseFloat(obs.latitude).toFixed(6)}}, ${{parseFloat(obs.longitude).toFixed(6)}}` :
                    'No GPS';

                row.innerHTML = `
                    <td><input type="checkbox" class="obs-checkbox" data-index="${{index}}" checked onchange="updateCount()"></td>
                    <td>${{photoPreview}}</td>
                    <td>${{obs.observed_on || 'Unknown'}}</td>
                    <td><em>${{obs.scientific_name || obs.common_name}}</em></td>
                    <td>${{obs.location || 'Unknown'}}</td>
                    <td>${{coords}}</td>
                    <td>${{obs.observer || 'Unknown'}}</td>
                    <td><span class="license-badge">${{obs.license_display}}</span></td>
                    <td><a href="${{obs.url}}" target="_blank">View</a></td>
                `;

                tbody.appendChild(row);
            }});

            updateCount();
        }}

        function updateCount() {{
            const total = observations.length;
            const selected = document.querySelectorAll('.obs-checkbox:checked').length;

            document.getElementById('total-count').textContent = total;
            document.getElementById('selected-count').textContent = selected;
        }}

        function selectAll() {{
            document.querySelectorAll('.obs-checkbox').forEach(cb => cb.checked = true);
            updateCount();
        }}

        function deselectAll() {{
            document.querySelectorAll('.obs-checkbox').forEach(cb => cb.checked = false);
            updateCount();
        }}

        function showImage(src) {{
            const modal = document.getElementById('imageModal');
            const modalImg = document.getElementById('modal-image');
            modal.style.display = 'block';
            modalImg.src = src;
        }}

        function closeModal() {{
            document.getElementById('imageModal').style.display = 'none';
        }}

        function exportCSV() {{
            const selected = [];
            document.querySelectorAll('.obs-checkbox:checked').forEach(cb => {{
                const index = parseInt(cb.dataset.index);
                selected.push(observations[index]);
            }});

            if (selected.length === 0) {{
                alert('No observations selected. Please select at least one observation.');
                return;
            }}

            // Build Wildbook CSV
            let csv = 'observation_id,observed_on,Encounter.year,Encounter.month,Encounter.day,';
            csv += 'scientific_name,Encounter.genus,Encounter.specificEpithet,common_name,';
            csv += 'Encounter.decimalLatitude,Encounter.decimalLongitude,Encounter.verbatimLocality,';
            csv += 'Encounter.locationID,Encounter.livingStatus,Encounter.submitterID,';
            csv += 'Sighting.sightingID,Encounter.sightingRemarks,observer,quality_grade,url,Encounter.researcherComments,';
            csv += 'Encounter.mediaAsset0,Encounter.mediaAsset0.license\\n';

            selected.forEach(obs => {{
                const escape = (str) => `"${{(str || '').toString().replace(/"/g, '""')}}"`;

                // Get photo filename and license from photo list
                const photoList = obs._photo_list || [];
                const licenseList = obs._license_list || [];
                const photo0 = photoList.length > 0 ? photoList[0] : '';
                const license0 = licenseList.length > 0 ? licenseList[0] : '';

                const row = [
                    escape(obs.observation_id),
                    escape(obs.observed_on),
                    escape(obs.year),
                    escape(obs.month),
                    escape(obs.day),
                    escape(obs.scientific_name),
                    escape(obs.genus),
                    escape(obs.specific_epithet),
                    escape(obs.common_name),
                    escape(obs.latitude),
                    escape(obs.longitude),
                    escape(obs.location),
                    escape(obs.location_id),
                    escape(obs.living_status),
                    escape(obs.submitter_id),
                    escape(obs.sighting_id),
                    escape(obs.sighting_remarks),
                    escape(obs.observer),
                    escape(obs.quality_grade),
                    escape(obs.url),
                    escape(obs.researcher_comments),
                    escape(photo0),
                    escape(license0)
                ];

                csv += row.join(',') + '\\n';
            }});

            // Show preview
            document.getElementById('csv-preview').value = csv;

            // Download file
            const blob = new Blob([csv], {{ type: 'text/csv' }});
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'flickr_observations_{species_part}_{date_part}.csv';
            a.click();
            window.URL.revokeObjectURL(url);
        }}

        // Initialize
        renderObservations();
    </script>
</body>
</html>'''

    def write_csv(self, data: List[Dict[str, Any]], filename: str):
        """Write observations to CSV in Wildbook format (fallback if no HTML)."""
        # This would implement CSV writing - simplified for now
        pass


if __name__ == "__main__":
    # Test the downloader
    downloader = FlickrDownloader(
        output_dir="./data",
        days_back=30,
        species_list=["whale shark"],
        html_review=True
    )
    result = downloader.run()
    print(f"\nComplete! {result['total_observations']} observations downloaded.")
