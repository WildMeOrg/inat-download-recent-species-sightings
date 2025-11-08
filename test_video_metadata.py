#!/usr/bin/env python3
"""Check what metadata YouTube API provides for altered/synthetic content"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import YouTubeSearcher
import os
import json

# Set API key
os.environ['YOUTUBE_API_KEY'] = os.environ.get('YOUTUBE_API_KEY', '')

searcher = YouTubeSearcher()

# Get detailed video info for the video with altered content label
video_id = "CqypdJMpRuI"

print("=" * 80)
print(f"CHECKING VIDEO METADATA FOR: {video_id}")
print("=" * 80)

try:
    video_details = searcher.get_video_details(video_id)

    print(f"\n📹 VIDEO DETAILS:")
    print(json.dumps(video_details, indent=2))

    # Check for any fields that might indicate altered/synthetic content
    snippet = video_details.get('snippet', {})
    content_details = video_details.get('contentDetails', {})
    status = video_details.get('status', {})

    print(f"\n🔍 LOOKING FOR ALTERED/SYNTHETIC CONTENT INDICATORS:")
    print("=" * 80)

    # Check common fields
    if 'contentRating' in content_details:
        print(f"Content Rating: {content_details['contentRating']}")

    if 'madeForKids' in status:
        print(f"Made for Kids: {status['madeForKids']}")

    if 'selfDeclaredMadeForKids' in status:
        print(f"Self Declared Made for Kids: {status['selfDeclaredMadeForKids']}")

    # Look for any AI/synthetic labels
    all_text = json.dumps(video_details).lower()

    ai_keywords = ['altered', 'synthetic', 'ai-generated', 'ai generated', 'artificial',
                   'digitally created', 'computer generated', 'deepfake']

    print(f"\n🤖 SEARCHING FOR AI/SYNTHETIC KEYWORDS IN METADATA:")
    for keyword in ai_keywords:
        if keyword in all_text:
            print(f"  ✓ Found: '{keyword}'")

    print(f"\n📝 TITLE: {snippet.get('title', 'N/A')}")
    print(f"📝 CHANNEL: {snippet.get('channelTitle', 'N/A')}")
    print(f"📝 DESCRIPTION (first 200 chars):\n{snippet.get('description', 'N/A')[:200]}")

except Exception as e:
    print(f"Error: {e}")
