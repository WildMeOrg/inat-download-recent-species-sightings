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


class iNaturalistDownloader:
    """Downloads observations and photos from iNaturalist API."""

    BASE_URL = "https://api.inaturalist.org/v1"

    def __init__(self, output_dir: str, days_back: int, species_list: List[str], rate_limit: float = 1.0):
        """
        Initialize the downloader.

        Args:
            output_dir: Directory to save CSV and photos
            days_back: Number of days back to search for observations
            species_list: List of species names to search for
            rate_limit: Seconds to wait between API calls (default: 1.0)
        """
        self.output_dir = Path(output_dir)
        self.days_back = days_back
        self.species_list = species_list
        self.rate_limit = rate_limit
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
            params = urllib.parse.urlencode({
                'taxon_id': taxon_id,
                'd1': start_date,
                'd2': end_date,
                'has[]': 'photos',
                'quality_grade': 'any',
                'per_page': per_page,
                'page': page,
                'order_by': 'observed_on'
            })

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

            # Download photos
            photos = obs.get('photos', [])
            photo_filenames = []

            if photos:
                print(f"  Processing observation {idx}/{len(observations)} (ID: {obs_id}, {len(photos)} photos)...")

                for photo_idx, photo in enumerate(photos, 1):
                    # Use original or large size
                    photo_url = photo.get('url', '').replace('square', 'original')

                    # Create unique filename
                    photo_ext = photo_url.split('.')[-1].split('?')[0]
                    if '/' in photo_ext or len(photo_ext) > 4:
                        photo_ext = 'jpg'

                    photo_filename = f"{obs_id}_{photo_idx}.{photo_ext}"

                    if self.download_photo(photo_url, photo_filename):
                        photo_filenames.append(photo_filename)

            # Create row for CSV
            row = {
                'observation_id': obs_id,
                'observed_on': observed_on,
                'scientific_name': scientific_name,
                'common_name': common_name,
                'latitude': latitude,
                'longitude': longitude,
                'place_name': place_guess,
                'observer': observer,
                'quality_grade': quality_grade,
                'url': obs_url,
                'photo_count': len(photo_filenames),
                'photo_filenames': '; '.join(photo_filenames)
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

        fieldnames = [
            'observation_id',
            'observed_on',
            'scientific_name',
            'common_name',
            'latitude',
            'longitude',
            'place_name',
            'observer',
            'quality_grade',
            'url',
            'photo_count',
            'photo_filenames'
        ]

        with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)

        print(f"\nCSV file written: {csv_path}")
        print(f"Total observations: {len(data)}")

    def run(self):
        """Main execution method."""
        print("=" * 60)
        print("iNaturalist Species Observations Downloader")
        print("=" * 60)
        print(f"Output directory: {self.output_dir}")
        print(f"Date range: Last {self.days_back} days")
        print(f"Species: {', '.join(self.species_list)}")
        print(f"API rate limit: {self.rate_limit} seconds between calls")
        print("=" * 60)
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

        # Write to CSV
        if all_observations_data:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_filename = f"inat_observations_{timestamp}.csv"
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
        rate_limit=args.rate_limit
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
