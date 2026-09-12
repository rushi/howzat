# Audio Fingerprinting

## Overview

Howzat uses spectral peak analysis (similar to Shazam) to create audio fingerprints that identify ads despite background noise.

## The Pipeline

```
Raw Audio → Spectrogram → Peak Detection → Constellation Hashing → Fingerprints
```

## How It Works

### 1. Spectrogram Generation

Converts audio from time-domain to frequency-domain using FFT:

```python
# Parameters
FFT_WINDOW_SIZE = 4096        # Frequency resolution
FFT_OVERLAP_RATIO = 0.5       # 50% overlap between windows

# Convert to spectrogram (2D: time × frequency)
frequencies, times, spectrogram = signal.spectrogram(
    audio,
    fs=sample_rate,
    window="hann",
    nperseg=FFT_WINDOW_SIZE,
    mode="magnitude",
)

# Convert to dB scale for better contrast
spectrogram = 10 * np.log10(spectrogram + 1e-10)
```

**Output**: 2D array where each column is a frequency snapshot at a point in time.

### 2. Peak Detection

Finds prominent frequency points (spectral peaks):

```python
# Parameters
PEAK_NEIGHBORHOOD_SIZE = 20   # Peak must be highest in 20×20 area

# Use adaptive threshold (mean + 1 std dev)
amp_min = np.mean(spectrogram) + np.std(spectrogram)

# Find local maxima
local_max = maximum_filter(spectrogram, size=PEAK_NEIGHBORHOOD_SIZE)
is_peak = (spectrogram == local_max) & (spectrogram > amp_min)

# Extract peak coordinates
peaks = list(zip(time_indices, freq_indices))
```

**Output**: List of `(time_idx, freq_idx)` tuples (~100 peaks per second).

### 3. Hash Generation

Creates hashes from peak pairs (constellation map):

```python
# Parameters
FAN_VALUE = 15              # Pair each peak with 15 subsequent peaks
MAX_TIME_DELTA = 200        # Max time gap between paired peaks

# For each anchor peak
for i, (t1, f1) in enumerate(peaks_sorted):
    # Pair with subsequent peaks within time window
    for j in range(i + 1, min(i + FAN_VALUE + 1, len(peaks_sorted))):
        t2, f2 = peaks_sorted[j]
        time_delta = t2 - t1

        if MIN_TIME_DELTA <= time_delta <= MAX_TIME_DELTA:
            # Hash encodes: freq1 + freq2 + time_delta
            hash_input = f"{f1}|{f2}|{time_delta}"
            hash_value = md5(hash_input).hexdigest()[:16]

            yield Fingerprint(hash_value, time_offset=times[t1])
```

**Why this works**:

- Each audio has a unique constellation of peaks
- Hashes encode peak relationships (tolerates noisy audio)
- Time offset stored for alignment verification
- ~1500 hashes per second (high redundancy)

### 4. Database Storage

```sql
CREATE TABLE fingerprints (
    hash TEXT,              -- 16-char MD5 hash
    ad_name TEXT,           -- Which ad
    time_offset REAL,       -- When in the ad (seconds)
    PRIMARY KEY (hash, ad_name, time_offset)
)
```

## Key Features

### Volume Independent

Uses relative peak heights, not absolute amplitudes.

### Noise Tolerant

- Adaptive thresholding adjusts to audio characteristics
- High redundancy (~45,000 hashes for 30s ad)
- Partial matches still work

### Time Invariant

Hashes encode relative time (time_delta), not absolute position. A 5-second window can match any part of a 30-second ad.

### Fast Matching

Hash lookup is O(1), database query is O(log n) per hash.

## Typical Numbers

**For 30-second ad**:

- Peaks: ~3,000
- Fingerprints: ~45,000 hashes
- Storage: ~1 MB
- Generation time: 1-2 seconds

**For 5-second window** (real-time):

- Peaks: ~500
- Fingerprints: ~7,500 hashes
- Processing: <0.5 seconds

## Configuration

```yaml
audio:
  sample_rate: 44100 # Higher = better quality
  chunk_size: 1024 # Buffer size

detection:
  confidence_threshold: 0.6 # 60% match required
  listen_window_seconds: 5 # Analysis window size
```

## API

```python
# From raw audio
result = fingerprint_audio(audio, sample_rate=44100)

# From file
result = fingerprint_file("ad.wav")

# From microphone
result = fingerprint_from_mic(duration_seconds=10)

# Result contains
result.fingerprints       # List[Fingerprint]
result.duration_seconds   # float
result.sample_rate        # int
```

## Limitations

- **Short samples**: <3 seconds may not have enough unique peaks
- **Extreme distortion**: Heavy pitch shift breaks frequency relationships
- **Mixed audio**: Multiple sources add non-matching peaks (still works via confidence scoring)

## Further Reading

- [Shazam Paper](https://www.ee.columbia.edu/~dpwe/papers/Wang03-shazam.pdf) - Original algorithm
- [Audio Fingerprinting Tutorial](https://willdrevo.com/fingerprinting-and-audio-recognition-with-python/)
