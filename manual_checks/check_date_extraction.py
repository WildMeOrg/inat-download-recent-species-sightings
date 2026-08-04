#!/usr/bin/env python3
"""Test observation date extraction with various formats"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import extract_observation_date

test_videos = [
    {
        'title': '7th Oct whale shark diving',
        'description': 'Amazing dive',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '2025-10-07',
        'type': 'Full date'
    },
    {
        'title': 'Whale shark encounter Nov 5 2025',
        'description': '',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '2025-11-05',
        'type': 'Full date'
    },
    {
        'title': 'Yesterday we saw a whale shark!',
        'description': 'It was amazing',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '2025-11-06',
        'type': 'Relative date'
    },
    {
        'title': 'Whale shark diving trip',
        'description': 'Great experience last week',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '2025-10-31',
        'type': 'Relative date'
    },
    {
        'title': 'Whale sharks in October 2025',
        'description': 'Great month for sightings',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '2025-10',
        'type': 'Year-Month only'
    },
    {
        'title': 'NINDY | TRIP TO WHALE SHARK | EMPANG KAB. JAMBU | SUMBAWA | 2025',
        'description': '',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '2025',
        'type': 'Year only'
    },
    {
        'title': 'Amazing whale shark',
        'description': 'Check out this video',
        'published_at': '2025-11-07T12:00:00Z',
        'expected': '',
        'type': 'No date'
    }
]

print("=" * 80)
print("TESTING OBSERVATION DATE EXTRACTION")
print("=" * 80)

for i, video in enumerate(test_videos, 1):
    result = extract_observation_date(video)
    expected = video['expected']
    status = "✓" if result == expected else "✗"

    print(f"\n{status} Test {i} - {video['type']}:")
    print(f"  Title: {video['title']}")
    print(f"  Description: {video['description']}")
    print(f"  Published: {video['published_at'][:10]}")
    print(f"  Expected: '{expected}'")
    print(f"  Got:      '{result}'")

    if result != expected:
        print(f"  ❌ MISMATCH!")

print("\n" + "=" * 80)
print("KEY INSIGHTS:")
print("  • Supports partial dates (year-only, year-month, full date)")
print("  • Empty string = No date found (prevents using upload date)")
print("  • CSV export will populate year/month/day fields based on what's available")
print("=" * 80)
