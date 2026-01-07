# Howzat

Automatically mute cricket advertisements using audio fingerprinting. Record ad audio signatures, then let the app continuously listen and mute your system when those ads play.

## Features

- **Audio Fingerprinting** - Uses spectral peak analysis (similar to Shazam) to identify ads
- **Automatic Muting** - Mutes macOS system audio when an ad is detected
- **Desktop Notifications** - Get notified when ads are detected/ended
- **Webhook Support** - Trigger webhooks for home automation (e.g., mute TV via Home Assistant)
- **Multiple Unmute Modes** - Timer-based, detection-based, manual, or configurable

## Requirements

- macOS (uses AppleScript for audio control)
- Python 3.10+
- PortAudio (for microphone access)

## Installation

Make sure [uv](https://docs.astral.sh/uv/) is is installed

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
  config   Configuration management
  listen   Start listening mode to detect ads
  record   Record and fingerprint advertisements
  status   Show current status and statistics
  version  Show version information
```

### Recording Ads

```bash
# Record from microphone for 30 seconds
howzat record mic --name "Dream11-Ad" --duration 30

# Record until you press Ctrl+C
howzat record until-stop --name "CRED-Ad"

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

# Delete an ad
howzat ads delete "Dream11-Ad"

# Export/import database
howzat ads export ~/backup/ads.db
howzat ads import ~/backup/ads.db

# Database stats
howzat ads stats
```

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

## Tech Stack

- **Python 3.10+** - Core language
- **Typer + Rich** - CLI framework with beautiful output
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
