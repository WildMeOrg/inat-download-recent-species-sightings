#!/usr/bin/env python3
"""
iNaturalist Species Observations Downloader
Created for SeadragonSearch.org program

Downloads recent observations of specified species from iNaturalist,
including observation data (CSV) and photos.
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import urllib.request
import urllib.parse
import json
import time
import uuid


class iNaturalistDownloader:
    """Downloads observations and photos from iNaturalist API."""

    BASE_URL = "https://api.inaturalist.org/v1"

    def __init__(self, output_dir: str, days_back: int, species_list: List[str], rate_limit: float = 1.0, html_review: bool = False, place: str = None, location_id: str = None, submitter_id: str = None, social_split: bool = False):
        """
        Initialize the downloader.

        Args:
            output_dir: Directory to save CSV and photos
            days_back: Number of days back to search for observations
            species_list: List of species names to search for
            rate_limit: Seconds to wait between API calls (default: 1.0)
            html_review: Generate interactive HTML review instead of CSV (default: False)
            place: Optional place name to filter observations (e.g., "California", "Oregon", "United States")
            location_id: Optional location ID to add to all observations in Encounter.locationID column
            submitter_id: Optional submitter ID to add to all observations in Encounter.submitterID column
            social_split: Split multi-photo observations into separate rows with shared sighting ID (default: False)
        """
        self.output_dir = Path(output_dir)
        self.days_back = days_back
        self.species_list = species_list
        self.rate_limit = rate_limit
        self.html_review = html_review
        self.place = place
        self.place_id = None
        self.location_id = location_id
        self.submitter_id = submitter_id
        self.social_split = social_split
        self.photos_dir = self.output_dir / "photos"

        # Create directories if they don't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)

    def get_date_range(self) -> tuple:
        """Calculate the date range for the search."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=self.days_back)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    def search_species(self, species_name: str) -> int:
        """
        Search for a species by name and return its taxon ID.

        Args:
            species_name: Common or scientific name of the species

        Returns:
            Taxon ID of the species, or None if not found
        """
        print(f"Searching for species: {species_name}")

        params = urllib.parse.urlencode({
            'q': species_name,
            'rank': 'species'
        })

        url = f"{self.BASE_URL}/taxa?{params}"

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            # Rate limiting
            time.sleep(self.rate_limit)

            if data['results']:
                taxon = data['results'][0]
                taxon_id = taxon['id']
                name = taxon.get('preferred_common_name', taxon['name'])
                print(f"  Found: {name} (ID: {taxon_id})")
                return taxon_id
            else:
                print(f"  Warning: Species '{species_name}' not found")
                return None

        except Exception as e:
            print(f"  Error searching for species '{species_name}': {e}")
            return None

    def resolve_place(self, place_name: str) -> int:
        """
        Resolve a place name to a place ID, preferring political boundaries.

        Args:
            place_name: Name of the place (e.g., "California", "Oregon", "United States")

        Returns:
            Place ID, or None if not found
        """
        print(f"Resolving place: {place_name}")

        params = urllib.parse.urlencode({'q': place_name})
        url = f"{self.BASE_URL}/places/autocomplete?{params}"

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            # Rate limiting
            time.sleep(self.rate_limit)

            places = data.get('results', [])

            if not places:
                print(f"  Warning: No places found for '{place_name}'")
                return None

            # Prioritize places by type (countries, states, counties, provinces)
            priority_types = ["country", "state", "county", "province"]

            for place_type in priority_types:
                for place in places:
                    if place.get("place_type") == place_type and place_name.lower() in place.get("name", "").lower():
                        place_id = place["id"]
                        display_name = place.get("display_name", place.get("name"))
                        print(f"  Found: {display_name} (ID: {place_id}, Type: {place_type})")
                        return place_id

            # If no priority match, return the first exact name match
            for place in places:
                if place.get("name", "").lower() == place_name.lower():
                    place_id = place["id"]
                    display_name = place.get("display_name", place.get("name"))
                    print(f"  Found: {display_name} (ID: {place_id})")
                    return place_id

            # If no exact match, return the first result
            first_place = places[0]
            place_id = first_place["id"]
            display_name = first_place.get("display_name", first_place.get("name"))
            print(f"  Found (first result): {display_name} (ID: {place_id})")
            return place_id

        except Exception as e:
            print(f"  Error resolving place '{place_name}': {e}")
            return None

    def get_observations(self, taxon_id: int) -> List[Dict[Any, Any]]:
        """
        Get observations for a specific taxon ID within the date range.

        Args:
            taxon_id: iNaturalist taxon ID

        Returns:
            List of observation dictionaries
        """
        start_date, end_date = self.get_date_range()

        print(f"  Fetching observations from {start_date} to {end_date}...")

        all_observations = []
        page = 1
        per_page = 200  # Max allowed by API

        while True:
            params_dict = {
                'taxon_id': taxon_id,
                'd1': start_date,
                'd2': end_date,
                'has[]': 'photos',
                'quality_grade': 'any',
                'per_page': per_page,
                'page': page,
                'order_by': 'observed_on'
            }

            # Add place_id if it was specified
            if self.place_id is not None:
                params_dict['place_id'] = self.place_id

            params = urllib.parse.urlencode(params_dict)

            url = f"{self.BASE_URL}/observations?{params}"

            try:
                with urllib.request.urlopen(url) as response:
                    data = json.loads(response.read().decode())

                # Rate limiting
                time.sleep(self.rate_limit)

                results = data.get('results', [])

                if not results:
                    break

                all_observations.extend(results)
                print(f"    Page {page}: {len(results)} observations")

                # Check if there are more pages
                total_results = data.get('total_results', 0)
                if len(all_observations) >= total_results:
                    break

                page += 1

            except Exception as e:
                print(f"    Error fetching observations (page {page}): {e}")
                break

        print(f"  Total observations found: {len(all_observations)}")
        return all_observations

    def download_photo(self, url: str, filename: str) -> bool:
        """
        Download a photo from URL to the photos directory.

        Args:
            url: URL of the photo
            filename: Filename to save as

        Returns:
            True if successful, False otherwise
        """
        filepath = self.photos_dir / filename

        # Skip if already downloaded
        if filepath.exists():
            return True

        try:
            urllib.request.urlretrieve(url, filepath)
            return True
        except Exception as e:
            print(f"      Error downloading photo {filename}: {e}")
            return False

    def process_observations(self, observations: List[Dict[Any, Any]], species_name: str) -> List[Dict[str, Any]]:
        """
        Process observations and download photos.

        Args:
            observations: List of observation dictionaries from API
            species_name: Name of the species for reference

        Returns:
            List of processed observation dictionaries for CSV export
        """
        processed_data = []

        for idx, obs in enumerate(observations, 1):
            obs_id = obs['id']
            observed_on = obs.get('observed_on', 'Unknown')

            # Location data - handle various ways iNaturalist stores coordinates
            latitude = None
            longitude = None

            # Try 'location' field first (comma-separated lat,lon string)
            location_str = obs.get('location')
            if location_str:
                lat_lon = location_str.split(',')
                latitude = lat_lon[0].strip() if len(lat_lon) > 0 else None
                longitude = lat_lon[1].strip() if len(lat_lon) > 1 else None
            else:
                # Try geojson coordinates (if geojson exists and is not None)
                geojson = obs.get('geojson')
                if geojson and isinstance(geojson, dict):
                    coordinates = geojson.get('coordinates', [])
                    if coordinates and isinstance(coordinates, list) and len(coordinates) >= 2:
                        longitude = coordinates[0]
                        latitude = coordinates[1]

            # Place name
            place_guess = obs.get('place_guess', '')

            # Observer
            user = obs.get('user')
            observer = user.get('login', 'Unknown') if user and isinstance(user, dict) else 'Unknown'

            # Quality grade
            quality_grade = obs.get('quality_grade', 'Unknown')

            # URL
            obs_url = f"https://www.inaturalist.org/observations/{obs_id}"

            # Taxon info
            taxon = obs.get('taxon')
            if taxon and isinstance(taxon, dict):
                scientific_name = taxon.get('name', species_name)
                common_name = taxon.get('preferred_common_name', '')
            else:
                scientific_name = species_name
                common_name = ''

            # Parse date components from observed_on (format: YYYY-MM-DD)
            encounter_year = None
            encounter_month = None
            encounter_day = None
            if observed_on and observed_on != 'Unknown':
                try:
                    date_parts = observed_on.split('-')
                    if len(date_parts) >= 3:
                        encounter_year = date_parts[0]
                        encounter_month = date_parts[1]
                        encounter_day = date_parts[2]
                except Exception:
                    pass  # Keep as None if parsing fails

            # Parse scientific name into genus and specific epithet
            encounter_genus = None
            encounter_specific_epithet = None
            if scientific_name:
                name_parts = scientific_name.split()
                if len(name_parts) >= 1:
                    encounter_genus = name_parts[0]
                if len(name_parts) >= 2:
                    encounter_specific_epithet = name_parts[1]

            # Parse annotations for living status and evidence of presence
            living_status = 'alive'  # Default to 'alive'
            is_single_subject = False  # Track if observation has "single subject" annotation
            has_non_organism_evidence = False  # Track if evidence is something other than organism
            annotations = obs.get('annotations')
            if annotations and isinstance(annotations, list):
                for annotation in annotations:
                    if isinstance(annotation, dict):
                        controlled_value_id = annotation.get('controlled_value_id')
                        controlled_attribute_id = annotation.get('controlled_attribute_id')

                        # Living status annotation
                        if controlled_value_id == 19:
                            living_status = 'dead'
                        elif controlled_value_id == 14:
                            living_status = 'alive'

                        # Evidence of Presence annotations (controlled_attribute_id == 22)
                        if controlled_attribute_id == 22:
                            # controlled_value_id 24 = "Organism" (single subject - good)
                            if controlled_value_id == 24:
                                is_single_subject = True
                            # Any other value (track, scat, molt, etc.) should be deselected
                            elif controlled_value_id is not None:
                                has_non_organism_evidence = True

            # Check if observation is part of "Skulls and Bones" project (ID 488)
            project_ids = obs.get('project_ids', [])
            is_skulls_and_bones = 488 in project_ids if project_ids else False

            # Download photos
            photos = obs.get('photos', [])
            photo_filenames = []
            photo_licenses = []

            if photos:
                print(f"  Processing observation {idx}/{len(observations)} (ID: {obs_id}, {len(photos)} photos)...")

                for photo_idx, photo in enumerate(photos, 1):
                    # Use original or large size
                    photo_url = photo.get('url', '').replace('square', 'original')

                    # Get license code
                    license_code = photo.get('license_code', '')

                    # Create unique filename
                    photo_ext = photo_url.split('.')[-1].split('?')[0]
                    if '/' in photo_ext or len(photo_ext) > 4:
                        photo_ext = 'jpg'

                    photo_filename = f"{obs_id}_{photo_idx}.{photo_ext}"

                    if self.download_photo(photo_url, photo_filename):
                        photo_filenames.append(photo_filename)
                        photo_licenses.append(license_code)

            # Create researcher comments with download date, source URL, and license info
            today_date = datetime.now().strftime("%Y-%m-%d")
            researcher_comments = f"Observation downloaded from iNaturalist on {today_date}.<br>Source: {obs_url}"

            # Add license information to researcher comments
            if photo_licenses:
                unique_licenses = list(set([lic for lic in photo_licenses if lic]))
                if unique_licenses:
                    license_str = ', '.join(unique_licenses)
                    researcher_comments += f"<br>License(s): {license_str}"
                else:
                    researcher_comments += "<br>License: None specified. Copyright applies."

            # If social_split is enabled and there are multiple photos, create one row per photo
            # BUT only if the observation is NOT marked as single subject
            if self.social_split and len(photo_filenames) > 1 and not is_single_subject:
                # Generate a common sighting ID for all photos from this observation
                sighting_id = str(uuid.uuid4())

                # Create one row for each photo
                for photo_idx, (photo_filename, photo_license) in enumerate(zip(photo_filenames, photo_licenses)):
                    row = {
                        'observation_id': obs_id,
                        'observed_on': observed_on,
                        'Encounter.year': encounter_year,
                        'Encounter.month': encounter_month,
                        'Encounter.day': encounter_day,
                        'scientific_name': scientific_name,
                        'Encounter.genus': encounter_genus,
                        'Encounter.specificEpithet': encounter_specific_epithet,
                        'common_name': common_name,
                        'Encounter.decimalLatitude': latitude,
                        'Encounter.decimalLongitude': longitude,
                        'Encounter.verbatimLocality': place_guess,
                        'Encounter.locationID': self.location_id if self.location_id else None,
                        'Encounter.livingStatus': living_status,
                        'Encounter.submitterID': self.submitter_id if self.submitter_id else None,
                        'Encounter.state': 'unapproved',
                        'observer': observer,
                        'quality_grade': quality_grade,
                        'url': obs_url,
                        'Encounter.researcherComments': researcher_comments,
                        'Sighting.sightingID': sighting_id,
                        'photo_count': 1,  # Each row has one photo
                        'photo_filenames': photo_filename,
                        '_photo_list': [photo_filename],  # Single photo for this encounter
                        '_license_list': [photo_license],  # Single license for this encounter
                        '_has_non_organism_evidence': has_non_organism_evidence,  # For HTML deselection
                        '_is_skulls_and_bones': is_skulls_and_bones  # For HTML deselection
                    }
                    processed_data.append(row)
            else:
                # Original behavior: one row per observation
                # Sighting ID only populated when social_split is enabled
                sighting_id = str(uuid.uuid4()) if self.social_split and len(photo_filenames) >= 1 else None

                row = {
                    'observation_id': obs_id,
                    'observed_on': observed_on,
                    'Encounter.year': encounter_year,
                    'Encounter.month': encounter_month,
                    'Encounter.day': encounter_day,
                    'scientific_name': scientific_name,
                    'Encounter.genus': encounter_genus,
                    'Encounter.specificEpithet': encounter_specific_epithet,
                    'common_name': common_name,
                    'Encounter.decimalLatitude': latitude,
                    'Encounter.decimalLongitude': longitude,
                    'Encounter.verbatimLocality': place_guess,
                    'Encounter.locationID': self.location_id if self.location_id else None,
                    'Encounter.livingStatus': living_status,
                    'Encounter.submitterID': self.submitter_id if self.submitter_id else None,
                    'Encounter.state': 'unapproved',
                    'observer': observer,
                    'quality_grade': quality_grade,
                    'url': obs_url,
                    'Encounter.researcherComments': researcher_comments,
                    'Sighting.sightingID': sighting_id,
                    'photo_count': len(photo_filenames),
                    'photo_filenames': '; '.join(photo_filenames),
                    '_photo_list': photo_filenames,  # Temporary field for photo processing
                    '_license_list': photo_licenses,  # Temporary field for license processing
                    '_has_non_organism_evidence': has_non_organism_evidence,  # For HTML deselection
                    '_is_skulls_and_bones': is_skulls_and_bones  # For HTML deselection
                }
                processed_data.append(row)

        return processed_data

    def write_csv(self, data: List[Dict[str, Any]], filename: str):
        """
        Write observation data to CSV file.

        Args:
            data: List of observation dictionaries
            filename: CSV filename
        """
        if not data:
            print("No data to write to CSV")
            return

        csv_path = self.output_dir / filename

        # Determine maximum number of photos across all observations
        max_photos = 0
        for row in data:
            photo_list = row.get('_photo_list', [])
            if len(photo_list) > max_photos:
                max_photos = len(photo_list)

        # Add individual photo columns and license columns to each row
        for row in data:
            photo_list = row.get('_photo_list', [])
            license_list = row.get('_license_list', [])
            for i in range(max_photos):
                # Add photo filename column
                photo_column_name = f'Encounter.mediaAsset{i}'
                row[photo_column_name] = photo_list[i] if i < len(photo_list) else None
                # Add license column
                license_column_name = f'Encounter.mediaAsset{i}.license'
                row[license_column_name] = license_list[i] if i < len(license_list) else None
            # Remove temporary fields
            del row['_photo_list']
            del row['_license_list']

        # Build fieldnames with dynamic photo columns
        fieldnames = [
            'observation_id',
            'observed_on',
            'Encounter.year',
            'Encounter.month',
            'Encounter.day',
            'scientific_name',
            'Encounter.genus',
            'Encounter.specificEpithet',
            'common_name',
            'Encounter.decimalLatitude',
            'Encounter.decimalLongitude',
            'Encounter.verbatimLocality',
            'Encounter.locationID',
            'Encounter.livingStatus',
            'Encounter.submitterID',
            'Encounter.state',
            'Sighting.sightingID',
            'observer',
            'quality_grade',
            'url',
            'Encounter.researcherComments',
            'photo_count',
            'photo_filenames'
        ]

        # Add photo asset columns and license columns
        for i in range(max_photos):
            fieldnames.append(f'Encounter.mediaAsset{i}')
            fieldnames.append(f'Encounter.mediaAsset{i}.license')

        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

        print(f"\nCSV file written: {csv_path}")
        print(f"Total observations: {len(data)}")
        if max_photos > 0:
            print(f"Maximum photos per observation: {max_photos}")

    def write_html(self, data: List[Dict[str, Any]], filename: str):
        """
        Write observation data to an interactive HTML review page.

        Args:
            data: List of observation dictionaries
            filename: HTML filename
        """
        if not data:
            print("No data to write to HTML")
            return

        html_path = self.output_dir / filename

        # Determine maximum number of photos across all observations
        max_photos = 0
        for row in data:
            photo_list = row.get('_photo_list', [])
            if len(photo_list) > max_photos:
                max_photos = len(photo_list)

        # Build observation data with image file paths
        observations_json = []
        for row in data:
            photo_list = row.get('_photo_list', [])
            license_list = row.get('_license_list', [])

            # Use file path for first photo preview
            photo_path = None
            if photo_list:
                first_photo_path = self.photos_dir / photo_list[0]
                if first_photo_path.exists():
                    # Create relative path from HTML file to photo
                    photo_path = f"photos/{photo_list[0]}"

            # Build array of all photo paths for gallery
            all_photo_paths = []
            for photo_filename in photo_list:
                photo_file_path = self.photos_dir / photo_filename
                if photo_file_path.exists():
                    all_photo_paths.append(f"photos/{photo_filename}")

            # Get unique licenses for display
            unique_licenses = list(set([lic for lic in license_list if lic]))
            license_display = ', '.join(unique_licenses) if unique_licenses else 'No license'

            # Build observation object
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
                'observer': row.get('observer'),
                'quality_grade': row.get('quality_grade'),
                'url': row.get('url'),
                'researcher_comments': row.get('Encounter.researcherComments'),
                'photo_count': len(photo_list),
                'photo_filenames': '; '.join(photo_list),
                'license_display': license_display,
                'has_non_organism_evidence': row.get('_has_non_organism_evidence', False),
                'is_skulls_and_bones': row.get('_is_skulls_and_bones', False),
                'photo_path': photo_path,
                'all_photo_paths': all_photo_paths,
                'photos': [],
                'licenses': []
            }

            # Add individual photo filenames and licenses
            for i in range(max_photos):
                obs_data['photos'].append(photo_list[i] if i < len(photo_list) else None)
                obs_data['licenses'].append(license_list[i] if i < len(license_list) else None)

            observations_json.append(obs_data)

        # Generate HTML content
        html_content = self._generate_html_template(observations_json, max_photos)

        # Write HTML file
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"\nHTML review page written: {html_path}")
        print(f"Total observations: {len(data)}")
        print(f"Open this file in your web browser to review and select observations.")
        print(f"Maximum photos per observation: {max_photos}")

    def _generate_html_template(self, observations: List[Dict], max_photos: int) -> str:
        """Generate the HTML template with embedded JavaScript."""
        observations_json_str = json.dumps(observations, indent=2)

        # Build filename components for CSV download
        species_part = "_".join([s.replace(" ", "-") for s in self.species_list[:2]])
        place_part = f"_{self.place.replace(' ', '-')}" if self.place else ""
        date_part = datetime.now().strftime("%Y%m%d")

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>iNaturalist Observations Review</title>
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
            background: #2c7a3f;
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
            border-bottom: 3px solid #2c7a3f;
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
            color: #2c7a3f;
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
            background: #2c7a3f;
            color: white;
        }}

        .btn-primary:hover {{
            background: #235c31;
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

        .observations-table tbody tr:hover {{
            background: #f9f9f9;
        }}

        .obs-checkbox {{
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}

        .photo-preview {{
            width: 80px;
            height: 80px;
            object-fit: cover;
            border-radius: 4px;
            cursor: pointer;
            transition: transform 0.2s;
        }}

        .photo-preview:hover {{
            transform: scale(1.1);
        }}

        .no-photo {{
            width: 80px;
            height: 80px;
            background: #e0e0e0;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #999;
            font-size: 12px;
        }}

        .quality-badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}

        .quality-research {{
            background: #d4edda;
            color: #155724;
        }}

        .quality-needs_id {{
            background: #fff3cd;
            color: #856404;
        }}

        .quality-casual {{
            background: #f8d7da;
            color: #721c24;
        }}

        .csv-output {{
            background: #f5f5f5;
            border: 1px solid #ddd;
            border-radius: 5px;
            padding: 20px;
            font-family: "Courier New", monospace;
            font-size: 12px;
            white-space: pre;
            overflow-x: auto;
            max-height: 600px;
            overflow-y: auto;
        }}

        .copy-success {{
            display: none;
            background: #d4edda;
            color: #155724;
            padding: 10px 15px;
            border-radius: 5px;
            margin-bottom: 10px;
        }}

        .copy-success.show {{
            display: block;
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
            align-items: center;
            justify-content: center;
        }}

        .modal.show {{
            display: flex;
        }}

        .modal-gallery {{
            position: relative;
            max-width: 90%;
            max-height: 90%;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}

        .modal-image {{
            max-width: 100%;
            max-height: 80vh;
            object-fit: contain;
        }}

        .modal-close {{
            position: absolute;
            top: 20px;
            right: 30px;
            color: white;
            font-size: 40px;
            font-weight: bold;
            cursor: pointer;
            z-index: 1001;
        }}

        .modal-nav {{
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            font-size: 30px;
            padding: 20px;
            cursor: pointer;
            transition: background 0.2s;
            z-index: 1001;
        }}

        .modal-nav:hover {{
            background: rgba(255,255,255,0.3);
        }}

        .modal-nav-prev {{
            left: 20px;
        }}

        .modal-nav-next {{
            right: 20px;
        }}

        .modal-counter {{
            color: white;
            margin-top: 15px;
            font-size: 16px;
            background: rgba(0,0,0,0.5);
            padding: 8px 16px;
            border-radius: 5px;
        }}

        .modal-thumbnails {{
            display: flex;
            gap: 10px;
            margin-top: 15px;
            overflow-x: auto;
            max-width: 90vw;
            padding: 10px;
        }}

        .modal-thumbnail {{
            width: 60px;
            height: 60px;
            object-fit: cover;
            cursor: pointer;
            border: 2px solid transparent;
            border-radius: 4px;
            transition: border-color 0.2s, transform 0.2s;
        }}

        .modal-thumbnail:hover {{
            transform: scale(1.1);
        }}

        .modal-thumbnail.active {{
            border-color: #2c7a3f;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>iNaturalist Observations Review</h1>
            <p>Review observations and select which ones to include in your export</p>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="switchTab('review')">Review Observations</button>
            <button class="tab" onclick="switchTab('csv')">CSV Export</button>
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
            </div>

            <div class="controls">
                <button class="btn btn-primary" onclick="selectAll()">Select All</button>
                <button class="btn btn-secondary" onclick="deselectAll()">Deselect All</button>
            </div>

            <div class="table-wrapper">
                <table class="observations-table">
                    <thead>
                        <tr>
                            <th>Include</th>
                            <th>Photo</th>
                            <th>ID</th>
                            <th>Date</th>
                            <th>Species</th>
                            <th>Location</th>
                            <th>Observer</th>
                            <th>Quality</th>
                            <th>License</th>
                            <th>Photos</th>
                        </tr>
                    </thead>
                    <tbody id="observations-body">
                    </tbody>
                </table>
            </div>
        </div>

        <div id="csv-tab" class="tab-content">
            <div class="copy-success" id="copy-success">
                CSV content copied to clipboard!
            </div>

            <div class="controls">
                <button class="btn btn-primary" onclick="copyCSV()">Copy CSV to Clipboard</button>
                <button class="btn btn-secondary" onclick="downloadCSV()">Download CSV File</button>
            </div>

            <div class="csv-output" id="csv-output"></div>
        </div>
    </div>

    <div id="photo-modal" class="modal" onclick="closeModal(event)">
        <span class="modal-close" onclick="closeModal(event)">&times;</span>
        <button class="modal-nav modal-nav-prev" onclick="prevImage(event)" id="modal-prev">&lt;</button>
        <button class="modal-nav modal-nav-next" onclick="nextImage(event)" id="modal-next">&gt;</button>
        <div class="modal-gallery" onclick="event.stopPropagation()">
            <img class="modal-image" id="modal-image">
            <div class="modal-counter" id="modal-counter"></div>
            <div class="modal-thumbnails" id="modal-thumbnails"></div>
        </div>
    </div>

    <script>
        // Observation data
        const observations = {observations_json_str};
        const maxPhotos = {max_photos};

        // Filename components for CSV export
        const csvFilename = 'inat_observations_export_{species_part}{place_part}_{date_part}.csv';

        // Initialize
        document.addEventListener('DOMContentLoaded', function() {{
            renderObservations();
            updateCSV();
            updateStats();
        }});

        function renderObservations() {{
            const tbody = document.getElementById('observations-body');
            tbody.innerHTML = '';

            // Sort observations: checked (selected) first, then unchecked
            const sortedObservations = observations.map((obs, index) => ({{ obs, index }}))
                .sort((a, b) => {{
                    const aChecked = a.obs.license_display !== 'No license' &&
                                     !a.obs.has_non_organism_evidence &&
                                     !a.obs.is_skulls_and_bones &&
                                     a.obs.quality_grade !== 'needs_id';
                    const bChecked = b.obs.license_display !== 'No license' &&
                                     !b.obs.has_non_organism_evidence &&
                                     !b.obs.is_skulls_and_bones &&
                                     b.obs.quality_grade !== 'needs_id';

                    // Checked items (true) should come first
                    if (aChecked === bChecked) return 0;
                    return aChecked ? -1 : 1;
                }});

            sortedObservations.forEach(({{obs, index}}) => {{
                const tr = document.createElement('tr');

                // Checkbox
                const tdCheckbox = document.createElement('td');
                const checkbox = document.createElement('input');
                checkbox.type = 'checkbox';
                checkbox.className = 'obs-checkbox';
                // Default to checked only if:
                // 1. Observation has a license, AND
                // 2. Evidence is NOT non-organism (track, scat, molt, etc.), AND
                // 3. Observation is NOT part of "Skulls and Bones" project, AND
                // 4. Quality grade is NOT "needs_id"
                checkbox.checked = obs.license_display !== 'No license' &&
                                   !obs.has_non_organism_evidence &&
                                   !obs.is_skulls_and_bones &&
                                   obs.quality_grade !== 'needs_id';
                checkbox.id = `obs-${{index}}`;
                checkbox.addEventListener('change', handleCheckboxChange);
                tdCheckbox.appendChild(checkbox);
                tr.appendChild(tdCheckbox);

                // Photo preview
                const tdPhoto = document.createElement('td');
                if (obs.photo_path) {{
                    const img = document.createElement('img');
                    img.src = obs.photo_path;
                    img.className = 'photo-preview';
                    img.alt = 'Observation photo';
                    img.onclick = () => openModal(obs.all_photo_paths, 0);
                    tdPhoto.appendChild(img);
                }} else {{
                    const noPhoto = document.createElement('div');
                    noPhoto.className = 'no-photo';
                    noPhoto.textContent = 'No photo';
                    tdPhoto.appendChild(noPhoto);
                }}
                tr.appendChild(tdPhoto);

                // Observation ID
                const tdId = document.createElement('td');
                const link = document.createElement('a');
                link.href = obs.url;
                link.target = '_blank';
                link.textContent = obs.observation_id;
                tdId.appendChild(link);
                tr.appendChild(tdId);

                // Date
                const tdDate = document.createElement('td');
                tdDate.textContent = obs.observed_on || 'Unknown';
                tr.appendChild(tdDate);

                // Species
                const tdSpecies = document.createElement('td');
                const speciesDiv = document.createElement('div');
                const scientificName = document.createElement('div');
                scientificName.style.fontStyle = 'italic';
                scientificName.textContent = obs.scientific_name || 'Unknown';
                speciesDiv.appendChild(scientificName);
                if (obs.common_name) {{
                    const commonName = document.createElement('div');
                    commonName.style.fontSize = '12px';
                    commonName.style.color = '#666';
                    commonName.textContent = obs.common_name;
                    speciesDiv.appendChild(commonName);
                }}
                tdSpecies.appendChild(speciesDiv);
                tr.appendChild(tdSpecies);

                // Location
                const tdLocation = document.createElement('td');
                const locationDiv = document.createElement('div');
                if (obs.location) {{
                    locationDiv.textContent = obs.location;
                }}
                if (obs.latitude && obs.longitude) {{
                    const coords = document.createElement('div');
                    coords.style.fontSize = '11px';
                    coords.style.color = '#999';
                    coords.textContent = `${{obs.latitude}}, ${{obs.longitude}}`;
                    locationDiv.appendChild(coords);
                }}
                tdLocation.appendChild(locationDiv);
                tr.appendChild(tdLocation);

                // Observer
                const tdObserver = document.createElement('td');
                tdObserver.textContent = obs.observer || 'Unknown';
                tr.appendChild(tdObserver);

                // Quality grade
                const tdQuality = document.createElement('td');
                const qualityBadge = document.createElement('span');
                qualityBadge.className = `quality-badge quality-${{obs.quality_grade}}`;
                qualityBadge.textContent = obs.quality_grade || 'unknown';
                tdQuality.appendChild(qualityBadge);
                tr.appendChild(tdQuality);

                // License
                const tdLicense = document.createElement('td');
                tdLicense.textContent = obs.license_display || 'No license';
                tdLicense.style.fontSize = '11px';
                tr.appendChild(tdLicense);

                // Photo count
                const tdPhotoCount = document.createElement('td');
                tdPhotoCount.textContent = obs.photo_count;
                tr.appendChild(tdPhotoCount);

                tbody.appendChild(tr);
            }});
        }}

        function handleCheckboxChange() {{
            updateStats();
            updateCSV();
        }}

        function updateStats() {{
            const total = observations.length;
            const selected = getSelectedObservations().length;

            document.getElementById('total-count').textContent = total;
            document.getElementById('selected-count').textContent = selected;
        }}

        function getSelectedObservations() {{
            const selected = [];
            observations.forEach((obs, index) => {{
                const checkbox = document.getElementById(`obs-${{index}}`);
                if (checkbox && checkbox.checked) {{
                    selected.push(obs);
                }}
            }});
            return selected;
        }}

        function selectAll() {{
            observations.forEach((obs, index) => {{
                const checkbox = document.getElementById(`obs-${{index}}`);
                if (checkbox) checkbox.checked = true;
            }});
            updateStats();
            updateCSV();
        }}

        function deselectAll() {{
            observations.forEach((obs, index) => {{
                const checkbox = document.getElementById(`obs-${{index}}`);
                if (checkbox) checkbox.checked = false;
            }});
            updateStats();
            updateCSV();
        }}

        function updateCSV() {{
            const selected = getSelectedObservations();
            const csv = generateCSV(selected);
            document.getElementById('csv-output').textContent = csv;
        }}

        function generateCSV(data) {{
            if (data.length === 0) {{
                return 'No observations selected';
            }}

            // Build header
            const headers = [
                'observation_id',
                'observed_on',
                'Encounter.year',
                'Encounter.month',
                'Encounter.day',
                'scientific_name',
                'Encounter.genus',
                'Encounter.specificEpithet',
                'common_name',
                'Encounter.decimalLatitude',
                'Encounter.decimalLongitude',
                'Encounter.verbatimLocality',
                'Encounter.locationID',
                'Encounter.livingStatus',
                'Encounter.submitterID',
                'Encounter.state',
                'Sighting.sightingID',
                'observer',
                'quality_grade',
                'url',
                'Encounter.researcherComments',
                'photo_count',
                'photo_filenames'
            ];

            // Add photo asset columns
            for (let i = 0; i < maxPhotos; i++) {{
                headers.push(`Encounter.mediaAsset${{i}}`);
                headers.push(`Encounter.mediaAsset${{i}}.license`);
            }}

            const rows = [headers.join(',')];

            // Add data rows
            data.forEach(obs => {{
                const row = [
                    escapeCSV(obs.observation_id),
                    escapeCSV(obs.observed_on),
                    escapeCSV(obs.year),
                    escapeCSV(obs.month),
                    escapeCSV(obs.day),
                    escapeCSV(obs.scientific_name),
                    escapeCSV(obs.genus),
                    escapeCSV(obs.specific_epithet),
                    escapeCSV(obs.common_name),
                    escapeCSV(obs.latitude),
                    escapeCSV(obs.longitude),
                    escapeCSV(obs.location),
                    escapeCSV(obs.location_id),
                    escapeCSV(obs.living_status),
                    escapeCSV(obs.submitter_id),
                    escapeCSV('unapproved'),  // Encounter.state - always unapproved
                    escapeCSV(obs.sighting_id),
                    escapeCSV(obs.observer),
                    escapeCSV(obs.quality_grade),
                    escapeCSV(obs.url),
                    escapeCSV(obs.researcher_comments),
                    escapeCSV(obs.photo_count),
                    escapeCSV(obs.photo_filenames)
                ];

                // Add photo assets and licenses
                for (let i = 0; i < maxPhotos; i++) {{
                    row.push(escapeCSV(obs.photos[i]));
                    row.push(escapeCSV(obs.licenses[i]));
                }}

                rows.push(row.join(','));
            }});

            return rows.join('\\n');
        }}

        function escapeCSV(value) {{
            if (value === null || value === undefined) {{
                return '';
            }}
            const str = String(value);
            if (str.includes(',') || str.includes('"') || str.includes('\\n')) {{
                return '"' + str.replace(/"/g, '""') + '"';
            }}
            return str;
        }}

        function copyCSV() {{
            const csv = document.getElementById('csv-output').textContent;
            navigator.clipboard.writeText(csv).then(() => {{
                const success = document.getElementById('copy-success');
                success.classList.add('show');
                setTimeout(() => {{
                    success.classList.remove('show');
                }}, 3000);
            }});
        }}

        function downloadCSV() {{
            const csv = document.getElementById('csv-output').textContent;
            const blob = new Blob([csv], {{ type: 'text/csv' }});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = csvFilename;
            a.click();
            URL.revokeObjectURL(url);
        }}

        function switchTab(tabName) {{
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(tab => {{
                tab.classList.remove('active');
            }});
            event.target.classList.add('active');

            // Update tab content
            document.querySelectorAll('.tab-content').forEach(content => {{
                content.classList.remove('active');
            }});
            document.getElementById(tabName + '-tab').classList.add('active');
        }}

        // Gallery state
        let currentGallery = [];
        let currentImageIndex = 0;

        function openModal(imagePaths, startIndex = 0) {{
            if (!imagePaths || imagePaths.length === 0) return;

            currentGallery = imagePaths;
            currentImageIndex = startIndex;

            const modal = document.getElementById('photo-modal');
            modal.classList.add('show');

            updateModalImage();
            renderThumbnails();
            updateNavButtons();
        }}

        function closeModal(event) {{
            if (event) event.stopPropagation();
            document.getElementById('photo-modal').classList.remove('show');
            currentGallery = [];
            currentImageIndex = 0;
        }}

        function nextImage(event) {{
            event.stopPropagation();
            if (currentImageIndex < currentGallery.length - 1) {{
                currentImageIndex++;
                updateModalImage();
                updateNavButtons();
            }}
        }}

        function prevImage(event) {{
            event.stopPropagation();
            if (currentImageIndex > 0) {{
                currentImageIndex--;
                updateModalImage();
                updateNavButtons();
            }}
        }}

        function goToImage(index, event) {{
            event.stopPropagation();
            currentImageIndex = index;
            updateModalImage();
            updateNavButtons();
        }}

        function updateModalImage() {{
            const modalImg = document.getElementById('modal-image');
            const counter = document.getElementById('modal-counter');

            modalImg.src = currentGallery[currentImageIndex];
            counter.textContent = `${{currentImageIndex + 1}} / ${{currentGallery.length}}`;

            // Update active thumbnail
            document.querySelectorAll('.modal-thumbnail').forEach((thumb, idx) => {{
                if (idx === currentImageIndex) {{
                    thumb.classList.add('active');
                }} else {{
                    thumb.classList.remove('active');
                }}
            }});
        }}

        function renderThumbnails() {{
            const container = document.getElementById('modal-thumbnails');
            container.innerHTML = '';

            currentGallery.forEach((imgPath, index) => {{
                const thumb = document.createElement('img');
                thumb.src = imgPath;
                thumb.className = 'modal-thumbnail';
                if (index === currentImageIndex) {{
                    thumb.classList.add('active');
                }}
                thumb.onclick = (e) => goToImage(index, e);
                container.appendChild(thumb);
            }});
        }}

        function updateNavButtons() {{
            const prevBtn = document.getElementById('modal-prev');
            const nextBtn = document.getElementById('modal-next');

            // Hide buttons if only one image
            if (currentGallery.length <= 1) {{
                prevBtn.style.display = 'none';
                nextBtn.style.display = 'none';
            }} else {{
                prevBtn.style.display = 'block';
                nextBtn.style.display = 'block';

                // Disable prev button on first image
                prevBtn.style.opacity = currentImageIndex === 0 ? '0.3' : '1';
                prevBtn.style.cursor = currentImageIndex === 0 ? 'default' : 'pointer';

                // Disable next button on last image
                nextBtn.style.opacity = currentImageIndex === currentGallery.length - 1 ? '0.3' : '1';
                nextBtn.style.cursor = currentImageIndex === currentGallery.length - 1 ? 'default' : 'pointer';
            }}
        }}

        // Keyboard navigation
        document.addEventListener('keydown', function(event) {{
            const modal = document.getElementById('photo-modal');
            if (modal.classList.contains('show')) {{
                if (event.key === 'ArrowLeft') {{
                    prevImage(event);
                }} else if (event.key === 'ArrowRight') {{
                    nextImage(event);
                }} else if (event.key === 'Escape') {{
                    closeModal(event);
                }}
            }}
        }});
    </script>
</body>
</html>
'''

    def run(self):
        """Main execution method."""
        print("=" * 60)
        print("iNaturalist Species Observations Downloader")
        print("=" * 60)
        print(f"Output directory: {self.output_dir}")
        print(f"Date range: Last {self.days_back} days")
        print(f"Species: {', '.join(self.species_list)}")
        if self.place:
            print(f"Place filter: {self.place}")
        print(f"API rate limit: {self.rate_limit} seconds between calls")
        print("=" * 60)
        print()

        # Resolve place if specified
        if self.place:
            self.place_id = self.resolve_place(self.place)
            if self.place_id is None:
                print("\nError: Could not resolve place. Exiting.")
                sys.exit(1)
            print()

        all_observations_data = []

        for species_name in self.species_list:
            print(f"\nProcessing species: {species_name}")
            print("-" * 60)

            # Get taxon ID
            taxon_id = self.search_species(species_name)

            if taxon_id is None:
                continue

            # Get observations
            observations = self.get_observations(taxon_id)

            if not observations:
                print(f"  No observations found for {species_name}")
                continue

            # Process and download
            processed_data = self.process_observations(observations, species_name)
            all_observations_data.extend(processed_data)

        # Write to CSV or HTML
        if all_observations_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Build filename components
            species_part = "_".join([s.replace(" ", "-") for s in self.species_list[:2]])  # Use first 2 species
            place_part = f"_{self.place.replace(' ', '-')}" if self.place else ""

            if self.html_review:
                html_filename = f"inat_observations_review_{species_part}{place_part}_{timestamp}.html"
                self.write_html(all_observations_data, html_filename)
            else:
                csv_filename = f"inat_observations_{species_part}{place_part}_{timestamp}.csv"
                self.write_csv(all_observations_data, csv_filename)

            print("\n" + "=" * 60)
            print("Download complete!")
            print(f"Photos saved to: {self.photos_dir}")
            print("=" * 60)
        else:
            print("\nNo observations found for any species.")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description='Download recent iNaturalist observations for specified species.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download last 30 days of leafy and weedy seadragon observations
  %(prog)s --species "Phycodurus eques" "Phyllopteryx taeniolatus" --days 30 --output ./seadragon_data

  # Filter observations to California only
  %(prog)s --species "leafy seadragon" --days 60 --place "California" --output ./data

  # Generate interactive HTML review page for manual observation selection
  %(prog)s --species "leafy seadragon" --days 7 --html-review --output ./data

  # Filter by place and use HTML review mode
  %(prog)s --species "leafy seadragon" --days 60 --place "Oregon" --html-review --output ./data

  # Download last 7 days of leafy seadragons with 2 second rate limit
  %(prog)s --species "leafy seadragon" --days 7 --rate-limit 2.0 --output ./data

  # Use faster rate limit (0.5 seconds) - use with caution
  %(prog)s --species "weedy seadragon" --days 14 --rate-limit 0.5 --output ./data
        """
    )

    parser.add_argument(
        '--species',
        nargs='+',
        required=True,
        help='List of species names (common or scientific names)'
    )

    parser.add_argument(
        '--days',
        type=int,
        default=30,
        help='Number of days back to search for observations (default: 30)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='./inat_data',
        help='Output directory for CSV and photos (default: ./inat_data)'
    )

    parser.add_argument(
        '--rate-limit',
        type=float,
        default=1.0,
        help='Seconds to wait between iNaturalist API calls (default: 1.0)'
    )

    parser.add_argument(
        '--html-review',
        action='store_true',
        help='Generate interactive HTML review page instead of CSV (allows manual selection of observations)'
    )

    parser.add_argument(
        '--place',
        type=str,
        default=None,
        help='Filter observations by place (e.g., "California", "Oregon", "United States")'
    )

    parser.add_argument(
        '--use-locationID',
        type=str,
        default=None,
        help='Location ID to add to Encounter.locationID column for all observations'
    )

    parser.add_argument(
        '--use-submitterID',
        type=str,
        default=None,
        help='Submitter ID to add to Encounter.submitterID column for all observations'
    )

    parser.add_argument(
        '--social-split-observations',
        action='store_true',
        help='Split multi-photo observations into separate rows (one per photo) with shared Sighting.sightingID for social species'
    )

    args = parser.parse_args()

    # Validate inputs
    if args.days < 1:
        print("Error: --days must be at least 1")
        sys.exit(1)

    if args.rate_limit < 0:
        print("Error: --rate-limit must be non-negative")
        sys.exit(1)

    # Create downloader and run
    downloader = iNaturalistDownloader(
        output_dir=args.output,
        days_back=args.days,
        species_list=args.species,
        rate_limit=args.rate_limit,
        html_review=args.html_review,
        place=args.place,
        location_id=args.use_locationID,
        submitter_id=args.use_submitterID,
        social_split=args.social_split_observations
    )

    try:
        downloader.run()
    except KeyboardInterrupt:
        print("\n\nDownload interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
