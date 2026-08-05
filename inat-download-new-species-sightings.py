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
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any
import shutil
import urllib.error
import urllib.request
import urllib.parse
import json
import time
import uuid


# Without an explicit timeout urllib blocks forever on a server that accepts the
# connection and then goes quiet.
HTTP_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
MAX_RETRIES = 3

# A cell a spreadsheet would evaluate rather than display. Two details keep this
# byte-for-byte equivalent to the JavaScript copies rather than merely similar:
#   re.ASCII -- Python's \d matches every Unicode decimal digit and JavaScript's
#     matches 0-9, so without it "-٣" is a number here and a formula there.
#   \Z rather than $ -- Python's $ also matches just before a trailing newline
#     and JavaScript's (unflagged) $ does not, so "-16.5\n" would be left alone
#     here and prefixed there.
_FORMULA_LEAD_CHARS = ('=', '+', '-', '@', '\t', '\r')
_PLAIN_NUMBER_RE = re.compile(r'^-?\d*\.?\d+\Z', re.ASCII)


def neutralize_formula(value: Any) -> Any:
    r"""
    Prefix an apostrophe to a value a spreadsheet would treat as a formula.

    iNaturalist free text (place_guess, common names, user logins) reaches the
    Wildbook CSV verbatim, and a locality beginning "=" or "-" or "@" becomes a
    live formula the moment someone opens the file in Excel or Sheets.

    Genuine negative numbers -- every southern latitude, every western longitude
    -- are left alone, so this must test for a leading formula character AND for
    the value not being a plain number.

    FIVE COPIES OF THIS RULE EXIST and must stay identical, or the same
    observation exports differently depending on which button the reviewer
    pressed (measured once: `-Somewhere odd` from the direct CSV against
    `'-Somewhere odd` from the review page):
      1. here (:40), for this module's write_csv
      2. neutralize_formula() in inat-mcp-server/flickr_tools.py:50 -- a separate
         copy on purpose: the MCP server must not import this hyphenated
         top-level script, and this script must not depend on the server package
      3. escapeCSV() in this module's generated review page (:2113)
      4. the escape() closure in flickr_tools' generated review page (:1196)
      5. the escape() closure in youtube_tools' generated CSV export (:1394)

    Copies 3-5 are ANONYMOUS closures, so no identifier finds them and grepping
    for a function name silently under-reports (this census said "four" until a
    reviewer counted). Audit all five with:

        grep -rn "_FORMULA_LEAD_CHARS = \|\[=+" \
            inat-download-new-species-sightings.py \
            inat-mcp-server/flickr_tools.py inat-mcp-server/youtube_tools.py

    Expect SEVEN hits: the five copies plus this same command quoted in the two
    Python docstrings. The line numbers listed above are indicative and drift;
    the grep is the authoritative census.

    Args:
        value: Any CSV cell value

    Returns:
        The value unchanged, or a string with a leading apostrophe. Non-strings
        that need no guard come back untouched, so benign output is byte-for-byte
        what it was before this guard existed.
    """
    if value is None:
        return value
    text = str(value)
    if text[:1] in _FORMULA_LEAD_CHARS and not _PLAIN_NUMBER_RE.match(text):
        return "'" + text
    return value


def fetch_json(url: str, rate_limit: float = 1.0, timeout: int = HTTP_TIMEOUT,
               max_retries: int = MAX_RETRIES) -> Dict[str, Any]:
    """
    GET a JSON document, retrying transient failures with exponential backoff.

    Args:
        url: Fully-formed request URL
        rate_limit: Seconds to pause after a successful request
        timeout: Per-request socket timeout in seconds
        max_retries: Total attempts before giving up

    Returns:
        The decoded JSON body

    Raises:
        RuntimeError: If every attempt failed
    """
    last_error = None
    attempts = 0

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                payload = json.loads(response.read().decode())
            time.sleep(rate_limit)
            return payload
        except urllib.error.HTTPError as e:
            last_error = e
            # 4xx other than rate-limiting will not improve on retry.
            if e.code != 429 and e.code < 500:
                break
        except Exception as e:
            last_error = e

        if attempt < max_retries:
            backoff = rate_limit * (2 ** attempt)
            print(f"    Request failed ({last_error}); retrying in {backoff:.1f}s "
                  f"(attempt {attempt + 1}/{max_retries})")
            time.sleep(backoff)

    plural = '' if attempts == 1 else 's'
    raise RuntimeError(
        f"Request failed after {attempts} attempt{plural}: {url} ({last_error})"
    )


