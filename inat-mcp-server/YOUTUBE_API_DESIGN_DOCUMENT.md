# YouTube API Integration Design Document
## Wildlife Research Data Aggregation Platform

**Project Name:** iNaturalist-Wildbook MCP Server
**Application Type:** Wildlife Conservation Research Tool
**API Usage:** YouTube Data API v3
**Date:** November 2024
**Version:** 1.0

---

## Executive Summary

This document describes the integration of YouTube Data API v3 into an open-source wildlife conservation research platform that aggregates citizen science data for mark-recapture population studies. The platform combines structured observation data from iNaturalist with unstructured video data from YouTube to provide researchers with comprehensive wildlife sighting information.

**Purpose:** Enable wildlife researchers to discover and analyze video documentation of endangered species uploaded by tourists, divers, and nature enthusiasts worldwide.

**Impact:** Supports conservation efforts for threatened species by increasing data availability for photo-identification and population monitoring studies.

---

## 1. Project Background

### 1.1 Conservation Context

Wildlife researchers conducting mark-recapture studies rely on photo-identification of individual animals to:
- Estimate population sizes
- Track migration patterns
- Monitor species health
- Identify conservation priorities

Traditional data sources (scientific surveys, camera traps) are expensive and limited in geographic scope. Citizen science platforms like iNaturalist have democratized data collection, but valuable sighting data also exists in tourist/diver videos on YouTube.

### 1.2 Data Gap

**Problem:** Millions of wildlife encounter videos are uploaded to YouTube annually, but researchers lack tools to systematically discover and process this data.

**Solution:** Integrate YouTube search capabilities into our existing wildlife research platform to automatically discover relevant video content.

### 1.3 Target Species

Our platform supports research on any species, with current focus on:
- **Marine megafauna:** Whale sharks (Rhincodon typus), manta rays, sea turtles
- **Terrestrial megafauna:** Jaguars (Panthera onca), lions (Panthera leo), elephants
- **Cetaceans:** Dolphins, whales (dorsal fin identification)
- **Any species** where photo-ID is viable

---

## 2. Technical Architecture

### 2.1 System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Researcher (User)                         │
│              Natural Language Interface                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              Claude AI (MCP Client)                          │
│   • Interprets research queries                             │
│   • Orchestrates multi-source searches                      │
│   • Combines and formats results                            │
└──────────────────────┬──────────────────────────────────────┘
                       │ MCP Protocol
                       ↓
┌─────────────────────────────────────────────────────────────┐
│         MCP Server (iNaturalist-Wildbook)                    │
│                                                              │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │ iNaturalist Tools│         │  YouTube Tools   │         │
│  │ • Structured obs │         │  • Video search  │         │
│  │ • Photo download │         │  • Multi-language│         │
│  │ • Geo filtering  │         │  • Metadata only │         │
│  └────────┬─────────┘         └────────┬─────────┘         │
└───────────┼───────────────────────────┼───────────────────┘
            │                           │
            ↓                           ↓
   ┌─────────────────┐        ┌─────────────────┐
   │ iNaturalist API │        │  YouTube Data   │
   │                 │        │    API v3       │
   └─────────────────┘        └─────────────────┘
