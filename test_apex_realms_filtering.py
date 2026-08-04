#!/usr/bin/env python3
"""Regression test: the Apex Realms AI-generated video must stay out of reports.

This was previously a print-only script — it reported "✗ FAILURE" in its output
but always exited 0, so a regression here would never have failed a test run.
The fixture is a real video that prompted the AI-content filtering, and it needs
no API key or network: evaluate_wild_sighting_likelihood is a pure function of
the video metadata.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "inat-mcp-server"))

from youtube_tools import evaluate_wild_sighting_likelihood  # noqa: E402

# A real AI-generated video, kept verbatim as the fixture.
APEX_REALMS_VIDEO = {
    'video_id': 'CqypdJMpRuI',
    'title': 'Whale Shark Feeds Vertically Creating Glowing Plankton Tornado While Divers Watch in Awe',
    'description': (
        'Adult scuba divers on guided tour witness magical moment when massive whale shark '
        'positions itself completely vertical in water column and begins filter feeding, '
        'creating a spectacular glowing tornado of bioluminescent plankton spiraling into its '
        'mouth. The shark then makes eye contact with divers before performing an even larger '
        'vertical feeding display with multiple rotations.'
    ),
    'channel_title': 'Apex Realms',
    'channel_id': 'UCKvE37aBMdDY4ajyBO16qUA',
    'published_at': '2025-11-08T00:21:50Z',
}

# generate_html_report() only includes videos scoring above this.
REPORT_THRESHOLD = 90


def test_ai_generated_video_is_excluded_from_the_report():
    result = evaluate_wild_sighting_likelihood(APEX_REALMS_VIDEO)
    assert result['score'] <= REPORT_THRESHOLD, (
        f"AI-generated video scored {result['score']}% and would be included in the "
        f"report; reasons: {result['reasons']}"
    )


def test_the_ai_channel_is_what_triggers_the_exclusion():
    """Pin the reason, not just the score, so a coincidental pass is visible."""
    result = evaluate_wild_sighting_likelihood(APEX_REALMS_VIDEO)
    assert 'AI-generated content channel' in result['reasons'], result['reasons']


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
