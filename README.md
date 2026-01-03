<div align="center">

# Spotitube

<img src="https://raw.githubusercontent.com/4ngel2769/spotitube/refs/heads/main/assets/spotitube.png" alt="Spotitube Logo" width="180" height="180">

**A simple way to download your music library from Spotify and YouTube**

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Issues](https://img.shields.io/github/issues/4ngel2769/spotitube)](https://github.com/4ngel2769/spotitube/issues)

---

</div>

## Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
  - [Spotify API Setup](#spotify-api-setup)
  - [YouTube Music Cookies](#youtube-music-cookies)
- [Usage](#usage)
- [Sponsor](#sponsor)
- [License](#license)

## Introduction

Spotitube is a simple CLI tool designed to synchronize and download your music across platforms. Whether you want to back up your Spotify Liked Songs or migrate a YouTube Music playlist to high-quality local MP3s, Spotitube handles the heavy lifting with multi-threaded efficiency.

## Features

- **Cross-Platform**: Fetch tracks from Spotify (liked songs, playlists) and YouTube Music.
- **High-Fidelity Downloads**: Default 320kbps mp3 extraction using `yt-dlp` and [`ffmpeg`](https://ffmpeg.org/).
- **Multi Threaded Downloads**: Multi-threaded architecture for rapid searching and downloading.
- **Smart Deduplication**: Automatically filters duplicate tracks when merging sources.
- **Session Persistence**: Securely handles YouTube Music cookies for private library access.

## Prerequisites

- **Python 3.9+**
- **FFmpeg**: Essential for audio conversion.
  - **Windows 10/11**: `winget install ffmpeg`
  - **macOS**: `brew install ffmpeg`
  - **Linux**: Use your package manager. (e.g., `sudo apt install ffmpeg` for Debian-based systems)

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/4ngel2769/spotitube.git
   cd spotitube
   ```

2. **Set up a virtual environment**:
   ```bash
   # Windows
   python -m venv venv
   .\venv\Scripts\activate

   # macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

### Spotify API Setup
1. Visit the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
2. Create a new application to obtain your **Client ID** and **Client Secret**.
3. Set the **Redirect URI** to `http://127.0.0.1:8888/callback`.
4. Create a `.env` file in the root directory:
   ```env
   SPOTIFY_CLIENT_ID=your_id_here
   SPOTIFY_CLIENT_SECRET=your_secret_here
   SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
   ```

### YouTube Music Cookies
To access private playlists or "Liked Songs":
1. Open `music.youtube.com` in your browser and log in.
2. Open DevTools (F12) > Network tab.
3. Find any request to `music.youtube.com` and copy the `cookie` header value.
4. The script will prompt you to paste this on the first run, or you can manually create `ytmusic_cookie.txt`.

## Usage

Launch the interactive CLI:

```bash
python script.py
```

### Quick Start Guide
1. **Select Source**: Choose Spotify (1), YouTube Music (2), or Both (3).
2. **Download Mode**: Enter `y` to download files or `n` to just generate a JSON report.
3. **Select Content**: Choose between Liked Songs or specific playlists.
4. **Process**: The script will begin concurrent processing. Files are saved to `i/downloaded_songs/`.

## Sponsor

If you find this tool useful, consider supporting the development:

<a href="https://ko-fi.com/angelthebox" target="_blank"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support me on Ko-fi" style="height: 60px !important;width: 240px !important;" ></a>

<a href="https://buymeacoffee.com/angelthebox" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

## License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.

---
<div align="center">
Built with 💚 by <a href="https://github.com/4ngel2769">angeldev0</a>
</div>
