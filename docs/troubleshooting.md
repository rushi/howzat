# Troubleshooting Guide

Common issues and solutions for Howzat.

## Microphone Not Working

### Symptoms
- No audio detected when running `howzat listen`
- Error messages about microphone access
- Silent/no audio input

### Solutions

**1. Grant Microphone Permission**
- Go to **System Settings > Privacy & Security > Microphone**
- Enable microphone access for your Terminal app (Terminal, iTerm2, etc.)
- Restart your terminal after granting permission

**2. Verify Microphone Input**
```bash
# Test microphone for 5 seconds
howzat listen test --duration 5
```

**3. Check System Audio Input**
- Open **System Settings > Sound > Input**
- Ensure the correct microphone is selected
- Check that input level shows activity when you speak

## Low Detection Accuracy

### Symptoms
- Ads not being detected consistently
- Many false positives or false negatives
- Low confidence scores

### Solutions

**1. Adjust Confidence Threshold**
```bash
# Lower the threshold (default is 0.6)
howzat config set detection.confidence_threshold 0.4

# Or go even lower for testing
howzat config set detection.confidence_threshold 0.3
```

**2. Improve Recording Quality**
- Record ads in the **same environment** where you'll be listening
- Ensure ads are recorded at **sufficient volume**
- Minimize background noise during recording
- Record for at least **30 seconds** (longer is better)

**3. Re-record Problematic Ads**
```bash
# Delete old recording
howzat ads delete "Ad-Name"

# Record again with better conditions
howzat record mic --name "Ad-Name" --duration 30
```

**4. Test Recognition**
```bash
# Play the ad and test recognition without continuous listening
howzat listen test --duration 10
```

## PyAudio Installation Issues

### Symptoms
- `pip install pyaudio` fails with compilation errors
- Missing PortAudio library errors
- Build failures on macOS

### Solutions

**1. Install PortAudio First**
```bash
brew install portaudio
```

**2. Install PyAudio with uv (recommended)**
```bash
# Let uv handle it automatically (usually works)
uv pip install pyaudio

# Or with explicit paths if needed
uv pip install --global-option='build_ext' \
    --global-option='-I/opt/homebrew/include' \
    --global-option='-L/opt/homebrew/lib' pyaudio
```

**3. Using pip (if not using uv)**
```bash
pip install --global-option='build_ext' \
    --global-option='-I/opt/homebrew/include' \
    --global-option='-L/opt/homebrew/lib' pyaudio
```

**4. Check PortAudio Installation**
```bash
# Verify PortAudio is installed
brew info portaudio

# Reinstall if needed
brew reinstall portaudio
```

## Database Issues

### Corrupted Database

**Symptoms**: SQLite errors, corrupted fingerprints

**Solution**:
```bash
# Backup current database
cp ~/.config/howzat/ads.db ~/.config/howzat/ads.db.backup

# Delete and reinitialize
rm ~/.config/howzat/ads.db

# Re-record your ads
howzat record mic --name "Ad-Name" --duration 30
```

### Database Size Too Large

**Symptoms**: Slow performance, large database file

**Solution**:
```bash
# Check database stats
howzat ads stats

# Delete unused ads
howzat ads list
howzat ads delete "Ad-Name"

# Vacuum database to reclaim space
sqlite3 ~/.config/howzat/ads.db "VACUUM;"
```

## Notification Issues

### Notifications Not Appearing

**Symptoms**: No desktop notifications when ads are detected

**Solutions**:

**1. Check Notification Settings**
- Go to **System Settings > Notifications**
- Find your Terminal app (Terminal, iTerm2, etc.)
- Ensure notifications are **enabled**
- Set alert style to **Banners** or **Alerts**

**2. Verify Notifications Are Enabled in Config**
```bash
howzat config show

# Enable if disabled
howzat config set actions.notify true
```

**3. Test Notifications Manually**
```bash
# Send a test notification (requires pync)
python3 -c "import pync; pync.notify('Test', title='Howzat')"
```

## Webhook Issues

### Webhook Not Triggering

**Symptoms**: Webhook URL not being called when ads are detected

**Solutions**:

**1. Verify Webhook Configuration**
```bash
howzat config show

# Enable webhook
howzat config set actions.webhook true

# Set webhook URL
howzat config set webhook.url "https://your-webhook-url.com/endpoint"
```

**2. Check Webhook Events**
```bash
# View current webhook configuration
howzat config show

# Ensure the correct events are enabled
# Default: [ad_started, ad_ended]
```

**3. Test Webhook Manually**
```bash
# Use curl to test your webhook endpoint
curl -X POST https://your-webhook-url.com/endpoint \
  -H "Content-Type: application/json" \
  -d '{"event":"ad_started","ad_name":"Test","confidence":0.8}'
```

**4. Check Logs for Errors**
```bash
# View recent logs
tail -f ~/.config/howzat/howzat.log

# Run in verbose mode
howzat listen -v
```

## Unmute Issues

### Audio Not Unmuting Automatically

**Symptoms**: System stays muted after ad ends

**Solutions**:

**1. Check Unmute Mode**
```bash
howzat config show

# Switch to detection-based unmute (recommended)
howzat config set unmute.mode detection

# Or use timer-based unmute
howzat config set unmute.mode timer
howzat config set unmute.timer_seconds 30
```

**2. Manually Unmute**
```bash
# Force unmute immediately
# (Press Ctrl+U while howzat listen is running)
```

**3. Check for Overlapping Ads**
- If multiple ads play back-to-back, detection mode might keep the system muted
- Consider using `timer` mode with a short duration
- Or use `manual` mode and unmute yourself

## Performance Issues

### High CPU Usage

**Symptoms**: High CPU usage during listening mode

**Solutions**:

**1. Increase Listen Window**
```bash
# Default is 5 seconds, increase to reduce CPU
howzat config set detection.listen_window_seconds 10
```

**2. Close Other Audio Apps**
- Close browsers, media players that might be processing audio
- Reduce background processes

### Slow Recognition

**Symptoms**: Delays in ad detection

**Solutions**:

**1. Reduce Database Size**
- Delete unused ads
- Keep only frequently occurring ads

**2. Lower Confidence Threshold**
- Requires fewer fingerprint matches
- Faster detection but potentially less accurate

## Getting Help

If you're still experiencing issues:

1. **Check Logs**: `tail -f ~/.config/howzat/howzat.log`
2. **Run in Verbose Mode**: `howzat listen -v`
3. **File an Issue**: [GitHub Issues](https://github.com/rushi/howzat/issues)
4. **Provide Details**:
   - macOS version
   - Python version
   - Error messages
   - Steps to reproduce

## Common Error Messages

### `ModuleNotFoundError: No module named 'pync'`

**Solution**: Install development dependencies
```bash
uv pip install -e ".[dev]"
```

### `sqlite3.OperationalError: database is locked`

**Solution**: Another instance of howzat is running
```bash
# Find and kill the process
ps aux | grep howzat
kill <PID>
```

### `OSError: [Errno -9996] Invalid input device`

**Solution**: Microphone permissions not granted or wrong device selected
- Grant microphone permission to Terminal
- Check audio input device in System Settings

### `typer.Exit: Aborted!`

**Solution**: Command was cancelled or interrupted
- This is normal when pressing Ctrl+C
- Not an error, just a clean exit
