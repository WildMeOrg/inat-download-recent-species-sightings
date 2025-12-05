#!/usr/bin/env python3
"""
YouTube Wildlife Video Search Tools
Searches YouTube for wildlife videos by species name (any species)
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import urllib.request
import urllib.parse
import json

class YouTubeSearcher:
    """Search YouTube for wildlife videos."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize YouTube searcher.

        Args:
            api_key: YouTube Data API v3 key (or set YOUTUBE_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get('YOUTUBE_API_KEY')
        if not self.api_key:
            raise ValueError(
                "YouTube API key required. Set YOUTUBE_API_KEY environment variable "
                "or pass api_key parameter. Get a key at: "
                "https://console.cloud.google.com/apis/credentials"
            )

        self.base_url = "https://www.googleapis.com/youtube/v3"

    def search_videos(
        self,
        species_query: str,
        days_back: int = 1,
        max_results: int = 50,
        additional_keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search YouTube for videos about a species.

        Args:
            species_query: Species name (scientific or common) e.g., "Panthera leo" or "lion"
            days_back: How many days back to search (default: 1)
            max_results: Maximum videos to return (default: 50, max: 50 per API call)
            additional_keywords: Optional keywords to add (e.g., ["wild", "safari"])
            exclude_keywords: Optional keywords to exclude (e.g., ["cartoon", "toy"])

        Returns:
            List of video dictionaries with metadata
        """
        # Build search query
        query_parts = [species_query]

        if additional_keywords:
            query_parts.extend(additional_keywords)

        search_query = " ".join(query_parts)

        # Add exclusions with minus operator
        if exclude_keywords:
            for keyword in exclude_keywords:
                search_query += f" -{keyword}"

        # Calculate date filter (RFC 3339 format)
        published_after = (datetime.utcnow() - timedelta(days=days_back)).isoformat("T") + "Z"

        # Build API request
        params = {
            'part': 'snippet',
            'q': search_query,
            'type': 'video',
            'maxResults': min(max_results, 50),  # API limit is 50
            'publishedAfter': published_after,
            'order': 'date',  # Most recent first
            'key': self.api_key,
            'relevanceLanguage': 'en',  # Prioritize but don't restrict to English
            'safeSearch': 'none',  # Include all content
            'videoEmbeddable': 'true',  # Only embeddable videos
        }

        url = f"{self.base_url}/search?" + urllib.parse.urlencode(params)

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            videos = []

            for item in data.get('items', []):
                video_id = item['id'].get('videoId')
                if not video_id:
                    continue

                snippet = item['snippet']

                video_data = {
                    'video_id': video_id,
                    'title': snippet.get('title', ''),
                    'description': snippet.get('description', ''),
                    'channel_title': snippet.get('channelTitle', ''),
                    'channel_id': snippet.get('channelId', ''),
                    'published_at': snippet.get('publishedAt', ''),
                    'thumbnail_url': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                    'url': f"https://www.youtube.com/watch?v={video_id}",
                    'embed_url': f"https://www.youtube.com/embed/{video_id}",
                }

                videos.append(video_data)

            return videos

        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else "No error details"
            raise Exception(f"YouTube API error: {e.code} - {error_body}")

        except Exception as e:
            raise Exception(f"Error searching YouTube: {str(e)}")

    def search_multi_language(
        self,
        species_names: Dict[str, str],
        days_back: int = 1,
        max_results_per_language: int = 10,
        additional_keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search YouTube with multiple language variants of a species name.

        Args:
            species_names: Dict of language code -> species name
                Example: {"en": "lion", "es": "león", "scientific": "Panthera leo"}
            days_back: How many days back to search
            max_results_per_language: Max results per language variant
            additional_keywords: Optional keywords to add to all searches
            exclude_keywords: Optional keywords to exclude from all searches

        Returns:
            Deduplicated list of videos (by video_id)
        """
        all_videos = []
        seen_ids = set()

        for language, species_name in species_names.items():
            try:
                videos = self.search_videos(
                    species_query=species_name,
                    days_back=days_back,
                    max_results=max_results_per_language,
                    additional_keywords=additional_keywords,
                    exclude_keywords=exclude_keywords
                )

                for video in videos:
                    # Deduplicate by video ID
                    if video['video_id'] not in seen_ids:
                        video['matched_language'] = language
                        video['matched_query'] = species_name
                        all_videos.append(video)
                        seen_ids.add(video['video_id'])

            except Exception as e:
                print(f"Warning: Error searching for '{species_name}' ({language}): {e}")
                continue

        # Sort by published date (most recent first)
        all_videos.sort(key=lambda x: x.get('published_at', ''), reverse=True)

        return all_videos

    def get_video_details(self, video_id: str) -> Dict[str, Any]:
        """
        Get detailed information about a specific video.

        Args:
            video_id: YouTube video ID

        Returns:
            Detailed video metadata
        """
        params = {
            'part': 'snippet,contentDetails,statistics',
            'id': video_id,
            'key': self.api_key
        }

        url = f"{self.base_url}/videos?" + urllib.parse.urlencode(params)

        try:
            with urllib.request.urlopen(url) as response:
                data = json.loads(response.read().decode())

            if not data.get('items'):
                raise Exception(f"Video not found: {video_id}")

            item = data['items'][0]
            snippet = item['snippet']
            statistics = item.get('statistics', {})
            content_details = item.get('contentDetails', {})

            return {
                'video_id': video_id,
                'title': snippet.get('title', ''),
                'description': snippet.get('description', ''),
                'channel_title': snippet.get('channelTitle', ''),
                'channel_id': snippet.get('channelId', ''),
                'published_at': snippet.get('publishedAt', ''),
                'tags': snippet.get('tags', []),
                'category_id': snippet.get('categoryId', ''),
                'duration': content_details.get('duration', ''),
                'view_count': statistics.get('viewCount', 0),
                'like_count': statistics.get('likeCount', 0),
                'comment_count': statistics.get('commentCount', 0),
                'thumbnail_url': snippet.get('thumbnails', {}).get('high', {}).get('url', ''),
                'url': f"https://www.youtube.com/watch?v={video_id}",
                'embed_url': f"https://www.youtube.com/embed/{video_id}",
            }

        except Exception as e:
            raise Exception(f"Error getting video details: {str(e)}")

def format_video_results(videos: List[Dict[str, Any]], include_descriptions: bool = True) -> str:
    """
    Format video results as readable text.

    Args:
        videos: List of video dictionaries
        include_descriptions: Whether to include video descriptions

    Returns:
        Formatted string
    """
    if not videos:
        return "No videos found."

    result = f"**Found {len(videos)} videos:**\n\n"

    for i, video in enumerate(videos, 1):
        # Parse date
        pub_date = video.get('published_at', '')
        if pub_date:
            try:
                dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d %H:%M UTC')
            except:
                date_str = pub_date
        else:
            date_str = "Unknown date"

        result += f"**{i}. {video.get('title', 'Untitled')}**\n"
        result += f"   - Channel: {video.get('channel_title', 'Unknown')}\n"
        result += f"   - Published: {date_str}\n"
        result += f"   - URL: {video.get('url', '')}\n"

        if video.get('matched_language'):
            result += f"   - Matched: {video.get('matched_query', '')} ({video.get('matched_language', '')})\n"

        if include_descriptions and video.get('description'):
            desc = video['description'][:200]  # First 200 chars
            if len(video['description']) > 200:
                desc += "..."
            result += f"   - Description: {desc}\n"

        result += "\n"

    return result

def evaluate_wild_sighting_likelihood(video: Dict[str, Any]) -> Dict[str, Any]:
    """
    Evaluate whether a video is likely a genuine wild wildlife sighting with citizen science value.

    Uses title, description, and channel to score likelihood of scientific value.
    Conservative scoring - prioritizes precision over recall.

    Args:
        video: Video dictionary with title, description, channel_title

    Returns:
        Dict with 'score' (0-100), 'is_likely_wild' (bool), 'reasons' (list of str)
    """
    title = (video.get('title', '') or '').lower()
    description = (video.get('description', '') or '').lower()
    channel = (video.get('channel_title', '') or '').lower()

    combined_text = f"{title} {description} {channel}"

    score = 40  # Start conservative (assume not wild until proven otherwise)
    reasons = []

    # CRITICAL HASHTAG ANALYSIS - Extract hashtags from title and description
    import re
    hashtag_pattern = r'#\w+'
    hashtags = ' '.join(re.findall(hashtag_pattern, title + ' ' + description)).lower()

    # DISQUALIFYING HASHTAGS (instant reject or heavy penalty)
    disqualifying_tags = [
        '#shorts', '#short', '#viral', '#trending', '#viralvideo', '#tending',
        '#shortsfeed', '#shortsvideo', '#ytshorts', '#youtubeshorts',
        '#facts', '#factsdastan', '#explained', '#didyouknow',
        '#roblox', '#minecraft', '#gaming', '#gameplay', '#game',
        '#ai', '#aiart', '#sora', '#animation', '#cartoon',
        '#diy', '#craft', '#crochet', '#drawing', '#art',
        '#funny', '#comedy', '#meme', '#lol', '#omg',
        '#foryou', '#fyp', '#foryoupage',
        '#edit', '#edits', '#compilation',
        '#comparison', '#vs', '#battle', '#fight'
    ]

    if any(tag in hashtags for tag in disqualifying_tags):
        score -= 50
        reasons.append("Non-scientific hashtags (viral/shorts/gaming/AI/comedy)")

    # STRONG NEGATIVE INDICATORS (likely NOT wild sighting)

    # Games and virtual content
    if any(word in combined_text for word in ['roblox', 'minecraft', 'game', 'gaming', 'hungry shark',
                                                 'gameplay', 'playing as', 'pov:', 'video game', 'raisen animales']):
        score -= 45
        reasons.append("Video game/gaming content")

    # Aquarium/zoo/captive (completely exclude)
    if any(word in combined_text for word in ['aquarium', 'zoo', 'tank', 'captive', 'captivity', 'shedd aquarium',
                                                 'georgia aquarium', 'brookfield zoo']):
        score -= 50
        reasons.append("Aquarium/zoo/captive setting (not wild)")

    # Educational/facts/documentary content (not actual sightings)
    if any(word in combined_text for word in ['facts', 'explained', 'did you know', 'comparison',
                                                 'vs ', ' vs.', 'battle', 'fight', 'who would win',
                                                 'top 10', 'top 5', 'top 3', 'learn', 'educational']):
        score -= 40
        reasons.append("Educational/documentary content (not sighting)")

    # AI generated content - channels, keywords, and patterns
    ai_channel_patterns = ['apex realms', 'ai magica', 'realistic', 'cinematic', 'wildlens',
                          'generated', 'deepseafables', 'mothers of the wild', 'primal origins']

    ai_content_keywords = ['ai ', ' ai', 'sora', 'caught on camera in chicago',
                          'real footage in chicago', 'cinematic disaster',
                          'realistic cinematic', 'magical moment', 'eye contact',
                          'glowing tornado', 'witness', 'in awe', 'spectacular display']

    if any(pattern in channel for pattern in ai_channel_patterns):
        score -= 70
        reasons.append("AI-generated content channel")
    elif any(word in combined_text for word in ai_content_keywords):
        score -= 60
        reasons.append("AI-generated or staged content")

    # Suspiciously low engagement for professional content (likely AI)
    # This requires video details, so we'll check in the main search function

    # Crafts, toys, animations
    if any(word in combined_text for word in ['diy', 'craft', 'crochet', 'making a', 'toy', 'lego',
                                                 'drawing', 'cartoon', 'animation', 'transformation']):
        score -= 50
        reasons.append("Craft/toy/animation content")

    # News clips and TV shows (usually not direct observations)
    if any(word in combined_text for word in ['abc 7', 'cnn', 'bbc', 'fox news', 'news', 'reported',
                                                 'reports', 'breaking news', 'headlines']):
        score -= 25
        reasons.append("News/media coverage (indirect)")

    # Click-bait and sensationalized content
    if any(word in combined_text for word in ['you won\'t believe', 'shocking', 'attacked', 'attacks',
                                                 'omg', 'wow', 'insane', 'crazy', 'unbelievable',
                                                 'instant', 'recognizes baby']):
        score -= 20
        reasons.append("Sensationalized/clickbait content")

    # Compilations and collections
    if any(word in combined_text for word in ['compilation', 'collection', 'best of', 'moments']):
        score -= 15
        reasons.append("Compilation video (not single sighting)")

    # Generic/vague content
    if any(word in combined_text for word in ['ocean life', 'marine life', 'sea creatures',
                                                 'sea animals', 'ocean animals']) and 'sighting' not in combined_text:
        score -= 10
        reasons.append("Generic ocean content (not specific sighting)")

    # STRONG POSITIVE INDICATORS (likely wild sighting)

    # Diving and swimming encounters (direct observation)
    if any(word in combined_text for word in ['diving', 'scuba', 'snorkel', 'swim with', 'swimming with',
                                                 'underwater', 'dive', 'freediving', 'snorkeling']):
        score += 35
        reasons.append("Diving/snorkeling encounter (direct observation)")

    # Specific wildlife tourism locations (known wild hotspots)
    hotspot_locations = ['oslob', 'baja', 'maldives', 'galapagos', 'sail rock', 'sailrock',
                        'similan', 'richelieu', 'koh tao', 'philippines', 'cebu', 'donsol',
                        'mafia island', 'ningaloo', 'sumbawa', 'okinawa', 'pemba', 'zanzibar',
                        'mozambique', 'tanzania', 'mexico', 'honduras', 'belize']

    if any(location in combined_text for location in hotspot_locations):
        score += 40
        reasons.append("Known wild wildlife hotspot location")

    # Tour and trip indicators (actual field observation)
    if any(word in combined_text for word in ['tour', 'trip', 'expedition', 'encounter', 'sighting',
                                                 'spotted', 'saw a', 'found a', 'came across']):
        score += 25
        reasons.append("Tour/expedition/sighting language")

    # Wildlife photography/documentation channels
    if any(word in channel for word in ['dive', 'ocean', 'marine', 'wildlife', 'nature', 'adventure',
                                          'travel', 'explorer', 'conservation', 'underwater']):
        score += 20
        reasons.append("Wildlife-focused channel")

    # Recent personal footage indicators
    if any(word in combined_text for word in ['gopro', 'my ', 'our ', 'i saw', 'we saw', 'today',
                                                 'yesterday', 'this morning', 'just saw']):
        score += 15
        reasons.append("Personal footage indicators")

    # Conservation and research content (high scientific value)
    if any(word in combined_text for word in ['rescue', 'conservation', 'research', 'tagging',
                                                 'tracking', 'monitoring', 'scientist', 'biologist']):
        score += 30
        reasons.append("Conservation/research content (scientific)")

    # Date/location specificity (indicates real observation)
    if any(word in combined_text for word in ['oct', 'nov', 'dec', 'jan', 'feb', 'mar', 'apr', 'may', 'jun',
                                                 'jul', 'aug', 'sep', '2025', '2024', 'today']) and \
       any(word in combined_text for word in hotspot_locations + ['beach', 'island', 'coast', 'reef']):
        score += 15
        reasons.append("Specific date/location (actual observation)")

    # Clamp score to 0-100 range
    score = max(0, min(100, score))

    # Conservative threshold - only mark as likely wild if >50% confident
    is_likely_wild = score > 50

    return {
        'score': score,
        'is_likely_wild': is_likely_wild,
        'reasons': reasons
    }


# Cache spaCy model at module level for performance
_nlp_model = None

def _get_nlp_model():
    """Load and cache spaCy model"""
    global _nlp_model
    if _nlp_model is None:
        import spacy
        _nlp_model = spacy.load("en_core_web_sm")
    return _nlp_model


def _determine_date_precision(date_text: str, parsed_date) -> str:
    """
    Determine the precision level of a date based on the original text.

    Returns:
        Date string in format: YYYY, YYYY-MM, or YYYY-MM-DD
    """
    import re

    date_text_lower = date_text.lower()

    # Check if it has day-level precision
    # Look for patterns like: "7th", "7", day numbers, "yesterday", "today"
    has_day = bool(re.search(r'\b\d{1,2}(st|nd|rd|th)?\b', date_text) or
                   'yesterday' in date_text_lower or
                   'today' in date_text_lower or
                   'last week' in date_text_lower or
                   'this week' in date_text_lower)

    # Check if it has month-level precision
    month_pattern = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|january|february|march|april|may|june|july|august|september|october|november|december)\b'
    has_month = bool(re.search(month_pattern, date_text_lower) or
                     'last month' in date_text_lower or
                     'this month' in date_text_lower)

    # Check if it explicitly mentions only year
    year_only_pattern = r'^\s*\d{4}\s*$|in\s+\d{4}|during\s+\d{4}'
    is_year_only = bool(re.search(year_only_pattern, date_text))

    if is_year_only and not has_month:
        return parsed_date.strftime('%Y')
    elif has_month and not has_day:
        return parsed_date.strftime('%Y-%m')
    elif has_day:
        return parsed_date.strftime('%Y-%m-%d')
    else:
        # Default to year only if we can't determine
        return parsed_date.strftime('%Y')


def extract_observation_date(video: Dict[str, Any]) -> str:
    """
    Extract the observation date from video metadata using spaCy NLP.

    Uses spaCy's Named Entity Recognition to find dates in title/description,
    then uses dateparser to resolve them (including relative dates like
    "yesterday", "last week"). Returns partial dates when appropriate.

    Args:
        video: Video dictionary with title, description, published_at

    Returns:
        Date string: YYYY-MM-DD, YYYY-MM, YYYY, or empty string if no date found

    Examples:
        "7th Oct 2025" -> "2025-10-07"
        "October 2025" -> "2025-10"
        "2025" -> "2025"
        "yesterday" -> "2025-11-06" (relative to published date)
    """
    import dateparser
    from datetime import datetime
    import re

    title = video.get('title', '') or ''
    description = video.get('description', '') or ''
    published_at = video.get('published_at', '')

    # Parse published date as reference for relative dates
    try:
        published_date = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
    except:
        published_date = datetime.utcnow()

    # Combine title and description for NLP analysis
    combined_text = f"{title}. {description}"

    # First try quick regex patterns for common formats before expensive NLP
    # Pattern 1: Full ISO format (2025-11-07)
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', combined_text)
    if iso_match:
        return iso_match.group(0)  # Full date: YYYY-MM-DD

    # Pattern 2: Year-Month ISO (2025-10)
    year_month_iso = re.search(r'\b(\d{4})-(\d{2})\b', combined_text)
    if year_month_iso:
        return year_month_iso.group(0)  # Partial date: YYYY-MM

    # Pattern 3: Common formats like "7th Oct", "Oct 7", "November 5"
    # These often lack year and spaCy may not recognize them, so handle with dateparser
    month_day_patterns = [
        r'\b(\d{1,2})(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|december|january|february|march|april|may|june|july|august|september|october|november|december)\b',
        r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|december|january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{1,2})(st|nd|rd|th)?\b'
    ]
    for pattern in month_day_patterns:
        match = re.search(pattern, combined_text, re.IGNORECASE)
        if match:
            # Use dateparser to resolve relative to published date
            parsed = dateparser.parse(
                match.group(0),
                settings={
                    'RELATIVE_BASE': published_date,
                    'PREFER_DATES_FROM': 'past',
                    'RETURN_AS_TIMEZONE_AWARE': False
                }
            )
            if parsed:
                return parsed.strftime('%Y-%m-%d')

    # Use spaCy NLP for more complex date extraction
    nlp = _get_nlp_model()
    doc = nlp(combined_text)

    # Find DATE entities
    date_entities = [ent for ent in doc.ents if ent.label_ == "DATE"]

    for ent in date_entities:
        date_text = ent.text

        # Use dateparser to resolve the date relative to published date
        parsed_date = dateparser.parse(
            date_text,
            settings={
                'RELATIVE_BASE': published_date,
                'PREFER_DATES_FROM': 'past',  # Wildlife observations are usually in the past
                'RETURN_AS_TIMEZONE_AWARE': False
            }
        )

        if parsed_date:
            # Determine precision based on original text
            return _determine_date_precision(date_text, parsed_date)

    # If spaCy didn't find dates, try simple year extraction as fallback
    # Only match year if it's reasonable (2015-2030) and word-bounded
    year_only_match = re.search(r'\b(201[5-9]|202[0-9]|2030)\b', combined_text)
    if year_only_match:
        return year_only_match.group(1)  # Partial date: YYYY

    # IMPORTANT: Do NOT default to published date!
    # The observation date is often different from upload date.
    # Return empty string if no date information found in content.
    return ''


