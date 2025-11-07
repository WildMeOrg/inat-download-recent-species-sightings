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