```

### 2.2 MCP Server Architecture

**Technology Stack:**
- Language: Python 3.12
- Protocol: Model Context Protocol (MCP) - Anthropic's standard for AI tool integration
- API Client: Python stdlib (urllib, json) - no external dependencies
- Deployment: Local stdio-based server

**Integration Points:**
1. **Input:** Natural language queries from researchers via Claude AI
2. **Processing:** MCP server translates to YouTube API calls
3. **Output:** Structured video metadata returned to researcher

### 2.3 YouTube API Usage

**API Endpoints Used:**
- `search.list` - Primary endpoint for video discovery
  - Part: snippet
  - Type: video
  - Filters: publishedAfter, relevanceLanguage, videoEmbeddable

**Data Retrieved (Metadata Only):**
- Video ID, title, description
- Channel name and ID
- Upload date
- Thumbnail URLs
- **No video downloads** - only metadata

**Data NOT Retrieved:**
- Video files (streaming or download)
- User personal information
- Comments or engagement metrics
- Recommendation algorithms

---

## 3. Use Cases and Workflow

### 3.1 Primary Use Case: Species Monitoring

**Scenario:** Marine biologist studying whale shark population in the Maldives

**Workflow:**
1. Researcher asks: *"Find whale shark videos from the Maldives uploaded this week"*
2. Claude AI interprets intent
3. MCP server calls YouTube API:
   ```
   search.list(
     q="whale shark Maldives",
     publishedAfter=<7 days ago>,
     type=video,
     maxResults=50
   )
   ```
4. Results returned with video URLs
5. Researcher manually reviews videos in browser
6. If useful, researcher extracts frames for photo-ID analysis
7. Individual whale sharks identified and added to Wildbook database

**API Calls:** 1 search = ~100 quota units

### 3.2 Multi-Language Discovery

**Scenario:** Global whale shark research requiring international data

**Workflow:**
1. Researcher asks: *"Search for whale shark videos in English, Spanish, French, Chinese, and Arabic from the last month"*
2. MCP server makes 5 sequential searches (one per language):
   - English: "whale shark"
   - Spanish: "tiburón ballena"
   - French: "requin-baleine"
   - Chinese: "鲸鲨"
   - Arabic: "قرش الحوت"
3. Results deduplicated by video ID
4. Combined multilingual report generated

**API Calls:** 5 searches = ~500 quota units

### 3.3 Automated Daily Monitoring

**Scenario:** Research program monitoring multiple species

**Workflow:**
1. Scheduled job runs daily at 9 AM UTC
2. Searches for new videos (last 24 hours) for:
   - 10 target species
   - 3 languages each (scientific name + 2 common names)
3. Generates daily report of new wildlife videos
4. Researchers review and select relevant videos

**API Calls:** 10 species × 3 languages = 30 searches = ~3,000 quota units per day

### 3.4 Geographic Hotspot Analysis

**Scenario:** Identify regions with high wildlife activity

**Workflow:**
1. Researcher asks: *"Where are the most jaguar videos coming from this year?"*
2. Broad search for jaguar videos (last 365 days)
3. Parse video descriptions for location mentions
4. Aggregate by region
5. Generate heat map of activity

**API Calls:** 1 search with 50 results = ~100 quota units

---

## 4. Expected Usage Patterns

### 4.1 Current Usage (10,000 units/day)

**Limitations:**
- ~100 searches per day
- Supports 1-2 active research projects
- Limited to English-only searches
- No automated daily monitoring
- Insufficient for multi-species studies

### 4.2 Requested Quota: 100,000 units/day

**Justification:**

| Use Case | Searches/Day | Units/Day | Notes |
|----------|-------------|-----------|-------|
| Daily monitoring (10 species × 3 languages) | 30 | 3,000 | Automated |
| Manual researcher queries (20 searches) | 20 | 2,000 | Ad-hoc research |
| Multi-language discovery (10 species × 5 languages) | 50 | 5,000 | Weekly deep dive |
| Geographic analysis (5 regions × 3 species) | 15 | 1,500 | Monthly analysis |
| Historical backfill (100 searches) | 100 | 10,000 | One-time/occasional |
| **Buffer for growth** | - | 78,500 | Support 5-10 research groups |
| **Total** | ~215 | **100,000** | Sustainable daily usage |

### 4.3 Growth Projections

**Year 1 (Current):**
- 3-5 active research groups
- 10-15 target species
- English + Spanish + French

**Year 2 (Projected):**
- 10-15 active research groups
- 30-50 target species
- Add Chinese, Portuguese, Arabic, Japanese
- Integration with 5+ universities

**Year 3 (Projected):**
- 20+ active research groups
- 100+ target species
- Global coverage (10+ languages)
- Potential citizen science volunteer access

---

## 5. Data Handling and Privacy

### 5.1 Data Collection

**What We Collect:**
- Public video metadata (title, description, upload date)
- Video URLs and thumbnail URLs
- Channel names (public information)

**What We DON'T Collect:**
- Video files or streams
- User personal information
- Email addresses or contact information
- Viewing history or engagement data
- Comments or user interactions

### 5.2 Data Storage

- **Metadata storage:** Temporary (24-48 hours)
- **URLs storage:** Persistent (for research reference)
- **No video downloads:** Videos remain on YouTube
- **User data:** None collected

### 5.3 Data Usage

**Purpose:** Wildlife conservation research only

**Access:**
- Restricted to registered researchers
- No public API or data reselling
- No commercial use

**Compliance:**
- YouTube Terms of Service: ✅ Compliant (metadata only, no scraping)
- GDPR: ✅ N/A (no personal data collected)
- Research ethics: ✅ Public data, conservation purpose

---

## 6. Benefits to YouTube Community

### 6.1 Content Discovery

**Value to Content Creators:**
- Wildlife videos gain visibility in research community
- Potential citation in scientific papers
- Increased views from researcher sharing
- Recognition of conservation contribution

### 6.2 Conservation Impact

**Social Good:**
- Tourist videos contribute to species protection
- Divers' casual footage becomes scientific data
- Citizen science democratization
- Raises awareness of endangered species

### 6.3 Platform Enhancement

**YouTube Ecosystem:**
- Demonstrates educational/scientific value of user content
- Showcases YouTube as research data source
- Potential partnerships with conservation organizations
- Positive PR for wildlife content

---

## 7. Technical Implementation Details

### 7.1 API Call Optimization

**Efficiency Measures:**
1. **Caching:** Results cached for 24 hours to avoid duplicate searches
2. **Deduplication:** Video IDs tracked to prevent redundant API calls
3. **Batch Processing:** Multiple species searched in sequence, not parallel
4. **Smart Filtering:** Use `publishedAfter` to limit search scope
5. **Rate Limiting:** 1-second delay between calls (self-imposed)

### 7.2 Error Handling

```python
# Graceful degradation
try:
    videos = search_youtube(species, days_back=7)