def split_rows_by_photo(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Expand each split-eligible row into one row per photo.

    Rows sharing an observation become one Wildbook Sighting: they all carry the
    observation's pre-generated _sighting_id in Sighting.sightingID.

    This is only ever called when social_split is on, so *every* row it returns
    gets a promoted sighting ID -- not just the ones that actually split. A lone
    encounter (single photo, or organism-evidence so splitting is suppressed)
    previously produced a one-encounter Sighting in Wildbook, and it must keep
    doing so rather than silently losing its Sighting.sightingID just because it
    had nothing to split.

    This runs *after* deduplication, which is deliberate. When splitting happened
    inside process_observations(), deduplicate_rows() saw the split rows and
    collapsed them back to one -- silently turning --social-split-observations
    into a no-op. Keeping the split downstream makes that impossible.

    Args:
        rows: Processed observation rows, one per observation

    Returns:
        A new list of new row dicts; neither the input rows nor their contents
        (e.g. _photo_list) are modified.
    """
    expanded = []

    for row in rows:
        photo_list = row.get('_photo_list', [])
        license_list = row.get('_license_list', [])

        if not row.get('_split_eligible') or len(photo_list) <= 1:
            passthrough_row = dict(row)
            passthrough_row['Sighting.sightingID'] = row['_sighting_id']
            expanded.append(passthrough_row)
            continue

        for photo_index, photo_filename in enumerate(photo_list):
            split_row = dict(row)
            split_row['Sighting.sightingID'] = row['_sighting_id']
            split_row['photo_count'] = 1
            split_row['photo_filenames'] = photo_filename
            split_row['_photo_list'] = [photo_filename]
            split_row['_license_list'] = (
                [license_list[photo_index]] if photo_index < len(license_list) else []
            )
            expanded.append(split_row)

    return expanded


class iNaturalistDownloader:
    """Downloads observations and photos from iNaturalist API."""

    BASE_URL = "https://api.inaturalist.org/v1"

    def __init__(self, output_dir: str, days_back: int, species_list: List[str], rate_limit: float = 1.0, html_review: bool = False, place: str = None, location_id: str = None, submitter_id: str = None, social_split: bool = False, project_owner: str = None, start_date: str = None, end_date: str = None):
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
            project_owner: Optional Wildbook username to own the project (required for new projects)
            start_date: Optional explicit window start, YYYY-MM-DD (overrides days_back)
            end_date: Optional explicit window end, YYYY-MM-DD (defaults to today)
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
        self.project_owner = project_owner
        # Validate here rather than at first use: a malformed date otherwise
        # surfaces as an empty result set after a long download.
        self.start_date = self._parse_date(start_date, '--start-date')
        self.end_date = self._parse_date(end_date, '--end-date')
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError(
                f"--start-date ({start_date}) is after --end-date ({end_date}); "
                f"iNaturalist would return nothing for that window"
            )
        self.photos_dir = self.output_dir / "photos"

        # Create directories if they don't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.photos_dir.mkdir(parents=True, exist_ok=True)

    def _get_json(self, url: str) -> Dict[str, Any]:
        """GET a JSON document using this downloader's rate limit."""
        return fetch_json(url, rate_limit=self.rate_limit)

    @staticmethod
    def _parse_date(value: str, flag: str) -> datetime:
        """
        Parse a YYYY-MM-DD command-line date, or None when not supplied.

        Args:
            value: The raw string, or None
            flag: The flag name, for the error message

        Returns:
            A datetime, or None

        Raises:
            ValueError: If the value is not a valid YYYY-MM-DD date
        """
        if value is None:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise ValueError(
                f"{flag} must be a date in YYYY-MM-DD form, got {value!r}"
            )

    def get_date_range(self) -> tuple:
        """
        Calculate the date range for the search.

        Explicit --start-date / --end-date win over --days, which can only ever
        express a window ending today and so cannot describe a closed historical
        range. The values map straight onto iNaturalist's d1/d2, which are
        inclusive whole dates -- so a request for 00:00 on the start day through
        23:59 on the end day is exactly this window.

        Returns:
            (start, end) as YYYY-MM-DD strings
        """
        end_date = self.end_date or datetime.now()
        if self.start_date:
            start_date = self.start_date
        else:
            # An --end-date without a --start-date still spans days_back before
            # it, rather than silently widening to every observation ever.
            start_date = end_date - timedelta(days=self.days_back)
        return start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")

    def generate_project_name(self, genus: str, specific_epithet: str) -> str:
        """
        Generate a Wildbook project name in the format: iNaturalist-genus-specificEpithet

        Args:
            genus: The genus name (e.g., "Panthera")
            specific_epithet: The specific epithet (e.g., "leo")

        Returns:
            Project name in lowercase format (e.g., "iNaturalist-panthera-leo")
        """
        if genus and specific_epithet:
            return f"iNaturalist-{genus.lower()}-{specific_epithet.lower()}"
        elif genus:
            return f"iNaturalist-{genus.lower()}"
        else:
            return "iNaturalist-unknown"

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
            data = self._get_json(url)

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
            data = self._get_json(url)

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
                'captive': 'false',  # Only wild organisms, exclude captive/cultivated
                'per_page': per_page,
                'page': page,
                'order_by': 'observed_on'
            }

            # Add place_id if it was specified
            if self.place_id is not None:
                params_dict['place_id'] = self.place_id

            params = urllib.parse.urlencode(params_dict)

            url = f"{self.BASE_URL}/observations?{params}"

            data = self._get_json(url)

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

        print(f"  Total observations found: {len(all_observations)}")
        return all_observations

    def download_photo(self, url: str, filename: str) -> bool:
        """
        Download a photo from URL to the photos directory.

        Retries transient failures the same way fetch_json does. A photo lost to
        a one-off network blip is not cosmetic: the row's photo list comes out
        short, and a second pass over the same observation (two species names
        resolving to one taxon) then disagrees with the first about which media
        the observation has. deduplicate_rows survives that by construction, but
        the cheapest fix is not to drop the photo in the first place.

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

        # Download to a sibling .part file and rename on success, so an
        # interrupted transfer is not cached as a complete photo.
        partial = filepath.with_name(filepath.name + '.part')
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response, \
                        open(partial, 'wb') as out:
                    shutil.copyfileobj(response, out)
                partial.replace(filepath)
                return True
            except urllib.error.HTTPError as e:
                last_error = e
                partial.unlink(missing_ok=True)
                # 4xx other than rate-limiting will not improve on retry.
                if e.code != 429 and e.code < 500:
                    break
            except Exception as e:
                last_error = e
                partial.unlink(missing_ok=True)

            if attempt < MAX_RETRIES:
                backoff = self.rate_limit * (2 ** attempt)
                print(f"      Photo download failed ({last_error}); retrying in "
                      f"{backoff:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})")
                time.sleep(backoff)

        print(f"      Error downloading photo {filename}: {last_error}")
        return False

    def extract_gif_frames(self, gif_path: Path) -> List[str]:
        """
        Extract all frames from an animated GIF and save as JPEGs.

        Args:
            gif_path: Path to the GIF file

        Returns:
            List of JPEG filenames that were created (without directory path)
        """
        try:
            from PIL import Image
        except ImportError:
            print("      Warning: PIL/Pillow not installed. Cannot convert animated GIFs.")
            print("      Install with: pip3 install Pillow")
            return []

        try:
            img = Image.open(gif_path)

            # Check if it's animated (has multiple frames)
            frame_count = getattr(img, 'n_frames', 1)

            if frame_count <= 1:
                # Not animated, no need to extract frames
                img.close()
                return []

            print(f"      Detected animated GIF with {frame_count} frames, extracting...")

            # Base filename (without extension)
            base_name = gif_path.stem  # e.g., "12345_1"

            extracted_filenames = []

            # Extract each frame
            for frame_idx in range(frame_count):
                img.seek(frame_idx)

                # Convert to RGB (GIFs can be in palette mode or have transparency)
                rgb_frame = img.convert('RGB')

                # Create filename for this frame: 12345_1_frame0.jpg, 12345_1_frame1.jpg, etc.
                frame_filename = f"{base_name}_frame{frame_idx}.jpg"
                frame_path = self.photos_dir / frame_filename

                # Save as JPEG with high quality
                rgb_frame.save(frame_path, 'JPEG', quality=90)
                extracted_filenames.append(frame_filename)

            print(f"      Extracted {len(extracted_filenames)} frames from GIF")

            # Close the image before deleting (important on Windows to release file lock)
            img.close()

            # Delete the original GIF after successful extraction
            gif_path.unlink()
            print(f"      Deleted original GIF: {gif_path.name}")

            return extracted_filenames

        except Exception as e:
            print(f"      Error extracting frames from GIF {gif_path.name}: {e}")
            # Make sure to close the image if there was an error
            try:
                img.close()
            except:
                pass
            return []

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

            # Geoprivacy - check if coordinates are obscured
            obscured = obs.get('obscured', False)
            geoprivacy = obs.get('geoprivacy')  # User-set: None/open, obscured, private
            taxon_geoprivacy = obs.get('taxon_geoprivacy')  # Auto: open, obscured
            public_positional_accuracy = obs.get('public_positional_accuracy')  # Accuracy in meters (inflated if obscured)

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
            # iNaturalist "Evidence of Presence" == "Organism". NOTE: this says
            # the evidence is the animal itself, NOT that only one individual is
            # pictured; iNaturalist has no single-subject annotation. Splitting
            # is currently suppressed for these, which is almost certainly too
            # broad -- see README for the open question.
            has_organism_evidence = False
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
                            # controlled_value_id 24 = "Organism"
                            if controlled_value_id == 24:
                                has_organism_evidence = True
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
            # True once one iNaturalist photo has become several files, which
            # only happens for an animated GIF. See _split_eligible below.
            gif_frames_extracted = False

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
                        # Check if the downloaded file is a GIF and extract frames if animated
                        photo_path = self.photos_dir / photo_filename
                        if photo_path.suffix.lower() == '.gif':
                            extracted_frames = self.extract_gif_frames(photo_path)
                            if extracted_frames:
                                # Add all extracted frames to the list (GIF was deleted)
                                gif_frames_extracted = True
                                for frame_filename in extracted_frames:
                                    photo_filenames.append(frame_filename)
                                    photo_licenses.append(license_code)
                            else:
                                # Not animated or extraction failed, keep original
                                photo_filenames.append(photo_filename)
                                photo_licenses.append(license_code)
                        else:
                            # Not a GIF, add normally
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

            # Generate project name based on species taxonomy
            project_name = self.generate_project_name(encounter_genus, encounter_specific_epithet)

            # Every observation gets a sighting ID, but it stays internal until a
            # split actually needs it -- either split_rows_by_photo() on the CSV
            # path, or the reviewer's Split button on the HTML path. Promoting it
            # unconditionally would populate a column that is empty today.
            sighting_id = None
            # An animated GIF is ONE iNaturalist photo that extract_gif_frames
            # turned into N JPEG files. Splitting counts files, so a 30-frame GIF
            # would become 30 Encounters of the same animal in the same second --
            # 29 guaranteed self-matches for Wildbook's ID pipeline. Splitting is
            # therefore refused for the whole observation: the spec (decision 1,
            # and the export table) fixes a split row at exactly one media asset,
            # so a frame group cannot be one row, and the fallback -- one
            # Encounter carrying every frame, exactly as today's default mode
            # exports it -- is the conservative answer.
            split_eligible = (
                self.social_split
                and len(photo_filenames) > 1
                and not has_organism_evidence
                and not gif_frames_extracted
            )

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
                'Encounter.submitterID': self.submitter_id if self.submitter_id else 'public',
                'Encounter.state': 'unapproved',
                'Encounter.project0.researchProjectName': project_name,
                'Encounter.project0.ownerUsername': self.project_owner if self.project_owner else None,
                'observer': observer,
                'quality_grade': quality_grade,
                'url': obs_url,
                'Encounter.otherCatalogNumbers': f'iNaturalist:{obs_id}',
                'Encounter.researcherComments': researcher_comments,
                'Sighting.sightingID': sighting_id,
                'photo_count': len(photo_filenames),
                'photo_filenames': '; '.join(photo_filenames),
                '_photo_list': photo_filenames,  # Temporary field for photo processing
                '_license_list': photo_licenses,  # Temporary field for license processing
                '_has_non_organism_evidence': has_non_organism_evidence,  # For HTML deselection
                '_is_skulls_and_bones': is_skulls_and_bones,  # For HTML deselection
                '_coordinates_obscured': obscured,  # For HTML display
                '_geoprivacy': geoprivacy,  # User-set geoprivacy
                '_taxon_geoprivacy': taxon_geoprivacy,  # Auto geoprivacy from conservation status
                '_public_positional_accuracy': public_positional_accuracy,  # Accuracy in meters
                '_sighting_id': str(uuid.uuid4()),  # Promoted to the column only when split
                '_split_eligible': split_eligible,  # Whether the flag would split this one
                '_gif_frames_extracted': gif_frames_extracted,  # Files outnumber source photos
            }
            processed_data.append(row)

        return processed_data

    def deduplicate_rows(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Keep exactly one row per observation.

        Several species names can resolve to one taxon, so the same observation
        can be processed more than once. The key is observation_id ALONE, and it
        has to stay that way: splitting now runs strictly after deduplication
        (see split_rows_by_photo and run()), so every row reaching here describes
        a whole observation and two rows sharing an ID are always duplicates.

        A composite (observation_id, photos) key used to be needed when
        process_observations did the splitting itself. It is now strictly weaker
        than the ID alone: the two passes over one observation need not agree on
        the photo list -- a transient download failure in the first pass is
        enough -- and both rows would then survive, giving Wildbook two
        Encounters carrying the same Encounter.otherCatalogNumbers and the same
        media. Identical media in two Encounters self-match, fabricating a
        resight of one animal at one instant.

        On collision the row with the most photos wins, so a pass that lost a
        photo to a failed download cannot displace a complete one.

        Args:
            data: Processed observation rows, one per observation

        Returns:
            The rows in their original order, with duplicates removed
        """
        unique_rows = {}
        for row in data:
            key = row.get('observation_id')
            previous = unique_rows.get(key)
            if previous is None or (
                len(row.get('_photo_list', [])) > len(previous.get('_photo_list', []))
            ):
                unique_rows[key] = row
        return list(unique_rows.values())

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

        # Build the export rows as copies. Callers may export the same data
        # more than once (CSV then HTML), so the input rows keep their
        # underscore-prefixed internal fields.
        export_rows = []
        for row in data:
            photo_list = row.get('_photo_list', [])
            license_list = row.get('_license_list', [])
            export_row = {k: v for k, v in row.items() if not k.startswith('_')}
            for i in range(max_photos):
                export_row[f'Encounter.mediaAsset{i}'] = (
                    photo_list[i] if i < len(photo_list) else None
                )
                export_row[f'Encounter.mediaAsset{i}.license'] = (
                    license_list[i] if i < len(license_list) else None
                )
            # Applied to every cell, exactly as the review page's escapeCSV()
            # does, so the two export paths cannot disagree about any field.
            export_rows.append(
                {k: neutralize_formula(v) for k, v in export_row.items()}
            )

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
            'Encounter.project0.researchProjectName',
            'Encounter.project0.ownerUsername',
            'Sighting.sightingID',
            'observer',
            'quality_grade',
            'url',
            'Encounter.otherCatalogNumbers',
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
            writer.writerows(export_rows)

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

            # Displayable path per photo, or None when the download failed.
            #
            # INVARIANT: len(all_photo_paths) == len(photo_list). A missing file
            # MUST become None rather than be dropped: a split row previews
            # all_photo_paths[i] and exports photos[i], so compacting this list
            # would shift every later row's preview and show the reviewer a
            # different photo from the one they are deciding about. The gallery
            # skips the Nones instead (see galleryFor() in the page).
            #
            # Note this list is sized to photo_list, NOT padded to max_photos the
            # way photos / licenses / photo_licensed are, and that asymmetry is
            # deliberate rather than an oversight. Those three are padded to a
            # common length because they are index-paired with each other and
            # read by index (photos[i] / licenses[i] / photo_licensed[i] must
            # describe the same photo i); a short array would silently misalign
            # which photo is considered licensed. Nothing walks all_photo_paths
            # that way: it is only ever indexed by a photoIndex already known to
            # be < photo_count, so padding it would add slots no code path can
            # reach. Index alignment with photo_list is the invariant that
            # matters; equal length with photos is not.
            all_photo_paths = [
                f"photos/{photo_filename}"
                if (self.photos_dir / photo_filename).exists() else None
                for photo_filename in photo_list
            ]
            assert len(all_photo_paths) == len(photo_list)

            # Get unique licenses for display
            unique_licenses = list(set([lic for lic in license_list if lic]))
            license_display = ', '.join(unique_licenses) if unique_licenses else 'No license'

            # Only default-select a row when *every* photo it would export
            # carries a license. One licensed photo used to be enough, which
            # quietly shipped all-rights-reserved media alongside it.
            all_media_licensed = bool(photo_list) and all(
                license_list[i] if i < len(license_list) else None
                for i in range(len(photo_list))
            )

            # Per-photo licence flags. A split row only exports its own photo, so
            # it can be selected on that photo's licence alone -- which lets
            # splitting rescue the licensed photos from an observation that is
            # deselected wholesale under the all-or-nothing rule.
            photo_licensed = [
                bool(license_list[i]) if i < len(license_list) else False
                for i in range(len(photo_list))
            ]
            photo_licensed += [False] * (max_photos - len(photo_licensed))

            # Whether the reviewer may split this observation at all. Kept in
            # Python with the rest of the media/biology rules -- the browser only
            # holds state. More than one file is not sufficient: an animated GIF
            # is one photo whose frames were extracted to N files, and splitting
            # those would emit N Encounters of one animal in one instant (see
            # _split_eligible in process_observations).
            #
            # can_split False must imply initially_split False, or isSplit()
            # would start a row split that no button can undo, so derive one from
            # the other rather than restating the condition.
            can_split = len(photo_list) > 1 and not row.get('_gif_frames_extracted', False)

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
                'project_name': row.get('Encounter.project0.researchProjectName'),
                'project_owner': row.get('Encounter.project0.ownerUsername'),
                'sighting_id': row.get('_sighting_id'),
                'can_split': can_split,
                'initially_split': bool(row.get('_split_eligible')) and can_split,
                'photo_licensed': photo_licensed,
                'observer': row.get('observer'),
                'quality_grade': row.get('quality_grade'),
                'url': row.get('url'),
                'other_catalog_numbers': row.get('Encounter.otherCatalogNumbers'),
                'researcher_comments': row.get('Encounter.researcherComments'),
                'photo_count': len(photo_list),
                'photo_filenames': '; '.join(photo_list),
                'license_display': license_display,
                'all_media_licensed': all_media_licensed,
                'has_non_organism_evidence': row.get('_has_non_organism_evidence', False),
                'is_skulls_and_bones': row.get('_is_skulls_and_bones', False),
                'coordinates_obscured': row.get('_coordinates_obscured', False),
                'geoprivacy': row.get('_geoprivacy'),
                'taxon_geoprivacy': row.get('_taxon_geoprivacy'),
                'public_positional_accuracy': row.get('_public_positional_accuracy'),
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
        html_content = self._generate_html_template(observations_json, max_photos, self.social_split)

        # Write HTML file
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        print(f"\nHTML review page written: {html_path}")
        print(f"Total observations: {len(data)}")
        print(f"Open this file in your web browser to review and select observations.")
        print(f"Maximum photos per observation: {max_photos}")

    @staticmethod
    def _json_for_script_block(payload: Any) -> str:
        """
        Serialize to JSON that is safe to inline inside a <script> element.

        iNaturalist free text (place_guess, common names, user logins) reaches
        this page verbatim. An unescaped "</script>" would close the block
        early, breaking the page and executing whatever followed.
        """
        # ensure_ascii=True also escapes U+2028/U+2029, which are legal in
        # JSON but are line terminators to a JavaScript parser.
        return (
            json.dumps(payload, indent=2, ensure_ascii=True)
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('&', '\\u0026')
        )

    def _generate_html_template(self, observations: List[Dict], max_photos: int, social_split: bool) -> str:
        """Generate the HTML template with embedded JavaScript."""
        observations_json_str = self._json_for_script_block(observations)

        # Build the CSV download filename. Species names come from the command
        # line and can contain apostrophes ("Cooper's hawk"), which would break
        # out of a raw JS string literal, so emit it as JSON.
        species_part = "_".join([s.replace(" ", "-") for s in self.species_list[:2]])
        place_part = f"_{self.place.replace(' ', '-')}" if self.place else ""
        date_part = datetime.now().strftime("%Y%m%d")
        csv_filename_js = self._json_for_script_block(
            f"inat_observations_export_{species_part}{place_part}_{date_part}.csv"
        )
        social_split_js = 'true' if social_split else 'false'

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

        .btn-split {{
            padding: 4px 12px;
            font-size: 11px;
            background: #2c7a3f;
            color: white;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            transition: all 0.2s;
        }}

        .btn-split:hover {{
            background: #235c31;
        }}

        .btn-split.split {{
            background: #dc3545;
        }}

        .btn-split.split:hover {{
            background: #c82333;
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

        /* Alternating row colors for split observations */
        .obs-group-even {{
            background: #ffffff;
        }}

        .obs-group-odd {{
            background: #f0f4ff;  /* Light blue background */
        }}

        .obs-group-even:hover,
        .obs-group-odd:hover {{
            background: #fff9e6 !important;  /* Light yellow on hover */
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

        .obscured-badge {{
            display: inline-block;
            padding: 3px 6px;
            border-radius: 3px;
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            background: #ffcdd2;
            color: #c62828;
            margin-left: 4px;
        }}

        .obscured-badge.taxon {{
            background: #ffe0b2;
            color: #e65100;
        }}

        .accuracy-info {{
            font-size: 10px;
            color: #999;
            margin-top: 2px;
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

        /* Failure messages (clipboard missing/blocked) reuse #copy-success --
           without this modifier they would render in the success palette above,
           telling the reviewer their copy worked when it did not. */
        .copy-success.copy-error {{
            background: #f8d7da;
            color: #721c24;
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
                <div class="stat">
                    <span class="stat-label">GPS Obscured</span>
                    <span class="stat-value" id="obscured-count" style="color: #e65100;">0</span>
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
                            <th>GPS</th>
                            <th>Observer</th>
                            <th>Quality</th>
                            <th>License</th>
                            <th>Photos</th>
                            <th id="split-header" style="display: none;">Split</th>
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
        // The width every observation's photos / licenses / photo_licensed array
        // is padded to. No logic branches on it any more -- the Split column is
        // gated on can_split -- but it names the padding width those arrays
        // share, and it is the value tests use to prove the padding happened.
        const maxPhotos = {max_photos};
        const socialSplitMode = {social_split_js};

        // Filename components for CSV export
        const csvFilename = {csv_filename_js};

        // observation_id -> bool. Seeded from initially_split (the flag plus the
        // organism-evidence suppression), then owned by the reviewer.
        const splitState = new Map();

        function isSplit(obs) {{
            if (!splitState.has(obs.observation_id)) {{
                splitState.set(obs.observation_id, Boolean(obs.initially_split));
            }}
            return splitState.get(obs.observation_id);
        }}

        // Whether the Split column exists on this page at all. Gates the <th>
        // reveal AND the per-row <td> together -- they must never disagree, or
        // the body carries a cell the head does not show. Driven by can_split,
        // not by maxPhotos: a page whose only multi-file observation is an
        // animated GIF has nothing splittable and so needs no column.
        const splitColumnShown = observations.some(o => o.can_split);

        function toggleSplit(observationId) {{
            const obs = observations.find(o => o.observation_id === observationId);
            // can_split, not photo_count: Python already decided (an animated
            // GIF's frames are one photo, and must not become N Encounters).
            if (!obs || !obs.can_split) return;
            splitState.set(observationId, !isSplit(obs));
            renderObservations();
            updateStats();
            updateCSV();
        }}

        // One display row per photo when split, otherwise one per observation.
        function displayRows() {{
            const rows = [];
            observations.forEach(obs => {{
                if (isSplit(obs)) {{
                    // Iterate photo_count, not photos.length: photos and licenses are
                    // padded to maxPhotos with nulls and must stay index-aligned.
                    for (let i = 0; i < obs.photo_count; i++) rows.push({{obs: obs, photoIndex: i}});
                }} else {{
                    rows.push({{obs: obs, photoIndex: null}});
                }}
            }});
            return rows;
        }}

        // Stable across split toggles, so a deselected photo stays deselected through a
        // split -> unsplit -> re-split round trip. The merged row has its own key.
        function rowKey(obs, photoIndex) {{
            return obs.observation_id + ':' + (photoIndex === null ? 'all' : photoIndex);
        }}

        // Whether each display row is selected for export, keyed by rowKey().
        // Seeded from the default heuristic below, then owned by the reviewer:
        // re-rendering (after a split toggle, say) must not throw their choices away.
        const selectionState = new Map();

        function defaultSelected(obs, photoIndex) {{
            // A split row exports only its own photo, so it needs only that photo
            // licensed; a merged row exports all of them and needs all licensed.
            const licensed = photoIndex === null
                ? obs.all_media_licensed
                : Boolean(obs.photo_licensed && obs.photo_licensed[photoIndex]);
            return licensed &&
                   !obs.has_non_organism_evidence &&
                   !obs.is_skulls_and_bones &&
                   obs.quality_grade !== 'needs_id';
        }}

        function isSelected(obs, photoIndex) {{
            const key = rowKey(obs, photoIndex);
            if (!selectionState.has(key)) {{
                selectionState.set(key, defaultSelected(obs, photoIndex));
            }}
            return selectionState.get(key);
        }}

        // Initialize
        document.addEventListener('DOMContentLoaded', function() {{
            initializeSplitColumn();
            renderObservations();
            updateCSV();
            updateStats();
        }});

        function initializeSplitColumn() {{
            // Only useful when something can actually be split.
            const header = document.getElementById('split-header');
            if (header && splitColumnShown) header.style.display = '';
        }}

        function renderObservations() {{
            const tbody = document.getElementById('observations-body');
            tbody.innerHTML = '';

            // Rank observations, not rows: expanding after sorting keeps an
            // observation's photos adjacent instead of scattering them.
            const ordered = observations.slice().sort((a, b) => {{
                const aSel = anySelected(a), bSel = anySelected(b);
                if (aSel === bSel) return 0;
                return aSel ? -1 : 1;
            }});

            let colorIndex = 0;
            ordered.forEach(obs => {{
                const split = isSplit(obs);
                const groupClass = (colorIndex++ % 2 === 0) ? 'obs-group-even' : 'obs-group-odd';
                const indices = split ? Array.from({{length: obs.photo_count}}, (_, i) => i) : [null];

                indices.forEach(photoIndex => {{
                    const tr = document.createElement('tr');
                    // Which observation this rendered row belongs to. Lets a
                    // reader (and a test) see grouping in the table itself
                    // rather than inferring it from the data model, which is
                    // observation-ordered by construction and so cannot show
                    // whether sorting scattered a split group.
                    tr.setAttribute('data-observation-id', obs.observation_id);
                    if (split) tr.classList.add(groupClass);
                    renderRow(tr, obs, photoIndex);
                    tbody.appendChild(tr);
                }});
            }});

            updateStats();
        }}

        function anySelected(obs) {{
            if (isSplit(obs)) {{
                for (let i = 0; i < obs.photo_count; i++) if (isSelected(obs, i)) return true;
                return false;
            }}
            return isSelected(obs, null);
        }}

        // all_photo_paths holds null where a photo failed to download, so it stays
        // index-aligned with photos. The modal cannot display a null, so hand it a
        // compacted list and translate this row's photo index into that list --
        // never pass photoIndex straight through as a gallery position.
        function galleryFor(obs, photoIndex) {{
            const paths = obs.all_photo_paths || [];
            const gallery = paths.filter(p => p);
            const target = photoIndex === null ? 0 : photoIndex;
            let start = 0;
            for (let i = 0; i < target && i < paths.length; i++) {{
                if (paths[i]) start++;
            }}
            return {{gallery: gallery, start: Math.min(start, Math.max(0, gallery.length - 1))}};
        }}

        // Builds every cell of one display row: `photoIndex` is null for a merged
        // row (the whole observation) or the zero-based photo for a split row.
        function renderRow(tr, obs, photoIndex) {{
            // Checkbox
            const tdCheckbox = document.createElement('td');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'obs-checkbox';
            // Keyed on the composite row key, not an array index.
            checkbox.checked = isSelected(obs, photoIndex);
            checkbox.id = `obs-${{rowKey(obs, photoIndex)}}`;
            checkbox.addEventListener('change', () => {{
                selectionState.set(rowKey(obs, photoIndex), checkbox.checked);
                handleCheckboxChange();
            }});
            tdCheckbox.appendChild(checkbox);
            tr.appendChild(tdCheckbox);

            // Photo preview. A split row previews the photo it will export --
            // all_photo_paths is index-aligned with photos (null where a download
            // failed), so photoIndex means the same thing in both.
            const photoPath = photoIndex === null
                ? obs.photo_path
                : (obs.all_photo_paths && obs.all_photo_paths[photoIndex]) || null;
            const tdPhoto = document.createElement('td');
            if (photoPath) {{
                const img = document.createElement('img');
                img.src = photoPath;
                img.className = 'photo-preview';
                img.alt = 'Observation photo';
                // Open the gallery on the photo this row shows, not always the first.
                img.onclick = () => {{
                    const g = galleryFor(obs, photoIndex);
                    openModal(g.gallery, g.start);
                }};
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
            tdLocation.appendChild(locationDiv);
            tr.appendChild(tdLocation);

            // GPS Status (coordinates + obscured indicator)
            const tdGps = document.createElement('td');
            const gpsDiv = document.createElement('div');

            const hasCoords = obs.latitude !== null && obs.latitude !== undefined && obs.latitude !== ''
                          && obs.longitude !== null && obs.longitude !== undefined && obs.longitude !== '';
            if (hasCoords) {{
                // Show coordinates
                const coords = document.createElement('div');
                coords.style.fontSize = '11px';
                coords.style.color = '#666';
                coords.textContent = `${{parseFloat(obs.latitude).toFixed(4)}}, ${{parseFloat(obs.longitude).toFixed(4)}}`;
                gpsDiv.appendChild(coords);

                // Show obscured badge if coordinates are obscured
                if (obs.coordinates_obscured) {{
                    const badge = document.createElement('span');
                    badge.className = 'obscured-badge' + (obs.taxon_geoprivacy === 'obscured' ? ' taxon' : '');
                    badge.textContent = obs.taxon_geoprivacy === 'obscured' ? 'TAXON' : 'OBSCURED';
                    badge.title = obs.taxon_geoprivacy === 'obscured'
                        ? 'Coordinates obscured due to species conservation status'
                        : 'Coordinates obscured by observer';
                    gpsDiv.appendChild(badge);

                    // Show accuracy if available
                    if (obs.public_positional_accuracy) {{
                        const accuracy = document.createElement('div');
                        accuracy.className = 'accuracy-info';
                        const km = (obs.public_positional_accuracy / 1000).toFixed(1);
                        accuracy.textContent = `±${{km}}km uncertainty`;
                        gpsDiv.appendChild(accuracy);
                    }}
                }} else {{
                    // Show exact indicator
                    const exact = document.createElement('div');
                    exact.style.fontSize = '10px';
                    exact.style.color = '#4caf50';
                    exact.textContent = '✓ Exact';
                    gpsDiv.appendChild(exact);
                }}
            }} else {{
                gpsDiv.textContent = 'No GPS';
                gpsDiv.style.color = '#999';
            }}

            tdGps.appendChild(gpsDiv);
            tr.appendChild(tdGps);

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
            tdPhotoCount.textContent = photoIndex === null ? obs.photo_count : 1;
            tr.appendChild(tdPhotoCount);

            // Split / Unsplit control. Appended only when the Split column exists
            // at all -- initializeSplitColumn() keeps its <th> hidden when nothing
            // on the page can be split, and an unconditional cell here would leave
            // such a page with 12 <td> under 11 visible <th>.
            if (splitColumnShown) {{
                const tdSplit = document.createElement('td');
                if (obs.can_split) {{
                    const btn = document.createElement('button');
                    btn.className = 'btn-split' + (isSplit(obs) ? ' split' : '');
                    btn.textContent = isSplit(obs) ? 'Unsplit' : 'Split';
                    btn.onclick = () => toggleSplit(obs.observation_id);
                    tdSplit.appendChild(btn);
                }}
                tr.appendChild(tdSplit);
            }}
        }}

        function handleCheckboxChange() {{
            updateStats();
            updateCSV();
        }}

        function updateStats() {{
            const rows = displayRows();
            document.getElementById('total-count').textContent = rows.length;
            document.getElementById('selected-count').textContent =
                rows.filter(r => isSelected(r.obs, r.photoIndex)).length;
            document.getElementById('obscured-count').textContent =
                observations.filter(obs => obs.coordinates_obscured).length;
        }}

        function getSelectedObservations() {{
            return displayRows().filter(r => isSelected(r.obs, r.photoIndex));
        }}

        function setAllSelected(value) {{
            // Write BOTH sides of every split toggle, not just the rows on screen.
            // An explicit "Deselect All" has to survive a later Split: writing only
            // the current display rows would leave the other side unkeyed, and
            // defaultSelected() would then re-seed it and silently re-arm rows the
            // reviewer had excluded.
            observations.forEach(obs => {{
                selectionState.set(rowKey(obs, null), value);
                for (let i = 0; i < obs.photo_count; i++) {{
                    selectionState.set(rowKey(obs, i), value);
                }}
            }});
            renderObservations();
            updateCSV();
        }}

        function selectAll() {{
            setAllSelected(true);
        }}

        function deselectAll() {{
            setAllSelected(false);
        }}

        function updateCSV() {{
            const selected = getSelectedObservations();
            const csv = generateCSV(selected);
            document.getElementById('csv-output').textContent = csv;
        }}

        // Takes display rows -- {{obs, photoIndex}} pairs from displayRows() -- so
        // there is nothing to regroup here: a split observation already arrives as
        // one row per photo.
        function generateCSV(rows) {{
            if (rows.length === 0) {{
                return 'No observations selected';
            }}

            // Sized before the header is built, so the mediaAsset columns match
            // the rows actually written.
            const columnCount = csvColumnCount(rows);

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
                'Encounter.project0.researchProjectName',
                'Encounter.project0.ownerUsername',
                'Sighting.sightingID',
                'observer',
                'quality_grade',
                'url',
                'Encounter.otherCatalogNumbers',
                'Encounter.researcherComments',
                'photo_count',
                'photo_filenames'
            ];

            // Add photo asset columns.
            for (let i = 0; i < columnCount; i++) {{
                headers.push(`Encounter.mediaAsset${{i}}`);
                headers.push(`Encounter.mediaAsset${{i}}.license`);
            }}

            const lines = [headers.join(',')];

            // Add data rows
            rows.forEach(({{obs, photoIndex}}) => {{
                // A split row carries only its own photo; a merged row carries the
                // observation's real photos, without the null padding to maxPhotos.
                const photos = photoIndex === null
                    ? obs.photos.slice(0, obs.photo_count)
                    : [obs.photos[photoIndex]];
                const licenses = photoIndex === null
                    ? obs.licenses.slice(0, obs.photo_count)
                    : [obs.licenses[photoIndex]];

                // Mode-dependent BY DESIGN -- see the spec, decision 4. With the flag,
                // every row keeps a sighting ID so existing Wildbook imports are
                // unchanged, even a lone row. Do not "simplify" this to isSplit alone.
                const sightingId = (socialSplitMode || isSplit(obs)) ? obs.sighting_id : '';

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
                    escapeCSV(obs.project_name),
                    escapeCSV(obs.project_owner),
                    escapeCSV(sightingId),
                    escapeCSV(obs.observer),
                    escapeCSV(obs.quality_grade),
                    escapeCSV(obs.url),
                    escapeCSV(obs.other_catalog_numbers),
                    escapeCSV(obs.researcher_comments),
                    escapeCSV(photos.length),
                    escapeCSV(photos.join('; '))
                ];

                // Add photo assets and licenses
                for (let i = 0; i < columnCount; i++) {{
                    row.push(escapeCSV(photos[i]));
                    row.push(escapeCSV(licenses[i]));
                }}

                lines.push(row.join(','));
            }});

            return lines.join('\\n');
        }}

        function csvColumnCount(rows) {{
            // Sized from the rows actually written: an all-split export must not carry
            // empty mediaAsset columns, and a merged one must fit its widest row.
            return Math.max(1, ...rows.map(
                r => r.photoIndex === null ? r.obs.photo_count : 1
            ));
        }}

        function escapeCSV(value) {{
            if (value === null || value === undefined) {{
                return '';
            }}
            let str = String(value);
            // Neutralise spreadsheet formula injection from iNaturalist free
            // text, but leave genuine negative numbers (latitudes) alone.
            if (/^[=+\\-@\\t\\r]/.test(str) && !/^-?\\d*\\.?\\d+$/.test(str)) {{
                str = "'" + str;
            }}
            if (/[",\\r\\n]/.test(str)) {{
                return '"' + str.replace(/"/g, '""') + '"';
            }}
            return str;
        }}

        function flashCopyStatus(message, isError) {{
            const success = document.getElementById('copy-success');
            success.textContent = message;
            // Explicit Boolean() so a success call (isError omitted) clears any
            // .copy-error left over from a previous failed attempt.
            success.classList.toggle('copy-error', Boolean(isError));
            success.classList.add('show');
            setTimeout(() => {{
                success.classList.remove('show');
            }}, 5000);
        }}

        function copyCSV() {{
            const csv = document.getElementById('csv-output').textContent;

            // This page is opened over file://, where the Clipboard API is
            // frequently missing or blocked outright. Feature-detect and catch
            // the rejection: without both, the reviewer got a TypeError or a
            // silent unhandled rejection and no feedback at all.
            const clipboard = navigator.clipboard;
            if (!clipboard || typeof clipboard.writeText !== 'function') {{
                flashCopyStatus('Clipboard is unavailable in this browser context. '
                    + 'Use "Download CSV File" instead.', true);
                return;
            }}

            clipboard.writeText(csv).then(() => {{
                flashCopyStatus('CSV content copied to clipboard!');
            }}).catch(() => {{
                flashCopyStatus('The browser blocked clipboard access. '
                    + 'Use "Download CSV File" instead.', true);
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

        if all_observations_data:
            print(f"\nDeduplicating observations...")
            print(f"  Total rows before deduplication: {len(all_observations_data)}")
            all_observations_data = self.deduplicate_rows(all_observations_data)
            print(f"  Unique rows after deduplication: {len(all_observations_data)}")

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
                # The HTML path does its own splitting in the browser, so only the
                # direct-CSV path needs it applied here.
                csv_rows = all_observations_data
                if self.social_split:
                    csv_rows = split_rows_by_photo(csv_rows)
                csv_filename = f"inat_observations_{species_part}{place_part}_{timestamp}.csv"
                self.write_csv(csv_rows, csv_filename)

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
        '--start-date',
        type=str,
        default=None,
        help='Explicit window start, YYYY-MM-DD. Overrides --days. '
             'Use with --end-date to backfill a closed historical range.'
    )

    parser.add_argument(
        '--end-date',
        type=str,
        default=None,
        help='Explicit window end, YYYY-MM-DD (default: today). Inclusive, so '
             '--end-date 2025-06-20 covers all of 20 June 2025.'
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

    parser.add_argument(
        '--project-owner',
        type=str,
        default=None,
        help='Wildbook username to own the project (required for creating new projects in Wildbook)'
    )

    args = parser.parse_args()

    # Validate inputs
    if args.days < 1:
        print("Error: --days must be at least 1")
        sys.exit(1)

    if args.rate_limit < 0:
        print("Error: --rate-limit must be non-negative")
        sys.exit(1)

    if args.start_date and args.end_date and '--days' in sys.argv:
        print("Note: --days is ignored when both --start-date and --end-date are given.")

    # Create downloader and run. Construction validates the date window, so a
    # malformed --start-date/--end-date must exit cleanly here rather than
    # surfacing as a traceback before anything has been downloaded.
    try:
        downloader = iNaturalistDownloader(
            output_dir=args.output,
            days_back=args.days,
            species_list=args.species,
            rate_limit=args.rate_limit,
            html_review=args.html_review,
            place=args.place,
            location_id=args.use_locationID,
            submitter_id=args.use_submitterID,
            social_split=args.social_split_observations,
            project_owner=args.project_owner,
            start_date=args.start_date,
            end_date=args.end_date
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

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
