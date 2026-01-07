# Ad Detection State Machine

## Overview

The `AdDetector` class manages the ad lifecycle using a state machine. It handles muting/unmuting, notifications, webhooks, and supports multiple unmute modes.

## State Machine

```
IDLE ──[match]──> AD_DETECTED ──> AD_PLAYING
                                      │
                    [3 consecutive    │ [match]
                     no-matches]      │ (reset counter)
                          │           │
                          ▼           │
                     AD_ENDING ◄──────┘
                          │
                    [unmute delay]
                          │
                          ▼
                        IDLE + UNMUTE
```

## States

### IDLE
- **Meaning**: No ad detected, audio unmuted
- **Actions on entry**: None
- **Transitions**: Match detected → AD_DETECTED

### AD_DETECTED
- **Meaning**: Ad just detected, transitioning (brief state)
- **Actions on entry**: 
  - Mute audio (save current volume)
  - Send notification
  - Call webhook
  - Emit `AD_STARTED` event
  - Start timer (for timer-based unmute modes)
- **Transitions**: Immediately → AD_PLAYING

### AD_PLAYING
- **Meaning**: Ad is playing, system muted
- **Actions on entry**: None
- **Transitions**:
  - Match → Stay in AD_PLAYING (reset no-match counter)
  - No match (detection mode) → Increment counter
  - 3+ no-matches (detection mode) → AD_ENDING

### AD_ENDING
- **Meaning**: Ad likely ended, waiting for unmute delay
- **Actions on entry**: Start unmute timer (delay_seconds)
- **Transitions**:
  - Match detected → Back to AD_PLAYING (false alarm)
  - Timer expires → IDLE + unmute

## Unmute Modes

### 1. Timer Mode (default)
```yaml
unmute:
  mode: timer
  timer_seconds: 30
```
- Fixed duration after ad detection
- Starts timer immediately when ad detected
- Ignores subsequent matches/no-matches

### 2. Detection Mode
```yaml
unmute:
  mode: detection
  delay_seconds: 2
```
- Unmutes when ad stops matching
- Requires 3 consecutive no-matches
- Adds small delay before unmuting (prevents false unmute)

### 3. Configurable Mode
```yaml
unmute:
  mode: configurable
  timer_seconds: 45
```
- Like timer mode but user sets duration
- Useful if ads have consistent length

### 4. Manual Mode
```yaml
unmute:
  mode: manual
```
- Never unmutes automatically
- User must call `detector.force_unmute()` or press hotkey

## Event System

The detector emits events for external observers:

```python
@dataclass
class AdEvent:
    event_type: AdEventType      # AD_STARTED, AD_PLAYING, AD_ENDED, NO_MATCH
    ad_name: str | None
    confidence: float
    duration_seconds: float      # Only for AD_ENDED

# Register callback
def on_event(event: AdEvent):
    if event.event_type == AdEventType.AD_STARTED:
        print(f"Ad started: {event.ad_name}")

detector = AdDetector(on_event=on_event)
```

## No-Match Counter

Tracks consecutive no-matches to detect ad end:

```python
# In AD_PLAYING state
if no_match:
    self._no_match_count += 1
    
    if unmute_mode == DETECTION:
        if self._no_match_count >= 3:  # threshold
            self._set_state(AD_ENDING)
            self._start_unmute_timer()

if match:
    self._no_match_count = 0  # Reset on any match
```

**Why 3?**: Balance between:
- Too low (1-2): False unmutes during brief audio gaps
- Too high (5+): Slow to detect ad end

## Actions Triggered

### On Ad Start
1. **Mute audio** via AppleScript:
   ```python
   osascript -e "set volume output muted true"
   ```
2. **Save volume** for restoration
3. **Send desktop notification** (pync)
4. **Call webhook** (if configured):
   ```json
   {
     "event": "ad_started",
     "ad_name": "Dream11-Ad",
     "confidence": 0.85,
     "timestamp": "2024-01-07T10:30:00"
   }
   ```

### On Ad End
1. **Unmute audio**:
   ```python
   osascript -e "set volume output muted false"
   osascript -e "set volume output volume 50"  # Restore
   ```
2. **Send notification** with duration
3. **Call webhook**:
   ```json
   {
     "event": "ad_ended",
     "ad_name": "Dream11-Ad",
     "confidence": 0.85,
     "duration_seconds": 28.5,
     "timestamp": "2024-01-07T10:30:28"
   }
   ```

## Usage

### Basic Usage

```python
from core.ad_detector import AdDetector
from core.recognizer import Recognizer

detector = AdDetector()
recognizer = Recognizer()

# Continuous loop
while True:
    # Get audio window
    audio = capture_audio(duration=5.0)
    
    # Recognize
    result = recognizer.recognize_audio(audio, sample_rate=44100)
    
    # Process through state machine
    event = detector.process_recognition(result)
    
    if event:
        print(f"Event: {event.event_type.name}")
```

### With Event Callback

```python
def handle_event(event: AdEvent):
    match event.event_type:
        case AdEventType.AD_STARTED:
            log(f"Muted: {event.ad_name} ({event.confidence:.0%})")
        case AdEventType.AD_ENDED:
            log(f"Unmuted after {event.duration_seconds:.1f}s")
        case AdEventType.NO_MATCH:
            log("No ad detected")

detector = AdDetector(on_event=handle_event)
```

### Statistics

```python
stats = detector.get_stats()

print(f"Total detections: {stats.total_detections}")
print(f"Total ad time: {stats.total_ad_time_seconds:.1f}s")
print(f"Current state: {stats.current_state.name}")
print(f"Current ad: {stats.current_ad}")
```

## Configuration

```yaml
actions:
  mute: true                    # Enable muting
  notifications: true           # Desktop notifications
  webhook: true                 # HTTP webhooks

unmute:
  mode: detection               # timer | detection | manual | configurable
  timer_seconds: 30             # For timer/configurable modes
  delay_seconds: 2              # Delay before unmute (detection mode)
  restore_volume: true          # Restore previous volume

detection:
  consecutive_no_match_threshold: 3  # No-matches to trigger AD_ENDING
```

## Error Handling

The detector is defensive:

```python
# Event callbacks are wrapped
try:
    self._on_event(event)
except Exception as e:
    logger.error(f"Event callback error: {e}")
    # Continue processing

# Timer cleanup on state changes
self._cancel_unmute_timer()  # Always cancel before starting new

# Force unmute on errors
try:
    # ... detection logic
except Exception:
    detector.force_unmute()  # Emergency unmute
```

## Threading

Timers run in daemon threads:

```python
self._unmute_timer = threading.Timer(delay, self._on_unmute_timer)
self._unmute_timer.daemon = True  # Don't block app exit
self._unmute_timer.start()
```

Safe to call `detector.reset()` or `detector.force_unmute()` from any thread.

## Best Practices

1. **Single detector instance**: Reuse across recognition loops
2. **Handle events**: Register callback for logging/UI updates
3. **Graceful shutdown**: Call `detector.reset()` on exit
4. **Error recovery**: Use `force_unmute()` for emergency situations
5. **Statistics**: Monitor `get_stats()` for debugging

## Testing

```python
# Dry-run mode (no actual muting)
settings.actions.mute = False
detector = AdDetector(settings)

# Process mock results
result = RecognitionResult(ad_name="Test", confidence=0.8, ...)
event = detector.process_recognition(result)

assert detector.state == AdDetectionState.AD_PLAYING
assert event.event_type == AdEventType.AD_STARTED
```
