#!/usr/bin/env python3
"""Test the new filtering functionality"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import YouTubeSearcher, generate_html_report
import os

# Set API key
os.environ['YOUTUBE_API_KEY'] = os.environ.get('YOUTUBE_API_KEY', '')

# Search for whale sharks
searcher = YouTubeSearcher()
print("Searching for whale shark videos from past 7 days...")
videos = searcher.search_videos(
    species_query="whale shark",
    days_back=7,
    max_results=50
)

print(f"\nFound {len(videos)} videos")

# Generate HTML report with filtering
output_path = "/mnt/c/inat-download-recent-species-sightings/data/youtube_reports/whale_shark_filtered_test.html"
search_params = {
    'species': 'whale shark',
    'days_back': 7
}

print(f"\nGenerating filtered HTML report...")
html_path = generate_html_report(videos, output_path, search_params)

print(f"✓ Report generated: {html_path}")
print("\nFiltering summary:")

# Show filtering results
from youtube_tools import evaluate_wild_sighting_likelihood

wild_count = 0
for video in videos:
    eval_result = evaluate_wild_sighting_likelihood(video)
    if eval_result['is_likely_wild']:
        wild_count += 1
        print(f"  ✓ {video['title'][:60]}... (score: {eval_result['score']}%)")

print(f"\n{wild_count}/{len(videos)} videos marked as likely wild sightings")
