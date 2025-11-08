#!/usr/bin/env python3
"""Show detailed filtering results"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import YouTubeSearcher, evaluate_wild_sighting_likelihood
import os

# Set API key
os.environ['YOUTUBE_API_KEY'] = os.environ.get('YOUTUBE_API_KEY', '')

# Search for whale sharks
searcher = YouTubeSearcher()
videos = searcher.search_videos(
    species_query="whale shark",
    days_back=7,
    max_results=50
)

print(f"=" * 80)
print(f"STRICT FILTERING RESULTS: {len(videos)} videos analyzed")
print(f"=" * 80)

accepted = []
rejected = []

for video in videos:
    eval_result = evaluate_wild_sighting_likelihood(video)
    if eval_result['is_likely_wild']:
        accepted.append((video, eval_result))
    else:
        rejected.append((video, eval_result))

print(f"\n✅ ACCEPTED ({len(accepted)} videos - likely citizen science value):")
print("=" * 80)
for video, eval_result in sorted(accepted, key=lambda x: x[1]['score'], reverse=True):
    print(f"\n[{eval_result['score']}%] {video['title'][:70]}")
    print(f"    Channel: {video['channel_title']}")
    print(f"    Reasons: {', '.join(eval_result['reasons'][:3])}")

print(f"\n\n❌ REJECTED ({len(rejected)} videos - not citizen science):")
print("=" * 80)
for video, eval_result in sorted(rejected, key=lambda x: x[1]['score'], reverse=True)[:10]:
    print(f"\n[{eval_result['score']}%] {video['title'][:70]}")
    print(f"    Reasons: {', '.join(eval_result['reasons'][:2])}")

print(f"\n" + "=" * 80)
print(f"SUMMARY: {len(accepted)}/{len(videos)} videos passed strict filtering ({len(accepted)*100/len(videos):.1f}%)")
print(f"=" * 80)
