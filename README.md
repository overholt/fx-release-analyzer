# Firefox Release Analyzer

A Python tool that automatically analyzes Firefox releases by combining git commit data with Bugzilla bug information to generate comprehensive release summaries using Claude AI.

## Features

- **Automatic Release Detection**: Finds git tags and commit ranges for any Firefox version
- **Rich Bug Information**: Uses [bmo-to-md](https://github.com/padenot/bmo-to-md) for detailed, markdown-formatted bug reports
- **Intelligent Analysis**: Claude AI generates comprehensive summaries organized by impact area
- **Multiple Release Types**: Supports major releases (143.0), point releases (143.0.1), and version shortcuts (143)
- **Smart Prioritization**: Automatically identifies and highlights the most important changes

## Installation

### Prerequisites

- Python 3.7+
- git repository with Firefox source code
- [bmo-to-md](https://github.com/padenot/bmo-to-md) command-line tool
- Claude API key from Anthropic
- Bugzilla API key (optional but recommended)

### Setup

1. **Clone or download the script**:
   ```bash
   curl -O https://path/to/fx-release-analyzer.py
   chmod +x fx-release-analyzer.py
   ```

2. **Install Python dependencies**:
   ```bash
   pip3 install requests
   ```

3. **Install bmo-to-md**:
   ```bash
   # Follow instructions at: https://github.com/padenot/bmo-to-md
   ```

4. **Set up API keys**:
   ```bash
   export CLAUDE_API_KEY="your_claude_api_key"
   export BMO_API_KEY="your_bugzilla_api_key"  # Optional but recommended
   ```

## Usage

### Basic Usage

Analyze a Firefox release from within a Firefox git repository:

```bash
# Point release
python3 fx-release-analyzer.py 143.0.1

# Major release  
python3 fx-release-analyzer.py 143.0

# Version shorthand
python3 fx-release-analyzer.py 143
```

### Advanced Options

```bash
# Specify custom paths
python3 fx-release-analyzer.py 143.0.1 \
  --repo-path /path/to/firefox-source \
  --bmo-path /usr/local/bin/bmo-to-md

# Save output to file
python3 fx-release-analyzer.py 143.0.1 --output firefox_143_0_1_analysis.md

# Use different API key
python3 fx-release-analyzer.py 143.0.1 --claude-key your_other_api_key
```

### Command Line Options

- `version` - Firefox version to analyze (required)
- `--claude-key` - Claude API key (or set `CLAUDE_API_KEY` env var)
- `--bmo-path` - Path to bmo-to-md executable (default: `bmo-to-md`)
- `--repo-path` - Path to Firefox git repository (default: current directory)
- `--output` - Save analysis to file instead of printing to stdout

## How It Works

1. **Repository Analysis**: Finds the appropriate Firefox release tags and extracts all commits between releases
2. **Bug Discovery**: Identifies bugs from multiple sources:
   - Bugzilla milestone searches for the target release
   - Bug IDs mentioned in commit messages
3. **Rich Bug Data**: Uses bmo-to-md to fetch detailed bug information including:
   - Complete descriptions and comments
   - Severity and component information
   - Proper markdown formatting
4. **Intelligent Prioritization**: Ranks bugs by importance using keywords like "security", "crash", "performance"
5. **AI Analysis**: Claude generates comprehensive summaries organized by:
   - Executive summary for users
   - Security and stability improvements
   - Performance enhancements
   - New features and web platform support
   - Developer tools updates
   - Platform-specific changes

## Sample Output

The tool generates detailed analyses like:

```markdown
# Firefox 143.0.1 Release Analysis

## Executive Summary
Firefox 143.0.1 is a stability-focused point release that addresses several critical 
issues discovered after the 143.0 release...

## Security and Stability
- **Bug 1234567**: Fixed critical memory safety issue in WebGL rendering
- **Bug 1234568**: Resolved crash when using certain WebExtension APIs
- **Bug 1234569**: Patched security vulnerability in PDF viewer

## Performance Improvements
- Optimized JavaScript engine for 15% faster page load times
- Reduced memory usage in tab management by 200MB on average
...
```

## Environment Variables

- `CLAUDE_API_KEY` - Your Anthropic Claude API key (required)
- `BMO_API_KEY` - Your Bugzilla API key (used by bmo-to-md, recommended)

## Troubleshooting

### Common Issues

**"bmo-to-md not found"**
```bash
# Install bmo-to-md or specify path
python3 fx-release-analyzer.py 143.0.1 --bmo-path /path/to/bmo-to-md
```

**"Could not find release tag"**
```bash
# Check available tags
git tag -l "*FIREFOX*143*RELEASE*"

# Make sure you're in a Firefox repository
git remote -v  # Should show mozilla URLs
```

**"API Error: anthropic-version header required"**
- Update the script - this should be automatically included

**"Request too large"**
- The tool automatically truncates large requests
- Consider analyzing smaller version ranges

### Debug Information

Run with verbose output to see what the tool is doing:

```bash
python3 fx-release-analyzer.py 143.0.1 2>&1 | tee debug.log
```

## API Usage and Costs

The tool makes several API calls:
- **Bugzilla REST API**: Free, used for finding bug IDs
- **Claude API**: Paid, one request per analysis (~$0.50-2.00 depending on release size)

To minimize costs:
- Use BMO_API_KEY to get better bug data in fewer requests
- The tool automatically limits content size to stay within reasonable token limits

## Contributing

This tool was designed for Mozilla Firefox development workflows. Contributions welcome for:

- Supporting other Mozilla products (Thunderbird, etc.)
- Additional output formats (JSON, HTML)
- Integration with other bug tracking systems
- Performance optimizations

## License

MIT License - feel free to modify and distribute.

## Credits

- Built for Firefox release management and analysis
- Uses [bmo-to-md](https://github.com/padenot/bmo-to-md) by Paul Adenot
- Powered by Anthropic's Claude AI
- Integrates with Mozilla's Bugzilla and Firefox git repositories
