#!/usr/bin/env python3
"""Test if Apex Realms video is properly filtered out"""

import sys
sys.path.insert(0, '/mnt/c/inat-download-recent-species-sightings/inat-mcp-server')

from youtube_tools import evaluate_wild_sighting_likelihood

# Simulate the Apex Realms video
apex_realms_video = {
    'video_id': 'CqypdJMpRuI',
    'title': 'Whale Shark Feeds Vertically Creating Glowing Plankton Tornado While Divers Watch in Awe',
    'description': 'Adult scuba divers on guided tour witness magical moment when massive whale shark positions itself completely vertical in water column and begins filter feeding, creating a spectacular glowing tornado of bioluminescent plankton spiraling into its mouth. The shark then makes eye contact with divers before performing an even larger vertical feeding display with multiple rotations.',
    'channel_title': 'Apex Realms',
    'channel_id': 'UCKvE37aBMdDY4ajyBO16qUA',
    'published_at': '2025-11-08T00:21:50Z'
}

print("=" * 80)
print("TESTING APEX REALMS AI-GENERATED VIDEO FILTERING")
print("=" * 80)

eval_result = evaluate_wild_sighting_likelihood(apex_realms_video)

print(f"\n📹 VIDEO: {apex_realms_video['title']}")
print(f"📺 CHANNEL: {apex_realms_video['channel_title']}")
print(f"\n🎯 CONFIDENCE SCORE: {eval_result['score']}%")
print(f"✅ LIKELY WILD: {eval_result['is_likely_wild']}")
print(f"❌ INCLUDED IN REPORT (>90%): {'YES' if eval_result['score'] > 90 else 'NO'}")

print(f"\n📊 FILTERING REASONS:")
for reason in eval_result['reasons']:
    print(f"  • {reason}")

print("\n" + "=" * 80)
if eval_result['score'] <= 90:
    print("✓ SUCCESS: AI-generated video properly EXCLUDED from report")
else:
    print("✗ FAILURE: AI-generated video would be INCLUDED (needs stricter filtering)")
print("=" * 80)
