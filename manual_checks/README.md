# Manual check scripts

These are diagnostic scripts, not automated tests. Each one calls a live API
(YouTube, and in some cases iNaturalist), needs credentials in the environment,
and reports by printing rather than asserting — results vary with whatever the
API returns that day.

They used to sit at the repo root named `test_*.py`, where pytest collected
them, hit `YouTubeSearcher()` at import time and aborted the whole run with
`ValueError: YouTube API key required` before any real test executed.

Run one directly:

    export YOUTUBE_API_KEY=...
    python3 manual_checks/check_filtering.py

The automated suite lives at the repo root and needs no network or keys:

    python3 -m pytest
