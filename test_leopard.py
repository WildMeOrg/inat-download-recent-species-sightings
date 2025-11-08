#!/usr/bin/env python3
"""Test leopard video filtering from Africa"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import YouTubeSearcher, generate_html_report
import os

# Set API key
os.environ['YOUTUBE_API_KEY'] = os.environ.get('YOUTUBE_API_KEY', '')

# Search for African leopard videos
searcher = YouTubeSearcher()
print("Searching for African leopard videos from past 7 days...")
videos = searcher.search_videos(
    species_query="leopard",
    days_back=7,
    max_results=50,
    additional_keywords=["Africa", "African", "wild", "safari"]
)

print(f"\nFound {len(videos)} videos")

# Generate HTML report with filtering
output_path = "/mnt/c/inat-download-recent-species-sightings/data/youtube_reports/leopard_africa_filtered.html"
search_params = {
    'species': 'African leopard',
    'days_back': 7
}

print(f"\nGenerating filtered HTML report...")
html_path = generate_html_report(videos, output_path, search_params)

print(f"✓ Report generated: {html_path}")
print("\nFiltering summary:")

# Show detailed filtering results
from youtube_tools import evaluate_wild_sighting_likelihood

accepted = []
rejected = []

for video in videos:
    eval_result = evaluate_wild_sighting_likelihood(video)
    if eval_result['score'] > 50:
        accepted.append((video, eval_result))
    else:
        rejected.append((video, eval_result))

print(f"\n✅ ACCEPTED ({len(accepted)} videos - included in report):")
print("=" * 80)
for video, eval_result in sorted(accepted, key=lambda x: x[1]['score'], reverse=True):
    print(f"  [{eval_result['score']}%] {video['title'][:65]}")

print(f"\n❌ EXCLUDED ({len(rejected)} videos - not in report):")
print("=" * 80)
for video, eval_result in sorted(rejected, key=lambda x: x[1]['score'], reverse=True)[:15]:
    reasons_str = ', '.join(eval_result['reasons'][:2]) if eval_result['reasons'] else 'No strong indicators'
    print(f"  [{eval_result['score']}%] {video['title'][:50]}...")
    print(f"      → {reasons_str}")

print(f"\n" + "=" * 80)
print(f"SUMMARY: {len(accepted)}/{len(videos)} videos in HTML report ({len(accepted)*100/len(videos):.1f}%)")
print(f"         {len(rejected)} videos excluded (≤50% confidence)")
print(f"=" * 80)
