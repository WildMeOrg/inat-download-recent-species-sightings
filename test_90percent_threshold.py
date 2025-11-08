#!/usr/bin/env python3
"""Test 90% confidence threshold with date/location extraction"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import YouTubeSearcher, generate_html_report, evaluate_wild_sighting_likelihood, extract_observation_date, extract_location
import os

# Set API key
os.environ['YOUTUBE_API_KEY'] = os.environ.get('YOUTUBE_API_KEY', '')

# Search for whale sharks
searcher = YouTubeSearcher()
print("=" * 80)
print("TESTING 90% CONFIDENCE THRESHOLD + DATE/LOCATION EXTRACTION")
print("=" * 80)
print("\nSearching for whale shark videos from past 7 days...")
videos = searcher.search_videos(
    species_query="whale shark",
    days_back=7,
    max_results=50
)

print(f"Found {len(videos)} videos from YouTube API")

# Analyze filtering
accepted_90 = []
accepted_50 = []
rejected = []

for video in videos:
    eval_result = evaluate_wild_sighting_likelihood(video)
    if eval_result['score'] > 90:
        accepted_90.append((video, eval_result))
    elif eval_result['score'] > 50:
        accepted_50.append((video, eval_result))
    else:
        rejected.append((video, eval_result))

print(f"\n📊 FILTERING RESULTS:")
print("=" * 80)
print(f"Videos >90% confidence (INCLUDED in report): {len(accepted_90)}")
print(f"Videos 51-90% confidence (EXCLUDED): {len(accepted_50)}")
print(f"Videos ≤50% confidence (EXCLUDED): {len(rejected)}")
print(f"Total excluded: {len(accepted_50) + len(rejected)}")

print(f"\n✅ VIDEOS INCLUDED IN REPORT (>90% confidence):")
print("=" * 80)
for video, eval_result in sorted(accepted_90, key=lambda x: x[1]['score'], reverse=True):
    obs_date = extract_observation_date(video)
    location = extract_location(video)

    print(f"\n[{eval_result['score']}%] {video['title'][:60]}")
    print(f"    Channel: {video['channel_title']}")
    print(f"    Published: {video['published_at'][:10]}")
    print(f"    Obs Date (extracted): {obs_date}")
    if location.get('place_name') or location.get('country'):
        place = location.get('place_name', '')
        country = location.get('country', '')
        loc_str = f"{place}{', ' + country if place and country else country}"
        print(f"    Location (extracted): {loc_str}")
        if location.get('latitude') and location.get('longitude'):
            print(f"    Coordinates: {location['latitude']:.4f}, {location['longitude']:.4f}")
    print(f"    Confidence reasons: {', '.join(eval_result['reasons'][:2])}")

print(f"\n⚠️  VIDEOS EXCLUDED (51-90% confidence - would have been included at old threshold):")
print("=" * 80)
for video, eval_result in sorted(accepted_50, key=lambda x: x[1]['score'], reverse=True)[:5]:
    print(f"  [{eval_result['score']}%] {video['title'][:65]}")

# Generate HTML report
output_path = "/mnt/c/inat-download-recent-species-sightings/data/youtube_reports/whale_shark_90_percent.html"
search_params = {
    'species': 'whale shark',
    'days_back': 7
}

print(f"\n📄 Generating HTML report with Wildbook CSV export...")
html_path = generate_html_report(videos, output_path, search_params)

print(f"\n" + "=" * 80)
print(f"✓ HTML REPORT: {html_path}")
print(f"  - Only {len(accepted_90)} high-confidence videos included (>90%)")
print(f"  - Dates and locations auto-extracted")
print(f"  - CSV export uses Wildbook format")
print(f"  - View at: http://localhost:8000/{os.path.basename(html_path)}")
print("=" * 80)
