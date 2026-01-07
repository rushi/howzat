# Audio Recognizer

## Overview

The recognizer matches audio against stored ad fingerprints in the database. It generates fingerprints from incoming audio and performs hash-based matching with confidence scoring.

## How It Works

```
Audio Input → Generate Fingerprints → Match Against DB → Confidence Score → Result
```

### Matching Process

```python
# 1. Generate fingerprints from audio
result = fingerprint_audio(audio, sample_rate)
hashes = [fp.hash_value for fp in result.fingerprints]

# 2. Query database for matches
matches = db.find_matches(hashes, min_matches=5)

# 3. Calculate confidence for each ad
for ad_name, match_count in matches:
    confidence = match_count / len(hashes)  # Percentage of hashes matched

# 4. Return best match if above threshold
if best_confidence >= threshold:
    return RecognitionResult(ad_name, confidence, is_match=True)
else:
    return NoMatch()
```

## Recognition Results

### RecognitionResult (Match Found)

```python
@dataclass
class RecognitionResult:
    ad_name: str           # Which ad matched
    confidence: float      # 0.0 to 1.0 (e.g., 0.85 = 85% match)
    match_count: int       # Number of matching hashes
    is_match: bool         # Always True
```

### NoMatch (No Match)

```python
@dataclass
class NoMatch:
    total_hashes: int             # How many hashes were generated
    closest_match: str | None     # Best candidate (if any)
    closest_confidence: float     # Its confidence (below threshold)
```

## Usage

### Basic Recognition

```python
from core.recognizer import Recognizer
import numpy as np

recognizer = Recognizer()

# From raw audio
audio = np.array([...])
result = recognizer.recognize_audio(audio, sample_rate=44100)

if isinstance(result, RecognitionResult) and result.is_match:
    print(f"Detected: {result.ad_name} ({result.confidence:.0%})")
else:
    print("No ad detected")
```

### From Different Sources

```python
# From microphone
result = recognizer.recognize_from_mic(duration_seconds=5.0)

# From file
result = recognizer.recognize_file("audio.wav")

# From numpy array
result = recognizer.recognize_audio(audio, sample_rate=44100)
```

### With Confidence Threshold

```python
# Default threshold from config
recognizer = Recognizer()  # Uses settings.detection.confidence_threshold

# Override threshold
recognizer.set_confidence_threshold(0.7)  # Require 70% match
```

## Confidence Scoring

Confidence is calculated as:

```python
confidence = matching_hashes / total_hashes_in_audio
```

**Example**:
- Audio generates 7,500 hashes
- 6,000 match "Dream11-Ad" 
- Confidence = 6,000 / 7,500 = **0.80 (80%)**

### What Affects Confidence?

**Higher confidence**:
- Clean audio (no background noise)
- Exact ad match
- Full coverage (entire ad in window)
- Good recording quality

**Lower confidence**:
- Background noise/mixing
- Partial ad (only 2s of 30s ad in window)
- Different audio source (TV vs stream)
- Poor microphone quality

## Database Matching

The database uses indexed hash lookup:

```python
# src/db/database.py
def find_matches(
    self, 
    hashes: list[str], 
    min_matches: int = 5
) -> list[tuple[str, int, float]]:
    """
    Find ads matching the given hashes.
    
    Returns: [(ad_name, match_count, confidence), ...]
    Sorted by confidence (best first)
    """
```

**min_matches=5**: Ignores ads with <5 matching hashes (reduces false positives)

### SQL Query

```sql
SELECT 
    ad_name,
    COUNT(*) as match_count
FROM fingerprints
WHERE hash IN (?, ?, ?, ...)  -- 7500+ hashes
GROUP BY ad_name
HAVING match_count >= 5       -- min_matches
ORDER BY match_count DESC
```

## Configuration

```yaml
detection:
  confidence_threshold: 0.6   # 60% match required
```

### Threshold Tuning

**Stricter** (fewer false positives):
```yaml
confidence_threshold: 0.75   # 75% match
```
⚠️ May miss ads in noisy environments

**Lenient** (better noise tolerance):
```yaml
confidence_threshold: 0.5    # 50% match
```
⚠️ May trigger false positives

**Recommended**: 0.6 - 0.7 (good balance)

## Integration with Listener

```python
from core.listener import ContinuousListener
from core.recognizer import Recognizer
from core.ad_detector import AdDetector

recognizer = Recognizer()
detector = AdDetector()
listener = ContinuousListener()

def on_recognition(result):
    # Recognizer returns RecognitionResult | NoMatch
    # Detector processes and manages state
    event = detector.process_recognition(result)
    
    if event:
        print(f"Event: {event.event_type.name}")

listener.start(on_recognition=on_recognition)
```

## Example Results

### Strong Match
```python
RecognitionResult(
    ad_name="Dream11-Ad",
    confidence=0.85,        # 85% of hashes matched
    match_count=6375,       # 6375 / 7500 hashes
    is_match=True
)
```

### Weak Match (Below Threshold)
```python
NoMatch(
    total_hashes=7500,
    closest_match="PhonePe-Ad",
    closest_confidence=0.45   # Only 45%, below 60% threshold
)
```

### No Match at All
```python
NoMatch(
    total_hashes=7200,
    closest_match=None,       # No ads had even min_matches
    closest_confidence=0.0
)
```

## Error Handling

The recognizer is defensive:

```python
# Empty fingerprints
if not result.fingerprints:
    return NoMatch(total_hashes=0)

# No database matches
if not matches:
    return NoMatch(total_hashes=len(hashes))

# Threshold not met
if best_confidence < self.confidence_threshold:
    return NoMatch(
        total_hashes=len(hashes),
        closest_match=best_name,
        closest_confidence=best_confidence
    )
```

## Performance

**Per recognition** (5s audio):
- Generate fingerprints: ~0.3s
- Database lookup: ~0.1s
- **Total**: ~0.4s

**Database size impact**:
- Small (10 ads): 0.1s lookup
- Medium (50 ads): 0.2s lookup
- Large (100+ ads): 0.3s lookup

Scales well with indexed hash lookups.

## Best Practices

1. **Reuse recognizer instance**: Database connection is cached
2. **Adjust threshold for environment**: Lower for noisy, higher for clean
3. **Check result type**: Use `isinstance()` or check `is_match` attribute
4. **Monitor confidence**: Log when close to threshold (debugging)

## Testing

```python
# Test with known ad
audio = load_audio("dream11-ad.wav")
result = recognizer.recognize_audio(audio, sample_rate=44100)

assert isinstance(result, RecognitionResult)
assert result.ad_name == "Dream11-Ad"
assert result.confidence > 0.6

# Test with non-ad audio
audio = load_audio("music.wav")
result = recognizer.recognize_audio(audio, sample_rate=44100)

assert isinstance(result, NoMatch)
```
