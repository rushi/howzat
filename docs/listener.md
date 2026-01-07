# Continuous Audio Listener

## Overview

The listener captures microphone audio in overlapping windows and performs continuous recognition using a sliding window approach.

## Sliding Window Concept

```
Time:  0s    2s    4s    6s    8s   10s
       [Window 1 (5s)]
             [Window 2 (5s)]
                   [Window 3 (5s)]
                         [Window 4 (5s)]

Window: 5s, Overlap: 2s, Step: 3s
Recognition every 3 seconds
```

**Why overlap?** Ensures ads aren't split across window boundaries.

## Architecture

```
Microphone → PyAudio → Ring Buffer (deque) → Recognition → Callback
                       (maxlen=220,500)
```

### Ring Buffer

```python
from collections import deque

# Auto-evicts old samples when full
window_samples = int(5.0 * 44100)  # 5 seconds
buffer: deque[float] = deque(maxlen=window_samples)

# Efficient O(1) operations
buffer.extend(new_chunk)  # Old samples auto-removed
audio = np.array(list(buffer))
```

## Classes

### ContinuousListener (Recommended)

Threaded listener with automatic recognition:

```python
listener = ContinuousListener()

def on_recognition(result):
    detector.process_recognition(result)

listener.start(on_recognition=on_recognition)
# ... runs in background thread
listener.stop()
```

### BufferedListener

Manual control, no threading:

```python
listener = BufferedListener(window_seconds=5.0)
listener.start()

while running:
    audio = listener.read_window()  # Returns when buffer full
    if audio is not None:
        result = recognizer.recognize_audio(audio, sample_rate=44100)

listener.stop()
```

## Usage Example

```python
from core.listener import ContinuousListener
from core.ad_detector import AdDetector

detector = AdDetector()
listener = ContinuousListener()

listener.start(on_recognition=lambda r: detector.process_recognition(r))

# Runs until stopped
listener.stop()
```

## Configuration

```yaml
audio:
  sample_rate: 44100 # Quality vs CPU
  chunk_size: 1024 # Buffer size

detection:
  listen_window_seconds: 5 # Recognition window
```

### Tuning

**Lower latency** (faster detection):

```yaml
listen_window_seconds: 3
```

⚠️ Less accurate (fewer fingerprints)

**Better accuracy** (slower detection):

```yaml
listen_window_seconds: 7
```

⚠️ More delay

## Threading

ContinuousListener runs in daemon thread:

- Callback executed in listener thread
- Detector is NOT thread-safe (use single instance)

## Performance

**Per 5s window**:

- Fingerprinting: ~0.3s
- Database lookup: ~0.1s
- **Total**: ~0.5s per 3s interval (17% CPU)

**Memory**: ~5-10 MB per listener instance

## Error Handling

Listener continues on errors:

```python
try:
    data = stream.read(chunk_size, exception_on_overflow=False)
except Exception as e:
    logger.warning(f"Error reading audio: {e}")
    continue  # Skip chunk, keep listening
```

## Microphone Permissions (macOS)

System Settings → Privacy & Security → Microphone → Enable for Terminal

Test with:

```bash
howzat listen test --duration 5
```

## Best Practices

1. Single listener instance per app
2. Use `daemon=True` threads for clean exit
3. Always call `listener.stop()` on shutdown
4. Monitor logs for audio read errors
