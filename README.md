# Howzat

Automatically mute cricket advertisements using audio fingerprinting. Record ad audio signatures, then let the app continuously listen and mute your system when those ads play.

## Features

- **Audio Fingerprinting** - Uses spectral peak analysis (similar to Shazam) to identify ads
- **Automatic Muting** - Mutes macOS system audio when an ad is detected
- **Web Dashboard** - Mobile-friendly UI accessible on iPhone over local WiFi
- **Desktop Notifications** - Get notified when ads are detected/ended
- **Webhook Support** - Trigger webhooks for home automation (e.g., mute TV via Home Assistant)
- **Multiple Unmute Modes** - Timer-based, detection-based, manual, or configurable

## Requirements

- macOS (uses AppleScript for audio control)
- Python 3.10+
- PortAudio (for microphone access)

## Installation

Make sure [uv](https://docs.astral.sh/uv/) is installed.

```bash
# Install PortAudio (required for PyAudio)
brew install portaudio

# Clone and install Howzat
git clone https://github.com/rushi/howzat.git
cd howzat
uv pip install -e .

# Grant microphone permission to Terminal
# System Settings > Privacy & Security > Microphone > Enable Terminal
```

## Quick Start

```bash
# 1. Record an ad (play the ad and record for 30 seconds)
howzat record mic --name "Dream11-Ad" --duration 30

# 2. Start listening mode
howzat listen

# 3. Watch cricket - ads will be automatically muted!
```

## Usage

```
Usage: howzat [OPTIONS] COMMAND [ARGS]...

  Howzat - Detect and mute advertisements automatically.

Options:
  -v, --verbose        Enable verbose/debug logging
  -c, --config PATH    Path to config file
  --help               Show this message and exit.

Commands:
  ads      Manage stored advertisements
  audio    Audio device management
  config   Configuration management
  listen   Start listening mode to detect ads
  record   Record and fingerprint advertisements
  serve    Start the web dashboard
  status   Show current status and statistics
  version  Show version information
```

| Command | Purpose |
| --- | --- |
| `record` | Record and fingerprint an ad from mic, file, or a timed session |
| `listen` | Continuously listen and mute when an ad is detected |
| `ads` | List, rename, delete, export/import, or vacuum the ad database |
| `audio` | List input devices, run diagnostics, and set up loopback capture |
| `config` | Show, set, reset, or locate the config file |
| `serve` | Start the web dashboard |
| `status` | Show database, config, and detection summary |

### Recording Ads

```bash
# Record from microphone for 30 seconds (--name is optional; auto-generated if omitted)
howzat record mic --name "Dream11-Ad" --duration 30
howzat record mic --duration 30                    # auto-names as "ad-7f3a" etc.

# Record until you press Ctrl+C
howzat record until-stop --name "CRED-Ad"

# Multi-ad session: press 's' to save current and immediately start the next ad
# Press Ctrl+C to end the session (shows summary of all saved ads)
howzat record until-stop

# Import from audio file
howzat record file ~/Downloads/phonePe-ad.mp3 --name "PhonePe-Ad"

# Add tags for organization
howzat record mic --name "MPL-Ad" --duration 25 --tag gaming --tag fantasy
```

You can also download the ads from YouTube and pass it as an input file to fingerprint the entire ad.

### Listening Mode

```bash
# Start listening (mutes when ads detected)
howzat listen

# Dry run - detect but don't mute
howzat listen --dry-run

# Custom confidence threshold
howzat listen --confidence 0.5

# Listen on a specific device (e.g. a loopback device for system audio)
howzat listen --device 2

# Test recognition without continuous listening
howzat listen test --duration 5
```

### Managing Ads

```bash
# List all stored ads
howzat ads list
howzat ads list --detailed

# Show info about specific ad
howzat ads info "Dream11-Ad"

# Rename an ad
howzat ads rename "Dream11-Ad" "Dream11-IPL-Ad"

# Delete an ad (or all ads)
howzat ads delete "Dream11-Ad"
howzat ads delete --all

# Export/import database (--merge keeps existing ads, default replaces them)
howzat ads export ~/backup/ads.db
howzat ads import ~/backup/ads.db
howzat ads import ~/backup/ads.db --merge

# Database stats
howzat ads stats

# Reclaim disk space after deleting ads
howzat ads vacuum
```

### Audio Devices

```bash
# List input devices, marking the default and any loopback device
howzat audio list-devices
howzat audio list-devices --all    # include output-only devices

# Record a short sample and report signal level, to sanity-check a device
howzat audio test --duration 5

# Run capture diagnostics (levels, clipping, silence) against a device
howzat audio diagnose

# Walk through setting up a loopback device to capture system audio
howzat audio setup-guide
```

To detect ads from system audio (e.g. streamed video) rather than the room's microphone, install a loopback device such as [BlackHole](https://github.com/ExistentialAudio/BlackHole) and point Howzat at it with `howzat config set audio.input_device <index>`.

### Configuration

```bash
# Show current config
howzat config show

# Set webhook URL
howzat config set webhook.url "https://homeassistant.local/api/webhook/ad-detected"
howzat config set actions.webhook true

# Change un-mute mode
howzat config set unmute.mode timer        # Fixed 30s timer
howzat config set unmute.mode detection    # Unmute when ad stops matching
howzat config set unmute.mode manual       # Manual unmute only
howzat config set unmute.mode configurable # Custom timer

# Adjust detection sensitivity
howzat config set detection.confidence_threshold 0.5

# Initialize config file
howzat config init

# Reset config to defaults
howzat config reset

# Print the config file path
howzat config path
```

## Configuration File

Config is stored at `~/.config/howzat/config.yaml`:

```yaml
webhook:
  url: null # e.g., "https://homeassistant.local/api/webhook/ad-detected"
  timeout_seconds: 5
  events: [ad_started, ad_ended]

detection:
  confidence_threshold: 0.6
  listen_window_seconds: 5
  consecutive_no_match_threshold: 3

actions:
  mute: true
  notify: true
  webhook: false

unmute:
  mode: detection # timer | detection | manual | configurable
  timer_seconds: 30
  delay_seconds: 3
  restore_volume: true
```

## Web Dashboard

Start the mobile-friendly dashboard and control Howzat from your iPhone on the same WiFi network:

```bash
howzat serve
# Open on iPhone: http://[your-mac-hostname].local:8080

howzat serve --open     # Opens browser automatically
howzat serve --port 9000
```

The dashboard provides:
- **Live status**: real-time detection state and VU meter (log-scaled dB) via SSE
- **Ads Library**: browse, rename, and delete stored fingerprints
- **Record**: capture new ads directly from the browser, then rename before saving
- **Config**: adjust detection settings; saves and restarts the listener automatically

## Tech Stack

- **Python 3.10+** - Core language
- **Typer + Rich** - CLI framework with beautiful output
- **FastAPI + uvicorn** - Web dashboard backend
- **NumPy + SciPy** - Audio signal processing and fingerprinting
- **PyAudio** - Microphone capture
- **SQLite** - Fingerprint storage (no external database needed)
- **pync** - macOS notifications
- **osascript** - macOS audio control via AppleScript

## How It Works

Howzat uses audio fingerprinting (similar to Shazam) to identify advertisements in real-time:

1. **[Recording & Fingerprinting](docs/fingerprinting.md)**: Audio is converted to a spectrogram, local peaks are identified, and pairs of peaks are hashed to create unique fingerprints
2. **[Continuous Listening](docs/listener.md)**: 5-second audio windows are captured from your microphone, fingerprinted in real-time
3. **[Recognition & Matching](docs/recognizer.md)**: Fingerprints are matched against stored ads using confidence scoring
4. **[Detection & Actions](docs/ad-detection.md)**: When confidence exceeds threshold, system audio is muted, notifications sent, and webhooks triggered
5. **Unmute**: Audio is restored based on your configured unmute mode (detection-based, timer, or manual)

**Learn More**: See the [technical documentation](docs/) for detailed implementation details.

## Development

### Setup Development Environment

```bash
uv venv                    # Creates .venv in ~100ms
source .venv/bin/activate  # Activate the virtual environment
uv pip install -e ".[dev]" # Install with dev dependencies in seconds
```

### Running Tests

```bash
# No venv activation needed with uv run!
uv run pytest tests/ -v

# Or if venv is activated
pytest tests/ -v
```

### Linting and Formatting

```bash
uv run ruff check src/ tests/           # Lint check
uv run ruff check src/ tests/ --fix     # Auto-fix issues
uv run ruff format src/ tests/          # Format code

# Enable pre-commit hooks (auto-runs on git commit)
pre-commit install
```

### Type Checking

```bash
uv run mypy src/
```

## Troubleshooting

Having issues? Check the **[Troubleshooting Guide](docs/troubleshooting.md)** for solutions to common problems:

- [Microphone not working](docs/troubleshooting.md#microphone-not-working)
- [Low detection accuracy](docs/troubleshooting.md#low-detection-accuracy)
- [PyAudio installation issues](docs/troubleshooting.md#pyaudio-installation-issues)
- [Notification issues](docs/troubleshooting.md#notification-issues)
- [Webhook issues](docs/troubleshooting.md#webhook-issues)
- [Performance issues](docs/troubleshooting.md#performance-issues)

Still stuck? [Open an issue](https://github.com/rushi/howzat/issues) on GitHub.

## Author

Created by [Rushi Vishavadia](http://rushi.dev)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