except QuotaExceeded:
    log_error("Quota exceeded, deferring search")
    schedule_retry(next_day)
except APIError as e:
    log_error(f"API error: {e}")
    notify_admin()
```

### 7.3 Quota Management

**Monitoring:**
- Daily quota usage tracked
- Alerts at 80% usage
- Automatic throttling at 90%
- Graceful degradation at 100%

**Distribution:**
- Research groups allocated quota share
- Priority queue for time-sensitive searches
- Batch jobs scheduled during off-peak hours

---

## 8. Alternative Approaches Considered

### 8.1 Web Scraping (Rejected)

**Why Not:**
- Violates YouTube ToS
- Unreliable (page structure changes)
- No official support
- Risk of IP blocking

### 8.2 Manual Search (Current Limitation)

**Why Inadequate:**
- Not scalable for multiple species
- Language barriers limit coverage
- Time-consuming for researchers
- Inconsistent results

### 8.3 Third-Party Aggregators (Rejected)

**Why Not:**
- Additional cost
- Data freshness delays
- Limited customization
- Privacy concerns

**Conclusion:** YouTube Data API v3 is the only viable, compliant, and effective solution.

---

## 9. Success Metrics

### 9.1 Research Impact

**Target Metrics (Year 1):**
- 500+ wildlife videos discovered monthly
- 10+ research papers citing platform data
- 5+ endangered species benefiting from increased data
- 20+ new individual animals identified via YouTube footage

### 9.2 Platform Usage

**Target Metrics:**
- 100+ daily API calls
- 50% of searches yielding actionable results
- 80% researcher satisfaction rate
- <5% wasted API calls (irrelevant results)

### 9.3 Conservation Outcomes

**Long-term Goals:**
- Contribute to IUCN Red List assessments
- Support marine protected area planning
- Identify wildlife trafficking hotspots
- Document rare species sightings

---

## 10. Project Governance


**Maintainers:**
- Wildlife research software engineers @ Conservation X Labs
- Conservation biologists
- Citizen science coordinators


---

## 11. Compliance and Responsible Use

### 11.1 YouTube Terms of Service

**Compliance Checklist:**
- ✅ Using official API (not scraping)
- ✅ Respecting rate limits
- ✅ Not downloading videos
- ✅ Not circumventing access controls
- ✅ Attributing content to creators
- ✅ Not using for spam or abuse
- ✅ Educational/research purpose
- ✅ No commercial exploitation

### 11.2 API Key Security

**Security Measures:**
- API keys stored as environment variables
- No hardcoding in source code
- Access restricted to server process
- Regular key rotation
- Audit logs maintained

### 11.3 Ethical Use

**Principles:**
1. **Conservation First:** All usage serves wildlife protection
2. **Creator Respect:** Credit given to video creators
3. **No Exploitation:** Non-commercial, research-only
4. **Transparency:** Open-source, auditable code
5. **Privacy:** No personal data collection

---

## 12. Conclusion

### 12.1 Summary

This YouTube API integration enables wildlife researchers worldwide to discover and utilize valuable citizen science video data for conservation purposes. By systematically searching YouTube for wildlife encounter videos, we transform casual tourist footage into scientific data supporting endangered species protection.

### 12.2 Quota Justification

**Current Limit (0 units/day):**
- No automation possible

**Requested Quota (100,000 units/day):**
- Supports 1 account
- ~1,000 searches/day
- Multi-language (5+ languages)
- Enables automated daily monitoring
- Scales with conservation needs

### 12.3 Impact Statement

Increasing our YouTube API quota directly translates to:
- **More species monitored:** 10x increase in species coverage
- **Better data quality:** Multi-language searches capture global sightings
- **Faster discovery:** Automated daily monitoring provides real-time awareness
- **Greater conservation impact:** More data enables better protection decisions

We respectfully request a quota increase to 100,000 units/day to support our mission of leveraging citizen science video data for wildlife conservation research.



## Appendices

### Appendix A: Example API Calls

**Single Species Search:**
```
GET https://www.googleapis.com/youtube/v3/search
  ?part=snippet
  &q=whale+shark
  &type=video
  &publishedAfter=2024-11-01T00:00:00Z
  &maxResults=25
  &key=[API_KEY]
```

**Multi-Language Search (Automated):**
```python
for language, term in species_terms.items():
    search_youtube(
        query=term,
        published_after=yesterday,
        max_results=10
    )
```

