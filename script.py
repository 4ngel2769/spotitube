import spotipy
from spotipy.oauth2 import SpotifyOAuth
from yt_dlp import YoutubeDL
import time
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv


# Load environment variables from .env file
load_dotenv()
# Spotify API credentials
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://localhost:8888/callback')

# Download settings
DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER', 'downloaded_songs')
AUDIO_FORMAT = os.getenv('AUDIO_FORMAT', 'mp3')  # Options: mp3, m4a, opus, wav
AUDIO_QUALITY = os.getenv('AUDIO_QUALITY', '320')  # Options: 128, 192, 256, 320 (kbps)
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))

# Initialize clients
sp = None

def init_spotify():
    """Initialize Spotify client"""
    global sp
    if sp is None:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope='user-library-read playlist-read-private',
            open_browser=True,  # Automatically open browser for login
            cache_path='.spotify_cache'  # Save token for reuse
        ))
    return sp

def get_ytmusic_cookie():
    """Get or load YouTube Music cookie"""
    cookie_file = 'ytmusic_cookie.txt'
    
    if not os.path.exists(cookie_file):
        print("\n=== YouTube Music Cookie Setup ===")
        print("Paste your YouTube Music cookie here:")
        print("(Get it from browser dev tools → Network → any request → cookie header)")
        cookie = input().strip()
        
        with open(cookie_file, 'w') as f:
            f.write(cookie)
        
        print(f"✓ Cookie saved to {cookie_file}")
        return cookie
    else:
        with open(cookie_file, 'r') as f:
            return f.read().strip()

def download_youtube_audio(url, track_name, artist_name):
    """Download audio from YouTube"""
    Path(DOWNLOAD_FOLDER).mkdir(parents=True, exist_ok=True)
    
    safe_filename = "".join(c for c in f"{artist_name} - {track_name}" 
                           if c.isalnum() or c in (' ', '-', '_')).strip()
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': AUDIO_FORMAT,
            'preferredquality': AUDIO_QUALITY,
        }],
        'outtmpl': f'{DOWNLOAD_FOLDER}/{safe_filename}.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'prefer_ffmpeg': True,
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return f"{DOWNLOAD_FOLDER}/{safe_filename}.{AUDIO_FORMAT}"
    except Exception as e:
        return None

def search_youtube_for_song(track_name, artist_name, download=False):
    """Search YouTube and optionally download"""
    query = f"{track_name} {artist_name}"
    
    ydl_opts_search = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'default_search': 'ytsearch1',
    }
    
    try:
        with YoutubeDL(ydl_opts_search) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            
            if result and 'entries' in result and result['entries']:
                video = result['entries'][0]
                video_info = {
                    'title': video.get('title', ''),
                    'url': f"https://www.youtube.com/watch?v={video['id']}",
                    'id': video['id'],
                }
                
                if download:
                    download_path = download_youtube_audio(
                        video_info['url'], 
                        track_name, 
                        artist_name
                    )
                    video_info['download_path'] = download_path
                
                return video_info
    except Exception as e:
        pass
    
    return None

# ============ SPOTIFY FUNCTIONS ============

def get_spotify_liked_songs():
    """Get all liked songs from Spotify"""
    sp = init_spotify()
    print("Fetching Spotify liked songs...")
    liked_songs = []
    offset = 0
    limit = 50
    
    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not results['items']:
            break
        
        for item in results['items']:
            track = item['track']
            liked_songs.append({
                'name': track['name'],
                'artist': ', '.join([artist['name'] for artist in track['artists']]),
                'album': track['album']['name'],
                'source': 'spotify'
            })
        
        offset += limit
        print(f"  Fetched {len(liked_songs)} songs...", end='\r')
        if len(results['items']) < limit:
            break
    
    print(f"\nFound {len(liked_songs)} Spotify liked songs")
    return liked_songs

def get_spotify_playlist_songs(playlist_id):
    """Get all songs from a Spotify playlist"""
    sp = init_spotify()
    songs = []
    offset = 0
    limit = 100
    
    while True:
        results = sp.playlist_tracks(playlist_id, limit=limit, offset=offset)
        if not results['items']:
            break
        
        for item in results['items']:
            if item['track']:
                track = item['track']
                songs.append({
                    'name': track['name'],
                    'artist': ', '.join([artist['name'] for artist in track['artists']]),
                    'album': track['album']['name'],
                    'source': 'spotify'
                })
        
        offset += limit
        if len(results['items']) < limit:
            break
    
    return songs

def get_spotify_playlists():
    """Get all Spotify playlists"""
    sp = init_spotify()
    print("Fetching Spotify playlists...")
    playlists = []
    offset = 0
    limit = 50
    
    while True:
        results = sp.current_user_playlists(limit=limit, offset=offset)
        if not results['items']:
            break
        
        for playlist in results['items']:
            playlists.append({
                'id': playlist['id'],
                'name': playlist['name'],
                'tracks_total': playlist['tracks']['total'],
                'source': 'spotify'
            })
        
        offset += limit
        if len(results['items']) < limit:
            break
    
    print(f"Found {len(playlists)} playlists")
    return playlists