def extract_location(video: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract location information from video metadata.

    Attempts to find GPS coordinates, place names, and countries from
    title, description, and tags.

    Args:
        video: Video dictionary with title, description

    Returns:
        Dict with 'place_name', 'country', 'latitude', 'longitude'
    """
    import re

    title = (video.get('title', '') or '').lower()
    description = (video.get('description', '') or '').lower()
    combined_text = f"{title} {description}"

    location_data = {
        'place_name': '',
        'country': '',
        'latitude': None,
        'longitude': None
    }

    # Known wildlife locations with coordinates (whale sharks, safaris, etc.)
    known_locations = {
        'oslob': {'place': 'Oslob', 'country': 'Philippines', 'lat': 9.5167, 'lon': 123.3833},
        'cebu': {'place': 'Cebu', 'country': 'Philippines', 'lat': 10.3157, 'lon': 123.8854},
        'baja': {'place': 'Baja California', 'country': 'Mexico', 'lat': 28.0, 'lon': -113.0},
        'la paz': {'place': 'La Paz', 'country': 'Mexico', 'lat': 24.1426, 'lon': -110.3128},
        'maldives': {'place': 'Maldives', 'country': 'Maldives', 'lat': 3.2028, 'lon': 73.2207},
        'galapagos': {'place': 'Galapagos Islands', 'country': 'Ecuador', 'lat': -0.9538, 'lon': -90.9656},
        'kruger': {'place': 'Kruger National Park', 'country': 'South Africa', 'lat': -24.0, 'lon': 31.5},
        'serengeti': {'place': 'Serengeti', 'country': 'Tanzania', 'lat': -2.3333, 'lon': 34.8333},
        'tanzania': {'place': 'Tanzania', 'country': 'Tanzania', 'lat': -6.3690, 'lon': 34.8888},
        'kenya': {'place': 'Kenya', 'country': 'Kenya', 'lat': -1.2864, 'lon': 36.8172},
        'sumbawa': {'place': 'Sumbawa', 'country': 'Indonesia', 'lat': -8.6500, 'lon': 117.3667},
        'okinawa': {'place': 'Okinawa', 'country': 'Japan', 'lat': 26.2124, 'lon': 127.6809},
        'similan': {'place': 'Similan Islands', 'country': 'Thailand', 'lat': 8.6500, 'lon': 97.6333},
        'richelieu': {'place': 'Richelieu Rock', 'country': 'Thailand', 'lat': 9.6000, 'lon': 98.2000},
        'sail rock': {'place': 'Sail Rock', 'country': 'Thailand', 'lat': 9.5667, 'lon': 99.8167},
        'koh tao': {'place': 'Koh Tao', 'country': 'Thailand', 'lat': 10.0956, 'lon': 99.8394},
        'south africa': {'place': 'South Africa', 'country': 'South Africa', 'lat': -30.5595, 'lon': 22.9375},
        'mozambique': {'place': 'Mozambique', 'country': 'Mozambique', 'lat': -18.6657, 'lon': 35.5296},
        'zanzibar': {'place': 'Zanzibar', 'country': 'Tanzania', 'lat': -6.1659, 'lon': 39.2026},
        'mafia island': {'place': 'Mafia Island', 'country': 'Tanzania', 'lat': -7.9167, 'lon': 39.7500},
        'ningaloo': {'place': 'Ningaloo Reef', 'country': 'Australia', 'lat': -22.0000, 'lon': 113.8333},
        'donsol': {'place': 'Donsol', 'country': 'Philippines', 'lat': 12.9050, 'lon': 123.5950},
    }

    # Check for known locations
    for location_key, location_info in known_locations.items():
        if location_key in combined_text:
            location_data['place_name'] = location_info['place']
            location_data['country'] = location_info['country']
            location_data['latitude'] = location_info['lat']
            location_data['longitude'] = location_info['lon']
            return location_data

    # Look for GPS coordinates in description (e.g., "12.345, -67.890" or "12°34'56"N 67°89'01"W")
    coord_patterns = [
        r'(-?\d{1,3}\.\d{4,}),?\s*(-?\d{1,3}\.\d{4,})',  # Decimal degrees
        r'(\d{1,3})°(\d{1,2})\'(\d{1,2})"([NS])\s*(\d{1,3})°(\d{1,2})\'(\d{1,2})"([EW])'  # DMS
    ]

    for pattern in coord_patterns:
        match = re.search(pattern, description)
        if match:
            try:
                if 'decimal' in pattern or '\\.' in pattern:
                    location_data['latitude'] = float(match.group(1))
                    location_data['longitude'] = float(match.group(2))
                    return location_data
            except:
                pass

    # Look for country names
    countries = [
        'south africa', 'tanzania', 'kenya', 'botswana', 'namibia', 'zimbabwe',
        'mozambique', 'zambia', 'madagascar', 'uganda', 'rwanda',
        'mexico', 'philippines', 'indonesia', 'thailand', 'maldives',
        'australia', 'japan', 'ecuador', 'honduras', 'belize'
    ]

    for country in countries:
        if country in combined_text:
            location_data['country'] = country.title()
            break

    return location_data


def generate_html_report(
    videos: List[Dict[str, Any]],
    output_path: str,
    search_params: Optional[Dict[str, Any]] = None
) -> str:
    """
    Generate an interactive HTML report for YouTube video search results.

    Only includes videos with >90% wild sighting confidence score.
    Videos with ≤90% confidence are completely excluded from the report.

    Args:
        videos: List of video dictionaries
        output_path: Path to save the HTML file
        search_params: Optional dict with search parameters (species, dates, etc.)

    Returns:
        Path to the generated HTML file
    """
    from pathlib import Path

    # Filter videos - only include those with >90% confidence (strict scientific threshold)
    original_count = len(videos)
    filtered_videos = []

    for video in videos:
        evaluation = evaluate_wild_sighting_likelihood(video)
        if evaluation['score'] > 90:
            # Add evaluation data to video dict for later use
            video['_evaluation'] = evaluation
            filtered_videos.append(video)

    videos = filtered_videos
    excluded_count = original_count - len(videos)

    # Prepare search parameters display
    search_info = ""
    if search_params:
        if 'species' in search_params:
            search_info += f"<strong>Species:</strong> {search_params['species']}<br>"
        if 'species_names' in search_params:
            search_info += "<strong>Languages searched:</strong> "
            search_info += ", ".join(f"{lang}: {name}" for lang, name in search_params['species_names'].items())
            search_info += "<br>"
        if 'days_back' in search_params:
            search_info += f"<strong>Time period:</strong> Last {search_params['days_back']} days<br>"
        if 'place' in search_params:
            search_info += f"<strong>Location filter:</strong> {search_params['place']}<br>"

    # Add filtering info
    search_info += f"<strong>Total videos found:</strong> {original_count}<br>"
    search_info += f"<strong>High-confidence sightings:</strong> {len(videos)} (&gt;90% confidence)<br>"
    if excluded_count > 0:
        search_info += f"<strong>Excluded:</strong> {excluded_count} videos (≤90% confidence)<br>"

    # Generate timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build video cards HTML
    video_cards = ""
    wild_count = 0
    for i, video in enumerate(videos):
        video_id = video.get('video_id', '')
        title = video.get('title', 'Untitled').replace('"', '&quot;').replace("'", "&#39;")
        channel = video.get('channel_title', 'Unknown')
        description = video.get('description', '')[:300]
        if len(video.get('description', '')) > 300:
            description += "..."

        pub_date = video.get('published_at', '')
        if pub_date:
            try:
                dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d %H:%M UTC')
            except:
                date_str = pub_date
        else:
            date_str = "Unknown date"

        url = video.get('url', '')
        matched_lang = video.get('matched_language', '')
        matched_query = video.get('matched_query', '')

        # Use cached evaluation from filtering step
        evaluation = video.get('_evaluation', {})
        score = evaluation.get('score', 0)
        is_likely_wild = evaluation.get('is_likely_wild', False)
        reasons = evaluation.get('reasons', [])

        # Extract observation date and location
        obs_date = extract_observation_date(video)
        location = extract_location(video)

        # Add extracted data to video dict for CSV export
        video['_obs_date'] = obs_date
        video['_location'] = location

        # All videos in report are already >90%, so all are checked by default
        checked_attr = 'checked'
        wild_count += 1

        # Create confidence badge with color coding
        if score >= 70:
            badge_class = 'confidence-high'
            badge_text = f'🟢 High confidence ({score}%)'
        elif score >= 40:
            badge_class = 'confidence-medium'
            badge_text = f'🟡 Medium confidence ({score}%)'
        else:
            badge_class = 'confidence-low'
            badge_text = f'🔴 Low confidence ({score}%)'

        reasons_html = '<br>• '.join(reasons) if reasons else 'No specific indicators'

        video_cards += f"""
        <div class="video-card" data-index="{i}">
            <div class="video-header">
                <input type="checkbox" class="video-checkbox" id="video-{i}" {checked_attr}>
                <label for="video-{i}" class="video-title">{title}</label>
                <span class="confidence-badge {badge_class}">{badge_text}</span>
            </div>
            <div class="video-content">
                <div class="video-player">
                    <iframe
                        width="100%"
                        height="315"
                        src="https://www.youtube.com/embed/{video_id}"
                        frameborder="0"
                        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                        allowfullscreen>
                    </iframe>
                </div>
                <div class="video-metadata">
                    <p><strong>Channel:</strong> {channel}</p>
                    <p><strong>Published:</strong> {date_str}</p>
                    {f'<p><strong>Observation Date (extracted):</strong> {obs_date}</p>' if obs_date else '<p><strong>Observation Date:</strong> <em>Unknown (not found in title/description)</em></p>'}
                    {f'<p><strong>Location (extracted):</strong> {location["place_name"]}{", " + location["country"] if location["country"] and location["place_name"] else location["country"]}</p>' if location.get('place_name') or location.get('country') else '<p><strong>Location:</strong> <em>Unknown (not found in title/description)</em></p>'}
                    {f'<p><strong>Coordinates:</strong> {location["latitude"]:.4f}, {location["longitude"]:.4f}</p>' if location.get('latitude') and location.get('longitude') else ''}
                    <p><strong>URL:</strong> <a href="{url}" target="_blank">{url}</a></p>
                    {f'<p><strong>Matched:</strong> {matched_query} ({matched_lang})</p>' if matched_lang else ''}
                    <div class="confidence-info">
                        <p><strong>Wild Sighting Confidence:</strong> {score}%</p>
                        <p><strong>Analysis:</strong><br>• {reasons_html}</p>
                    </div>
                    {f'<p><strong>Description:</strong> {description}</p>' if description else ''}
                    <div class="notes-section">
                        <label><strong>Research Notes:</strong></label>
                        <textarea class="research-notes" rows="2" placeholder="Add notes about this video's research value..."></textarea>
                    </div>
                </div>
            </div>
        </div>
        """

    # Generate complete HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>YouTube Wildlife Video Report</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: #f5f5f5;
            padding: 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .header {{
            margin-bottom: 30px;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 20px;
        }}

        h1 {{
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }}

        .search-info {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 15px;
            color: #555;
        }}

        .stats {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }}

        .stat-box {{
            background: #e3f2fd;
            padding: 15px 20px;
            border-radius: 6px;
            border-left: 4px solid #2196F3;
        }}

        .stat-box strong {{
            display: block;
            font-size: 24px;
            color: #1976D2;
        }}

        .stat-wild {{
            background: #e8f5e9;
            border-left: 4px solid #4CAF50;
        }}

        .stat-wild strong {{
            color: #2E7D32;
        }}

        .confidence-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 10px;
        }}

        .confidence-high {{
            background: #e8f5e9;
            color: #2E7D32;
            border: 1px solid #4CAF50;
        }}

        .confidence-medium {{
            background: #fff8e1;
            color: #F57F17;
            border: 1px solid #FBC02D;
        }}

        .confidence-low {{
            background: #ffebee;
            color: #C62828;
            border: 1px solid #E53935;
        }}

        .confidence-info {{
            background: #f5f5f5;
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
            font-size: 13px;
        }}

        .confidence-info p {{
            margin: 5px 0;
        }}

        .controls {{
            display: flex;
            gap: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }}

        button {{
            padding: 12px 24px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s;
        }}

        .btn-primary {{
            background: #2196F3;
            color: white;
        }}

        .btn-primary:hover {{
            background: #1976D2;
        }}

        .btn-secondary {{
            background: #757575;
            color: white;
        }}

        .btn-secondary:hover {{
            background: #616161;
        }}

        .btn-success {{
            background: #4CAF50;
            color: white;
        }}

        .btn-success:hover {{
            background: #45a049;
        }}

        .video-card {{
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin-bottom: 20px;
            overflow: hidden;
            transition: all 0.3s;
        }}

        .video-card:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}

        .video-header {{
            background: #fafafa;
            padding: 15px 20px;
            display: flex;
            align-items: center;
            gap: 15px;
            border-bottom: 1px solid #e0e0e0;
        }}

        .video-checkbox {{
            width: 20px;
            height: 20px;
            cursor: pointer;
        }}

        .video-title {{
            flex: 1;
            font-size: 16px;
            font-weight: 600;
            color: #333;
            cursor: pointer;
        }}

        .video-content {{
            padding: 20px;
            display: grid;
            grid-template-columns: 560px 1fr;
            gap: 20px;
        }}

        @media (max-width: 1200px) {{
            .video-content {{
                grid-template-columns: 1fr;
            }}
        }}

        .video-player {{
            position: relative;
            width: 100%;
        }}

        .video-player iframe {{
            width: 100%;
            height: 315px;
            border-radius: 6px;
        }}

        .video-metadata {{
            color: #555;
        }}

        .video-metadata p {{
            margin-bottom: 10px;
        }}

        .video-metadata a {{
            color: #2196F3;
            text-decoration: none;
            word-break: break-all;
        }}

        .video-metadata a:hover {{
            text-decoration: underline;
        }}

        .notes-section {{
            margin-top: 15px;
        }}

        .research-notes {{
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-family: inherit;
            font-size: 14px;
            resize: vertical;
        }}

        .export-section {{
            margin-top: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
        }}

        .export-output {{
            width: 100%;
            padding: 15px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            background: white;
            min-height: 200px;
        }}

        .timestamp {{
            color: #999;
            font-size: 14px;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎥 YouTube Wildlife Video Report</h1>
            <div class="search-info">
                {search_info}
            </div>
            <div class="stats">
                <div class="stat-box">
                    <strong id="total-videos">{len(videos)}</strong>
                    <span>Total Videos</span>
                </div>
                <div class="stat-box stat-wild">
                    <strong id="wild-count">{wild_count}</strong>
                    <span>Likely Wild Sightings</span>
                </div>
                <div class="stat-box">
                    <strong id="selected-count">{wild_count}</strong>
                    <span>Selected</span>
                </div>
            </div>
            <div class="controls">
                <button class="btn-primary" onclick="selectAll()">✓ Select All</button>
                <button class="btn-secondary" onclick="deselectAll()">✗ Deselect All</button>
            </div>
        </div>

        <div class="videos-list">
            {video_cards}
        </div>

        <div class="export-section">
            <h3>Export Results</h3>
            <p>Select videos above, then use the buttons below to export your selection.</p>
            <div class="controls" style="margin-bottom: 20px;">
                <button class="btn-success" onclick="exportSelected()">📥 Export Selected URLs</button>
                <button class="btn-success" onclick="exportCSV()">📊 Export as CSV (Wildbook Format)</button>
            </div>
            <textarea class="export-output" id="export-output" readonly></textarea>
        </div>

        <div class="timestamp">Generated: {timestamp}</div>
    </div>

    <script>
        function updateCount() {{
            const checkboxes = document.querySelectorAll('.video-checkbox');
            const selectedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
            document.getElementById('selected-count').textContent = selectedCount;
        }}

        function selectAll() {{
            document.querySelectorAll('.video-checkbox').forEach(cb => {{
                cb.checked = true;
            }});
            updateCount();
        }}

        function deselectAll() {{
            document.querySelectorAll('.video-checkbox').forEach(cb => {{
                cb.checked = false;
            }});
            updateCount();
        }}

        function exportSelected() {{
            const videos = {json.dumps(videos)};
            const checkboxes = document.querySelectorAll('.video-checkbox');
            const selected = [];

            checkboxes.forEach((cb, index) => {{
                if (cb.checked) {{
                    const video = videos[index];
                    const notes = document.querySelector(`#video-${{index}}`).closest('.video-card').querySelector('.research-notes').value;
                    selected.push({{
                        title: video.title,
                        url: video.url,
                        channel: video.channel_title,
                        published: video.published_at,
                        matched_language: video.matched_language || 'N/A',
                        notes: notes || 'No notes'
                    }});
                }}
            }});

            let output = `YouTube Wildlife Video Report\\n`;
            output += `Generated: {timestamp}\\n`;
            output += `Total Videos: {len(videos)}\\n`;
            output += `Selected: ${{selected.length}}\\n`;
            output += `\\n${{"-".repeat(80)}}\\n\\n`;

            selected.forEach((video, index) => {{
                output += `${{index + 1}}. ${{video.title}}\\n`;
                output += `   URL: ${{video.url}}\\n`;
                output += `   Channel: ${{video.channel}}\\n`;
                output += `   Published: ${{video.published}}\\n`;
                output += `   Matched: ${{video.matched_language}}\\n`;
                if (video.notes !== 'No notes') {{
                    output += `   Notes: ${{video.notes}}\\n`;
                }}
                output += `\\n`;
            }});

            document.getElementById('export-output').value = output;
        }}

        function exportCSV() {{
            const videos = {json.dumps(videos)};
            const checkboxes = document.querySelectorAll('.video-checkbox');
            const species = {json.dumps(search_params.get('species', '') if search_params else '')};

            // Wildbook CSV format header (matches iNaturalist export)
            let csv = 'observation_id,observed_on,Encounter.year,Encounter.month,Encounter.day,';
            csv += 'scientific_name,Encounter.genus,Encounter.specificEpithet,common_name,';
            csv += 'Encounter.decimalLatitude,Encounter.decimalLongitude,Encounter.verbatimLocality,';
            csv += 'Encounter.locationID,Encounter.livingStatus,Encounter.submitterID,Encounter.state,';
            csv += 'Sighting.sightingID,observer,quality_grade,url,Encounter.researcherComments,';
            csv += 'photo_count,photo_filenames,Encounter.mediaAsset0\\n';

            checkboxes.forEach((cb, index) => {{
                if (cb.checked) {{
                    const video = videos[index];
                    const notes = document.querySelector(`#video-${{index}}`).closest('.video-card').querySelector('.research-notes').value;

                    // Extract date components from _obs_date
                    // NOTE: _obs_date may be empty, partial (YYYY or YYYY-MM), or full (YYYY-MM-DD)
                    // Do NOT use published date as fallback - observation date != upload date
                    const obsDate = video._obs_date || '';
                    const dateParts = obsDate ? obsDate.split('-') : [];
                    const year = dateParts[0] || '';
                    const month = dateParts[1] || '';  // May be empty for year-only dates
                    const day = dateParts[2] || '';    // May be empty for year or year-month dates

                    // Extract location data
                    const location = video._location || {{}};
                    const latitude = location.latitude || '';
                    const longitude = location.longitude || '';
                    const placeName = location.place_name || '';
                    const country = location.country || '';
                    const verbatimLocality = placeName ? `${{placeName}}${{country ? ', ' + country : ''}}` : country;

                    // Generate unique sighting ID from video ID
                    const sightingID = `youtube-${{video.video_id}}`;

                    // Escape function for CSV fields
                    const escape = (str) => `"${{(str || '').replace(/"/g, '""')}}"`;

                    // Build Wildbook CSV row
                    const row = [
                        escape(video.video_id),                 // observation_id
                        obsDate,                                 // observed_on
                        year,                                    // Encounter.year
                        month,                                   // Encounter.month
                        day,                                     // Encounter.day
                        escape(species),                         // scientific_name (from search)
                        '',                                      // Encounter.genus (empty - need parsing)
                        '',                                      // Encounter.specificEpithet (empty - need parsing)
                        escape(species),                         // common_name (from search)
                        latitude,                                // Encounter.decimalLatitude
                        longitude,                               // Encounter.decimalLongitude
                        escape(verbatimLocality),                // Encounter.verbatimLocality
                        '',                                      // Encounter.locationID (empty)
                        'alive',                                 // Encounter.livingStatus (assume alive)
                        escape(video.channel_title),             // Encounter.submitterID (channel)
                        'unapproved',                            // Encounter.state
                        sightingID,                              // Sighting.sightingID
                        escape(video.channel_title),             // observer (channel name)
                        'citizen',                               // quality_grade
                        video.url,                               // url
                        escape(notes),                           // Encounter.researcherComments
                        '1',                                     // photo_count
                        '',                                      // photo_filenames (empty - video not downloaded)
                        video.url                                // Encounter.mediaAsset0 (YouTube URL)
                    ];

                    csv += row.join(',') + '\\n';
                }}
            }});

            document.getElementById('export-output').value = csv;
        }}

        // Update count when checkboxes change
        document.querySelectorAll('.video-checkbox').forEach(cb => {{
            cb.addEventListener('change', updateCount);
        }});
    </script>
</body>
</html>"""

    # Write HTML file
    output_file = Path(output_path)
    # Only create parent directory if it doesn't exist and isn't the current directory
    if output_file.parent != Path('.') and not output_file.parent.exists():
        output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return str(output_file)
