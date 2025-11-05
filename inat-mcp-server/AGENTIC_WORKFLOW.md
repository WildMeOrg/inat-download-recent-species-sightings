# Agentic AI Workflow Architecture

## Overview

This MCP server transforms your iNaturalist-Wildbook tool into an **autonomous AI agent capability**, enabling Claude and other AI assistants to intelligently download, filter, and prepare wildlife observation data for mark-recapture studies.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     USER / RESEARCHER                        │
│  "Download jaguar observations from Brazil last 30 days"    │
└──────────────────────────┬──────────────────────────────────┘
                           │ Natural Language
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE AI ASSISTANT                       │
│  • Understands intent                                        │
│  • Selects appropriate tools                                 │
│  • Orchestrates multi-step workflows                         │
│  • Provides human-readable summaries                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ MCP (Model Context Protocol)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    MCP SERVER (server.py)                    │
│                                                              │
│  Tools Available:                                            │
│  ┌────────────────────────────────────────────────┐         │
│  │ 1. download_observations                       │         │
│  │    • Multi-species support                     │         │
│  │    • Geographic filtering                      │         │
│  │    • Date range filtering                      │         │
│  │    • Quality control filters                   │         │
│  │    • HTML review generation                    │         │
│  │    • Social species splitting                  │         │
│  └────────────────────────────────────────────────┘         │
│  ┌────────────────────────────────────────────────┐         │
│  │ 2. get_recent_species_summary                  │         │
│  │    • Quick observation counts                  │         │
│  │    • Quality grade distribution                │         │
│  │    • Location statistics                       │         │
│  └────────────────────────────────────────────────┘         │
│  ┌────────────────────────────────────────────────┐         │
│  │ 3. list_place_suggestions                      │         │
│  │    • Geographic name resolution                │         │
│  │    • Place type identification                 │         │
│  └────────────────────────────────────────────────┘         │
└──────────────────────────┬──────────────────────────────────┘
                           │ Python API Calls
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              iNaturalistDownloader (Core Tool)               │
│  • API integration                                           │
│  • Photo downloading                                         │
│  • GIF frame extraction                                      │
│  • CSV generation                                            │
│  • HTML review interface                                     │
│  • Smart filtering logic                                     │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS API
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    iNaturalist API                           │
│  • Observation data                                          │
│  • Photo downloads                                           │
│  • Taxonomy lookup                                           │
│  • Place resolution                                          │
└─────────────────────────────────────────────────────────────┘
```

## Agentic Capabilities

### 1. **Intent Understanding**

Claude can understand complex, multi-faceted requests:

**User says:** "I'm studying jaguars in the Pantanal wetlands. Get me recent observations."

**Claude interprets:**
- Species: Panthera onca (resolves "jaguars" to scientific name)
- Location: Need to find "Pantanal" places
- Timeframe: "recent" = last 30 days (reasonable default)
- Output: HTML review (best for researcher curation)

**Actions taken:**
1. `list_place_suggestions("Pantanal")` - Find matching places
2. `download_observations(species=["Panthera onca"], place="Pantanal", days_back=30)`

### 2. **Multi-Step Workflow Orchestration**

Claude can chain multiple tools together intelligently:

**Example Workflow:**
```
User: "Find good places to look for jaguars in Brazil, check recent
       activity, and if there are more than 20 observations, download them"

Claude's Plan:
1. list_place_suggestions("Brazil") → Get major jaguar habitat regions
2. For each region:
   - get_recent_species_summary("jaguar", place=region)
   - If count > 20: download_observations(...)
3. Summarize findings
```

### 3. **Context-Aware Filtering**

Claude understands research requirements and applies appropriate filters:

**User:** "Download observations for my photo-ID study"

**Claude infers:**
- Need high-quality photos → Filter "needs_id" quality
- Need proper licensing → Auto-deselect unlicensed
- Need individual animals → Filter out non-organism evidence
- Need alive animals → Filter out skulls/bones

### 4. **Adaptive Parameter Selection**

Claude chooses optimal parameters based on context:

| User Request | Claude's Decision | Reasoning |
|--------------|-------------------|-----------|
| "Recent observations" | `days_back=30` | Standard recency window |
| "This week's sightings" | `days_back=7` | Literal interpretation |
| "Social species like dolphins" | `social_split=true` | Enables multi-individual handling |
| "State-level tracking" | `location_id="{state}"` | Geographic standardization |

### 5. **Error Recovery and Guidance**

Claude can diagnose issues and suggest solutions:

**Scenario:** Place name not found

```
User: "Download jaguars from Pantanal"
Server: Error - Could not resolve place 'Pantanal'

Claude's Response:
"Let me search for places matching 'Pantanal'..."
[Uses list_place_suggestions]
"I found several Pantanal regions:
1. Pantanal, Mato Grosso, Brazil
2. Pantanal Matogrossense National Park, Brazil

