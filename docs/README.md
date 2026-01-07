# Howzat Technical Documentation

Comprehensive technical documentation for Howzat's audio fingerprinting and ad detection system.

## Core Components

### [Audio Fingerprinting](fingerprinting.md)
Deep dive into the audio fingerprinting algorithm:
- Spectrogram generation and peak detection
- Constellation hashing for unique fingerprints
- How fingerprints are stored and queried
- Performance characteristics and trade-offs

### [Continuous Listening](listener.md)
Real-time audio capture and processing:
- Microphone integration with PyAudio
- Sliding window audio capture (5-second windows)
- Audio buffering and chunk processing
- Memory-efficient audio handling

### [Recognition Engine](recognizer.md)
Matching captured audio against stored fingerprints:
- Fingerprint matching algorithm
- Confidence scoring and threshold tuning
- Database query optimization
- Handling multiple ads and best-match selection

### [Ad Detection & State Machine](ad-detection.md)
Complete ad lifecycle management:
- State machine design (IDLE → AD_DETECTED → AD_PLAYING → AD_ENDING)
- State transitions and event callbacks
- Unmute modes (detection, timer, manual, configurable)
- Action triggers (mute, notify, webhook)

## Guides

### [Troubleshooting](troubleshooting.md)
Solutions to common issues:
- Microphone permission and audio input problems
- Low detection accuracy and tuning confidence thresholds
- PyAudio installation on macOS
- Notification and webhook configuration
- Database and performance optimization

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         User Input                          │
│  (Record Ad / Start Listening / Configure Settings)         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                      CLI Layer (Typer)                      │
│  Commands: record, listen, ads, config                     │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌──────────────┐   ┌────────────────┐   ┌─────────────┐
│ Fingerprinter│   │    Listener    │   │  Database   │
│              │   │                │   │             │
│ - Spectrogram│   │ - PyAudio      │   │ - SQLite    │
│ - Peak Find  │   │ - Buffering    │   │ - Queries   │
│ - Hashing    │   │ - Windowing    │   │ - Storage   │
└──────┬───────┘   └────────┬───────┘   └──────┬──────┘
       │                    │                   │
       │                    ▼                   │
       │            ┌──────────────┐            │
       │            │  Recognizer  │◄───────────┘
       │            │              │
       │            │ - Matching   │
       │            │ - Scoring    │
       │            └──────┬───────┘
       │                   │
       └───────────────────┼───────────────────┐
                           ▼                   │
                  ┌─────────────────┐          │
                  │   AdDetector    │◄─────────┘
                  │  (State Machine)│
                  │                 │
                  │ - Lifecycle Mgmt│
                  │ - Event Handling│
                  └────────┬────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌─────────────┐
│AudioControl  │  │Notifications │  │  Webhooks   │
│              │  │              │  │             │
│- osascript   │  │- pync        │  │- HTTP POST  │
│- Mute/Unmute │  │- Desktop     │  │- Callbacks  │
└──────────────┘  └──────────────┘  └─────────────┘
```

## Key Design Decisions

1. **SQLite over NoSQL**: Simple, file-based, no external dependencies
2. **Pydantic for Config**: Type-safe, validation, excellent DX
3. **State Machine Pattern**: Clear ad lifecycle, predictable behavior
4. **Dependency Injection**: Testable, flexible, cached singletons
5. **uv over pip**: 10-100x faster installs, better resolution
6. **Rich CLI**: Modern, beautiful terminal UX
7. **Typer**: Type-safe CLI with auto-generated help

## Contributing to Documentation

When updating documentation:

1. Keep explanations clear and concise
2. Include code examples where relevant
3. Add diagrams for complex flows (ASCII art is fine)
4. Link between related docs
5. Update this README if adding new docs

## Need Help?

- **Issues**: Check [troubleshooting.md](troubleshooting.md)
- **GitHub**: [Open an issue](https://github.com/rushi/howzat/issues)