# ============ YOUTUBE MUSIC FUNCTIONS ============

def get_ytmusic_liked_songs():
    """Get all liked songs from YouTube Music using yt-dlp"""
    cookie = get_ytmusic_cookie()
    
    print("Fetching YouTube Music liked songs...")
    print("This uses yt-dlp to fetch your liked songs playlist...")
    
    # Create cookie file in Netscape format
    cookie_lines = ['# Netscape HTTP Cookie File\n']
    for cookie_pair in cookie.split('; '):
        if '=' in cookie_pair:
            name, value = cookie_pair.split('=', 1)
            cookie_lines.append(f'.youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n')
    
    with open('cookies.txt', 'w') as f:
        f.writelines(cookie_lines)
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': 'cookies.txt',
    }
    
    liked_songs = []
    
    try:
        # YouTube Music liked songs playlist URL
        url = 'https://music.youtube.com/playlist?list=LM'
        
        with YoutubeDL(ydl_opts) as ydl:
            print("Extracting playlist info (this may take a while for large libraries)...")
            result = ydl.extract_info(url, download=False)
            
            if result and 'entries' in result:
                for entry in result['entries']:
                    try:
                        if entry:
                            title = entry.get('title', 'Unknown')
                            # Try to parse artist from title (usually "Artist - Song")
                            if ' - ' in title:
                                artist, song = title.split(' - ', 1)
                            else:
                                artist = entry.get('uploader', 'Unknown Artist')
                                song = title
                            
                            liked_songs.append({
                                'name': song.strip(),
                                'artist': artist.strip(),
                                'album': 'Unknown Album',
                                'videoId': entry.get('id', ''),
                                'source': 'ytmusic'
                            })
                            print(f"  Fetched {len(liked_songs)} songs...", end='\r')
                    except Exception as e:
                        continue
    except Exception as e:
        print(f"\n✗ Error fetching liked songs: {e}")
        print("  Make sure your cookie is valid and you're signed in to YouTube Music")
        return []
    
    print(f"\nFound {len(liked_songs)} YouTube Music liked songs")
    return liked_songs

def get_ytmusic_playlist_songs(playlist_url):
    """Get songs from a YouTube Music playlist URL"""
    cookie = get_ytmusic_cookie()
    
    # Create cookie file in Netscape format
    cookie_lines = ['# Netscape HTTP Cookie File\n']
    for cookie_pair in cookie.split('; '):
        if '=' in cookie_pair:
            name, value = cookie_pair.split('=', 1)
            cookie_lines.append(f'.youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n')
    
    with open('cookies.txt', 'w') as f:
        f.writelines(cookie_lines)
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': True,
        'cookiefile': 'cookies.txt',
    }
    
    songs = []
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(playlist_url, download=False)
            
            if result and 'entries' in result:
                for entry in result['entries']:
                    try:
                        if entry:
                            title = entry.get('title', 'Unknown')
                            if ' - ' in title:
                                artist, song = title.split(' - ', 1)
                            else:
                                artist = entry.get('uploader', 'Unknown Artist')
                                song = title
                            
                            songs.append({
                                'name': song.strip(),
                                'artist': artist.strip(),
                                'album': 'Unknown Album',
                                'videoId': entry.get('id', ''),
                                'source': 'ytmusic'
                            })
                    except Exception:
                        continue
    except Exception as e:
        print(f"Error fetching playlist: {e}")
    
    return songs

def process_song(song, download, index, total):
    """Process a single song (search/download)"""
    result = {'spotify': song, 'youtube': None}
    
    try:
        # If from YouTube Music, we already have the video ID
        if song.get('source') == 'ytmusic' and song.get('videoId'):
            video_url = f"https://www.youtube.com/watch?v={song['videoId']}"
            result['youtube'] = {
                'title': song['name'],
                'url': video_url,
                'id': song['videoId']
            }
            
            if download:
                download_path = download_youtube_audio(
                    video_url,
                    song['name'],
                    song['artist']
                )
                if download_path:
                    result['youtube']['download_path'] = download_path
                    return (True, result, f"[{index}/{total}] ✓ Downloaded: {song['name']} - {song['artist']}")
                else:
                    return (False, result, f"[{index}/{total}] ✗ Download failed: {song['name']} - {song['artist']}")
            else:
                return (True, result, f"[{index}/{total}] ✓ Found: {song['name']} - {song['artist']}")
        else:
            # Search YouTube for Spotify songs
            yt_result = search_youtube_for_song(
                song['name'],
                song['artist'],
                download=download
            )
            result['youtube'] = yt_result
            
            if yt_result:
                if download and yt_result.get('download_path'):
                    return (True, result, f"[{index}/{total}] ✓ Downloaded: {song['name']} - {song['artist']}")
                else:
                    return (True, result, f"[{index}/{total}] ✓ Found: {song['name']} - {song['artist']}")
            else:
                return (False, result, f"[{index}/{total}] ✗ Not found: {song['name']} - {song['artist']}")
    except Exception as e:
        return (False, result, f"[{index}/{total}] ✗ Error: {song['name']} - {song['artist']}")