Which would you like to use?"
```

## Advanced Agentic Workflows

### Workflow 1: Automated Data Quality Pipeline

```python
"Set up a weekly download pipeline for jaguar observations from
Mato Grosso, auto-filter low quality, and notify me of the count"
```

**Claude's execution:**
1. Check recent activity: `get_recent_species_summary()`
2. If observations exist: `download_observations()` with quality filters
3. Generate summary report
4. [Future] Schedule weekly repetition

### Workflow 2: Multi-Species Comparative Study

```python
"Compare recent observation counts for jaguars, pumas, and ocelots
across Brazilian states"
```

**Claude's execution:**
1. For each species:
   - For each major Brazilian state:
     - `get_recent_species_summary(species, place=state)`
2. Aggregate results into comparison table
3. Identify hotspots and trends

### Workflow 3: Cross-Platform Data Integration

```python
"Download dolphin observations from Israel, deduplicate against my
existing Wildbook database, and prepare import CSV"
```

**Claude's execution:**
1. `download_observations("Tursiops truncatus", place="Israel")`
2. [Future tool] Read existing Wildbook database
3. [Future tool] Compare observation IDs/dates/locations
4. Filter out duplicates
5. Generate final import CSV

### Workflow 4: Adaptive Temporal Analysis

```python
"Find the most active month for jaguar observations in the Pantanal
over the last year"
```

**Claude's execution:**
1. For each month in last 12 months:
   - `get_recent_species_summary()` with date range
2. Compare counts
3. Identify peak months
4. Optionally: Download observations from peak month

## Future Agentic Enhancements

### 1. **Computer Vision Integration**

Add CLIP-based tools for:
- Photo quality assessment
- Dorsal fin detection
- Individual feature extraction
- Duplicate photo detection

```python
# Future tool
"download_observations_with_ai_filtering"
- Uses CLIP to filter out low-quality photos
- Detects optimal identification views
- Scores photos for ID quality
```

### 2. **Wildbook Direct Integration**

```python
# Future tools
"upload_to_wildbook" - Direct upload via API
"check_wildbook_duplicates" - Pre-import deduplication
"match_individuals" - AI-assisted photo matching
```

### 3. **Scheduled Monitoring Agent**

```python
# Future capability
"Monitor iNaturalist daily for new jaguar observations in my study area
and auto-download research-grade observations"
```

Claude could:
- Run scheduled checks
- Maintain state (last observation ID seen)
- Only download new observations
- Send notifications when thresholds are met

### 4. **Research Project Management**

```python
# Future workflow
"Create a new research project for sea turtles in Costa Rica"
```

Claude could:
- Set up directory structure
- Configure default filters
- Download baseline observations
- Generate project documentation
- Track download history

### 5. **Data Quality Reporting**

```python
# Future tool
"analyze_observation_quality"
```

Claude could:
- Assess photo resolution
- Check GPS accuracy
- Identify missing metadata
- Score observations for research value
- Generate quality reports

## Benefits of Agentic Approach

### For Researchers:

1. **Natural Language Interface**
   - No need to remember command-line syntax
   - Describe intent, not implementation

2. **Contextual Understanding**
   - AI understands research domain
   - Applies appropriate filters automatically

3. **Workflow Automation**
   - Multi-step processes become single requests
   - Reduces manual data processing time

4. **Error Handling**
   - AI diagnoses and suggests fixes
   - Guides through complex scenarios

### For Research Programs:

1. **Standardization**
   - Consistent data collection protocols
   - Automated quality control

2. **Scalability**
   - Same effort for 1 species or 100
   - Easy to expand to new regions

3. **Reproducibility**
   - AI logs all decisions
   - Transparent filtering criteria

4. **Knowledge Transfer**
   - New researchers get AI guidance
   - Reduced training requirements

## Implementation Patterns

### Pattern 1: Exploratory Research

```
User: "I'm interested in studying species X in region Y"
AI: "Let me check recent activity..."
    [Uses get_recent_species_summary]
AI: "There are 47 observations. Would you like me to download them?"
User: "Yes, but only research-grade"
AI: "Downloading with quality filters..."
    [Uses download_observations with appropriate filters]
```

### Pattern 2: Ongoing Monitoring

```
User: "Download this week's observations for my ongoing study"
AI: [Recalls previous context]
    [Uses same species, place, filters as last time]
    [Compares to previous week's count]
AI: "This week: 23 observations (up from 18 last week)"
```

### Pattern 3: Bulk Processing

```
User: "Download observations for all species in my project list"
AI: [Reads species list from file or previous conversation]
    [Iterates through species]
    [Batches API calls to respect rate limits]
    [Generates combined report]
```

### Pattern 4: Comparative Analysis

```
User: "Which Brazilian state has the most jaguar observations this month?"
AI: [Gets list of major Brazilian states]
    [Queries each state in parallel]
    [Aggregates and ranks results]
    [Optionally downloads from top state]
```

## Security and Best Practices

### Rate Limiting

The MCP server respects iNaturalist API rate limits:
- Default: 1 second between calls
- Adjustable via `rate_limit` parameter
- Claude can increase delays if rate-limited

### Data Privacy

- Only public iNaturalist observations are accessed
- Respects observation licenses
- Does not collect user data beyond what's in observations

### Resource Management

- Photos stored locally (user controls)
- Configurable output directories
- Automatic cleanup of temporary files

## Getting Started

See **INSTALL.md** for setup instructions.

Once installed, try these progressive examples:

1. **Level 1 - Simple Query:**
   ```
   How many jaguar observations are there from Brazil this month?
   ```

2. **Level 2 - Basic Download:**
   ```
   Download those observations
   ```

3. **Level 3 - Filtered Download:**
   ```
   Download jaguar observations from Mato Grosso, research-grade only
   ```

4. **Level 4 - Complex Workflow:**
   ```
   Compare jaguar activity across Mato Grosso, Mato Grosso do Sul,
   and Pará in the last 60 days, then download observations from
   the most active state
   ```

5. **Level 5 - Research Pipeline:**
   ```
   Set up a monitoring system for my jaguar photo-ID project:
   download weekly observations from the Pantanal, split multi-photo
   observations, set location to the state level, and generate HTML
   reviews for my team to curate
   ```

## Conclusion

This MCP server bridges citizen science data (iNaturalist) and conservation research (Wildbook) through an intelligent AI agent that understands research workflows, automates repetitive tasks, and provides a natural language interface to complex data processing pipelines.

The agentic approach reduces the barrier to entry for researchers while maintaining scientific rigor through intelligent filtering, quality control, and transparent decision-making.