def main():
    print("=== Spotify & YouTube Music Song Finder & Downloader ===\n")
    
    # Choose source
    print("Select source:")
    print("1. Spotify")
    print("2. YouTube Music")
    print("3. Both")
    source_choice = input("\nEnter your choice (1-3): ")
    
    # Ask about downloading
    download_choice = input("\nDo you want to download the songs? (y/n): ").lower()
    download_songs = download_choice == 'y'
    
    if download_songs:
        print(f"\nDownload settings:")
        print(f"- Format: {AUDIO_FORMAT}")
        print(f"- Quality: {AUDIO_QUALITY} kbps")
        print(f"- Location: {DOWNLOAD_FOLDER}/")
        print(f"- Concurrent downloads: {MAX_CONCURRENT_DOWNLOADS}")
        print("\nNote: Requires FFmpeg to be installed on your system")
        input("\nPress Enter to continue...")
    
    all_songs = []
    
    # Spotify
    if source_choice in ['1', '3']:
        print("\n--- SPOTIFY ---")
        print("1. Liked songs")
        print("2. Playlists")
        print("3. Both")
        spotify_choice = input("\nEnter your choice (1-3): ")
        
        if spotify_choice in ['1', '3']:
            all_songs.extend(get_spotify_liked_songs())
        
        if spotify_choice in ['2', '3']:
            playlists = get_spotify_playlists()
            print("\nYour Spotify playlists:")
            for i, playlist in enumerate(playlists, 1):
                print(f"{i}. {playlist['name']} ({playlist['tracks_total']} tracks)")
            
            playlist_choice = input("\nEnter playlist numbers (comma-separated, or 'all'): ")
            
            if playlist_choice.lower() == 'all':
                selected_playlists = playlists
            else:
                indices = [int(x.strip()) - 1 for x in playlist_choice.split(',')]
                selected_playlists = [playlists[i] for i in indices if i < len(playlists)]
            
            for playlist in selected_playlists:
                print(f"\nFetching songs from '{playlist['name']}'...")
                songs = get_spotify_playlist_songs(playlist['id'])
                all_songs.extend(songs)
    
    # YouTube Music
    if source_choice in ['2', '3']:
        print("\n--- YOUTUBE MUSIC ---")
        print("1. Liked songs")
        print("2. Manual playlist URL")
        ytm_choice = input("\nEnter your choice (1-2): ")
        
        if ytm_choice == '1':
            all_songs.extend(get_ytmusic_liked_songs())
        elif ytm_choice == '2':
            playlist_url = input("\nEnter YouTube Music playlist URL: ")
            print(f"\nFetching songs from playlist...")
            songs = get_ytmusic_playlist_songs(playlist_url)
            all_songs.extend(songs)
            print(f"Found {len(songs)} songs in playlist")
    
    # Remove duplicates
    unique_songs = []
    seen = set()
    for song in all_songs:
        identifier = f"{song['name']}|{song['artist']}"
        if identifier not in seen:
            seen.add(identifier)
            unique_songs.append(song)
    
    print(f"\n\nTotal unique songs to process: {len(unique_songs)}")
    
    if len(unique_songs) > 1000:
        print(f"⚠ Warning: Processing {len(unique_songs)} songs will take a while!")
        cont = input("Continue? (y/n): ")
        if cont.lower() != 'y':
            return
    
    action = "Downloading" if download_songs else "Processing"
    print(f"\n{action} songs with {MAX_CONCURRENT_DOWNLOADS} concurrent workers...\n")
    
    results = []
    successful = 0
    
    # Process songs with threading for better performance
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        futures = {
            executor.submit(process_song, song, download_songs, i, len(unique_songs)): song
            for i, song in enumerate(unique_songs, 1)
        }
        
        for future in as_completed(futures):
            success, result, message = future.result()
            print(message)
            results.append(result)
            if success:
                successful += 1
    
    # Save results
    output_file = 'spotify_ytmusic_results.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    # Print summary
    print(f"\n\n=== Summary ===")
    print(f"Total songs processed: {len(unique_songs)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(unique_songs) - successful}")
    
    if download_songs:
        print(f"\nDownload location: {os.path.abspath(DOWNLOAD_FOLDER)}/")
    
    print(f"Results saved to: {output_file}")

if __name__ == "__main__":
    main()
