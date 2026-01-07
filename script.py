import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from yt_dlp import YoutubeDL
import time
import json
import os
import re
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
AUDIO_FORMAT = os.getenv('AUDIO_FORMAT', 'opus')  # Options: opus, m4a, mp3, flac, wav
AUDIO_QUALITY = os.getenv('AUDIO_QUALITY', 'best')  # Options: best, 256, 192, 160, 128
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))

# Audio format quality guide for user reference
# opus: Best efficiency. Good quality at lower bitrates.
# m4a (AAC): Good efficiency, widely compatible.
# mp3: Legacy format for compatibility (older mp3 players).
# flac: Lossless, but YouTube doesn't have lossless audio (it's transcoded from lossy).
# wav: Uncompressed, huge files, same issue as flac (transcoded from lossy source).

# Zotify settings
USE_ZOTIFY = os.getenv('USE_ZOTIFY', 'false').lower() == 'true'
ZOTIFY_USERNAME = os.getenv('ZOTIFY_USERNAME', '')
ZOTIFY_PASSWORD = os.getenv('ZOTIFY_PASSWORD', '')

# Initialize clients
sp = None
sp_public = None
zotify_available = False

def check_zotify():
    global zotify_available
    try:
        import librespot
        from zotify import Zotify
        if USE_ZOTIFY and ZOTIFY_USERNAME and ZOTIFY_PASSWORD:
            zotify_available = True
            print("✓ Zotify integration enabled")
            return True
        elif USE_ZOTIFY:
            print("⚠️  Zotify enabled but missing credentials")
    except ImportError:
        if USE_ZOTIFY:
            print("⚠️  Zotify not installed. Install: pip install zotify")
    return False

def init_spotify():
    """Initialize Spotify client"""
    global sp
    if sp is None and SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        auth_manager = SpotifyOAuth(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
            redirect_uri=SPOTIFY_REDIRECT_URI,
            scope='user-library-read playlist-read-private',
            open_browser=False,  # Don't auto-open on headless servers
            cache_path='.spotify_cache'
        )
        
        # If no cached token, provide manual authentication
        token_info = auth_manager.get_cached_token()
        if not token_info:
            print("\n=== Spotify Authentication ===")
            print("No cached token found. Starting OAuth flow...\n")
            
            # Get the authorization URL
            auth_url = auth_manager.get_authorize_url()
            print("="*70)
            print("STEP 1: Open this URL:\n")
            print(f"{auth_url}\n")
            print("="*70)
            print("\nSTEP 2: Paste the redirect URL:")
            print("="*70)
            response_url = input("\nPaste URL: ").strip()
            
            try:
                # Parse the authorization code from the URL
                code = auth_manager.parse_response_code(response_url)
                token_info = auth_manager.get_access_token(code)
                print("\n✓ Successfully authenticated! Token saved for future use.")
            except Exception as e:
                print(f"\n✗ Failed: {e}")
                raise
        
        sp = spotipy.Spotify(auth_manager=auth_manager)
    return sp

def init_spotify_public():
    global sp_public
    if sp_public is None:
        if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
            auth_manager = SpotifyClientCredentials(
                client_id=SPOTIFY_CLIENT_ID,
                client_secret=SPOTIFY_CLIENT_SECRET
            )
            sp_public = spotipy.Spotify(auth_manager=auth_manager)
        else:
            sp_public = spotipy.Spotify()
    return sp_public

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
        print(f"✓ Cookie saved")
        return cookie
    with open(cookie_file, 'r') as f:
        return f.read().strip()

def download_with_zotify(track_uri, track_name, artist_name, subfolder=None):
    if not zotify_available:
        return None
    try:
        from zotify import Zotify
        if subfolder:
            download_path = os.path.join(DOWNLOAD_FOLDER, subfolder)
        else:
            download_path = DOWNLOAD_FOLDER
        Path(download_path).mkdir(parents=True, exist_ok=True)
        Zotify.CONFIG.ROOT_PATH = download_path
        Zotify.CONFIG.DOWNLOAD_FORMAT = 'ogg'
        if not Zotify.is_authenticated():
            Zotify.login(ZOTIFY_USERNAME, ZOTIFY_PASSWORD)
        output_file = Zotify.download_track(track_uri)
        if output_file and os.path.exists(output_file):
            return output_file
    except Exception as e:
        print(f"  ✗ Zotify failed: {e}")
    return None

def download_youtube_audio(url, track_name, artist_name, subfolder=None):
    """Download audio from YouTube"""
    # Determine the download path
    if subfolder:
        download_path = os.path.join(DOWNLOAD_FOLDER, subfolder)
    else:
        download_path = DOWNLOAD_FOLDER
    
    Path(download_path).mkdir(parents=True, exist_ok=True)
    
    safe_filename = "".join(c for c in f"{artist_name} - {track_name}" 
                           if c.isalnum() or c in (' ', '-', '_')).strip()

    # Configure format selection based on user preference
    if AUDIO_FORMAT == 'opus':
        # Download best opus audio
        format_str = 'bestaudio[ext=webm]/bestaudio'
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'opus', 
                          'preferredquality': AUDIO_QUALITY if AUDIO_QUALITY != 'best' else '0'}]
    elif AUDIO_FORMAT == 'm4a':
        # Download best m4a/aac audio
        format_str = 'bestaudio[ext=m4a]/bestaudio'
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'aac',
                          'preferredquality': AUDIO_QUALITY if AUDIO_QUALITY != 'best' else '0'}]
    elif AUDIO_FORMAT == 'flac':
        # Lossless but source is lossy (YouTube)
        format_str = 'bestaudio/best'
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'flac'}]
    elif AUDIO_FORMAT == 'wav':
        # Uncompressed but source is lossy (YouTube)
        format_str = 'bestaudio/best'
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'wav'}]
    else:  # mp3 re-encoding
        format_str = 'bestaudio/best'
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3',
                          'preferredquality': AUDIO_QUALITY if AUDIO_QUALITY != 'best' else '320'}]
    # Add metadata and thumbnail
    postprocessors.extend([
        {'key': 'FFmpegMetadata', 'add_metadata': True},
        {'key': 'EmbedThumbnail'}
    ])
    
    ydl_opts = {
        'format': format_str,
        'postprocessors': postprocessors,
        'outtmpl': f'{download_path}/{safe_filename}.%(ext)s',
        'writethumbnail': True,
        'quiet': True,
        'no_warnings': True,
        'prefer_ffmpeg': True,
        # Add metadata for better Navidrome compatibility
        'postprocessor_args': ['-metadata', f'title={track_name}', '-metadata', f'artist={artist_name}',
                              '-metadata', f'album={subfolder if subfolder else "Downloaded"}'],
    }
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return f"{download_path}/{safe_filename}.{AUDIO_FORMAT}"
    except:
        return None

def search_youtube_for_song(track_name, artist_name, download=False, subfolder=None):
    query = f"{track_name} {artist_name}"
    try:
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True, 
                       'default_search': 'ytsearch1'}) as ydl:
            result = ydl.extract_info(f"ytsearch1:{query}", download=False)
            if result and 'entries' in result and result['entries']:
                video = result['entries'][0]
                video_info = {'title': video.get('title', ''), 
                            'url': f"https://www.youtube.com/watch?v={video['id']}", 'id': video['id']}
                if download:
                    video_info['download_path'] = download_youtube_audio(
                        video_info['url'], track_name, artist_name, subfolder)
                return video_info
    except:
        pass
    return None

def parse_spotify_url(url):
    patterns = [r'spotify\.com/playlist/([a-zA-Z0-9]+)', r'spotify\.com/track/([a-zA-Z0-9]+)',
                r'spotify:playlist:([a-zA-Z0-9]+)', r'spotify:track:([a-zA-Z0-9]+)']
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), 'playlist' if 'playlist' in pattern else 'track'
    return None, None

def get_spotify_playlist_from_url(playlist_url):
    playlist_id, url_type = parse_spotify_url(playlist_url)
    if not playlist_id or url_type != 'playlist':
        print(f"✗ Invalid Spotify URL")
        return None, []
    try:
        client = init_spotify() if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET else None
        if not client:
            client = init_spotify_public()
        playlist = client.playlist(playlist_id)
        playlist_name = playlist['name']
        songs = []
        offset = 0
        while True:
            results = client.playlist_tracks(playlist_id, limit=100, offset=offset)
            if not results['items']:
                break
            for item in results['items']:
                if item['track']:
                    track = item['track']
                    songs.append({'name': track['name'], 
                                'artist': ', '.join([a['name'] for a in track['artists']]),
                                'album': track['album']['name'], 'uri': track['uri'],
                                'source': 'spotify', 'collection': playlist_name})
            offset += 100
            if len(results['items']) < 100:
                break
        print(f"✓ Found: {playlist_name} ({len(songs)} tracks)")
        return playlist_name, songs
    except Exception as e:
        print(f"✗ Error: {e}")
        return None, []

def get_spotify_liked_songs():
    sp = init_spotify()
    if not sp:
        return []
    print("Fetching Spotify liked songs...")
    liked_songs = []
    offset = 0
    while True:
        results = sp.current_user_saved_tracks(limit=50, offset=offset)
        if not results['items']:
            break
        for item in results['items']:
            track = item['track']
            liked_songs.append({'name': track['name'], 
                              'artist': ', '.join([a['name'] for a in track['artists']]),
                              'album': track['album']['name'], 'uri': track['uri'],
                              'source': 'spotify', 'collection': 'Spotify Liked Songs'})
        offset += 50
        print(f"  Fetched {len(liked_songs)} songs...", end='\r')
        if len(results['items']) < 50:
            break
    print(f"\nFound {len(liked_songs)} songs")
    return liked_songs

def get_spotify_playlists():
    sp = init_spotify()
    if not sp:
        return []
    playlists = []
    offset = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        if not results['items']:
            break
        for p in results['items']:
            playlists.append({'id': p['id'], 'name': p['name'], 
                            'tracks_total': p['tracks']['total'], 'source': 'spotify'})
        offset += 50
        if len(results['items']) < 50:
            break
    return playlists

def get_spotify_playlist_songs(playlist_id, playlist_name):
    sp = init_spotify()
    if not sp:
        return []
    songs = []
    offset = 0
    while True:
        results = sp.playlist_tracks(playlist_id, limit=100, offset=offset)
        if not results['items']:
            break
        for item in results['items']:
            if item['track']:
                track = item['track']
                songs.append({'name': track['name'], 
                            'artist': ', '.join([a['name'] for a in track['artists']]),
                            'album': track['album']['name'], 'uri': track['uri'],
                            'source': 'spotify', 'collection': playlist_name})
        offset += 100
        if len(results['items']) < 100:
            break
    return songs

# ============ YOUTUBE MUSIC FUNCTIONS ============
def parse_youtube_url(url):
    patterns = [r'list=([a-zA-Z0-9_-]+)', r'youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)',
                r'music\.youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)']
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_ytmusic_liked_songs():
    cookie = get_ytmusic_cookie()
    cookie_lines = ['# Netscape HTTP Cookie File\n']
    for pair in cookie.split('; '):
        if '=' in pair:
            name, value = pair.split('=', 1)
            cookie_lines.append(f'.youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n')
    with open('cookies.txt', 'w') as f:
        f.writelines(cookie_lines)
    
    liked_songs = []
    try:
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True, 
                       'cookiefile': 'cookies.txt'}) as ydl:
            result = ydl.extract_info('https://music.youtube.com/playlist?list=LM', download=False)
            if result and 'entries' in result:
                for entry in result['entries']:
                    try:
                        if entry:
                            title = entry.get('title', 'Unknown')
                            if ' - ' in title:
                                artist, song = title.split(' - ', 1)
                            else:
                                artist, song = entry.get('uploader', 'Unknown'), title
                            liked_songs.append({'name': song.strip(), 'artist': artist.strip(),
                                              'album': 'Unknown', 'videoId': entry.get('id', ''),
                                              'source': 'ytmusic', 'collection': 'YouTube Music Liked Songs'})
                            print(f"  Fetched {len(liked_songs)} songs...", end='\r')
                    except:
                        continue
    except Exception as e:
        print(f"\n✗ Error: {e}")
        return []
    print(f"\nFound {len(liked_songs)} songs")
    return liked_songs

def get_ytmusic_playlist_from_url(playlist_url):
    playlist_id = parse_youtube_url(playlist_url)
    if not playlist_id:
        print("✗ Invalid YouTube URL")
        return None, []
    cookie = get_ytmusic_cookie()
    cookie_lines = ['# Netscape HTTP Cookie File\n']
    for pair in cookie.split('; '):
        if '=' in pair:
            name, value = pair.split('=', 1)
            cookie_lines.append(f'.youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n')
    with open('cookies.txt', 'w') as f:
        f.writelines(cookie_lines)
    
    songs = []
    playlist_name = 'YouTube Music Playlist'
    try:
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True,
                       'cookiefile': 'cookies.txt'}) as ydl:
            result = ydl.extract_info(playlist_url, download=False)
            if result and 'title' in result:
                playlist_name = result['title']
            if result and 'entries' in result:
                for entry in result['entries']:
                    try:
                        if entry:
                            title = entry.get('title', 'Unknown')
                            if ' - ' in title:
                                artist, song = title.split(' - ', 1)
                            else:
                                artist, song = entry.get('uploader', 'Unknown'), title
                            songs.append({'name': song.strip(), 'artist': artist.strip(),
                                        'album': 'Unknown', 'videoId': entry.get('id', ''),
                                        'source': 'ytmusic', 'collection': playlist_name})
                    except:
                        continue
        print(f"✓ Found: {playlist_name} ({len(songs)} tracks)")
    except Exception as e:
        print(f"✗ Error: {e}")
    return playlist_name, songs

def process_playlists_file():
    if not os.path.exists('playlists.txt'):
        return []
    print("\n📁 Processing playlists.txt...")
    all_songs = []
    with open('playlists.txt', 'r', encoding='utf-8') as f:
        urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    print(f"Found {len(urls)} URLs\n")
    for i, url in enumerate(urls, 1):
        print(f"[{i}/{len(urls)}] {url}")
        if 'spotify.com' in url or 'spotify:' in url:
            _, songs = get_spotify_playlist_from_url(url)
            if songs:
                all_songs.extend(songs)
        elif 'youtube.com' in url or 'music.youtube.com' in url:
            _, songs = get_ytmusic_playlist_from_url(url)
            if songs:
                all_songs.extend(songs)
        else:
            print("  ✗ Unrecognized URL")
        print()
    return all_songs

def process_song(song, download, index, total):
    result = {'spotify': song, 'youtube': None}
    collection = song.get('collection', 'Unknown')
    safe_subfolder = "".join(c for c in collection if c.isalnum() or c in (' ', '-', '_')).strip()
    try:
        if song.get('source') == 'spotify' and download and zotify_available:
            spotify_path = download_with_zotify(song.get('uri'), song['name'], song['artist'], safe_subfolder)
            if spotify_path:
                result['spotify_direct'] = True
                result['download_path'] = spotify_path
                return (True, result, f"[{index}/{total}] ✓ Spotify: {song['name']} - {song['artist']}")
        
        if song.get('source') == 'ytmusic' and song.get('videoId'):
            video_url = f"https://www.youtube.com/watch?v={song['videoId']}"
            result['youtube'] = {'title': song['name'], 'url': video_url, 'id': song['videoId']}
            if download:
                download_path = download_youtube_audio(video_url, song['name'], song['artist'], safe_subfolder)
                if download_path:
                    result['youtube']['download_path'] = download_path
                    return (True, result, f"[{index}/{total}] ✓ YouTube: {song['name']} - {song['artist']}")
                else:
                    return (False, result, f"[{index}/{total}] ✗ Failed: {song['name']}")
            else:
                return (True, result, f"[{index}/{total}] ✓ Found: {song['name']}")
        
        yt_result = search_youtube_for_song(song['name'], song['artist'], download=download, subfolder=safe_subfolder)
        result['youtube'] = yt_result
        if yt_result:
            if download and yt_result.get('download_path'):
                return (True, result, f"[{index}/{total}] ✓ YouTube: {song['name']} - {song['artist']}")
            else:
                return (True, result, f"[{index}/{total}] ✓ Found: {song['name']}")
        else:
            return (False, result, f"[{index}/{total}] ✗ Not found: {song['name']}")
    except Exception as e:
        return (False, result, f"[{index}/{total}] ✗ Error: {song['name']}")

def main():
    print("=== Spotify & YouTube Music Downloader ===\n")
    check_zotify()
    print("\n⚠️  Audio quality info:")
    print("YouTube Music: 256kbps AAC/Opus (premium), 128-160kbps (free)")
    if zotify_available:
        print("✓ Zotify: Spotify OGG Vorbis ~320kbps → YouTube fallback")
    print(f"\nFormat: {AUDIO_FORMAT} | Quality: {AUDIO_QUALITY}\n")
    
    all_songs = []
    if os.path.exists('playlists.txt'):
        use_file = input("Process playlists.txt? (y/n): ").lower()
        if use_file == 'y':
            all_songs.extend(process_playlists_file())
            if all_songs:
                download_songs = input("\nDownload? (y/n): ").lower() == 'y'
            else:
                print("\n✗ No songs found")
                return
    
    if not all_songs:
        print("Source:")
        print("1. Spotify")
        print("2. YouTube Music")
        print("3. Both")
        source_choice = input("\nChoice (1-3): ")
        download_songs = input("\nDownload? (y/n): ").lower() == 'y'
        
        if source_choice in ['1', '3']:
            print("\n--- SPOTIFY ---")
            if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
                print("1. Liked\n2. Playlists\n3. Both\n4. Public URL")
                spotify_choice = input("\nChoice (1-4): ")
                if spotify_choice in ['1', '3']:
                    all_songs.extend(get_spotify_liked_songs())
                if spotify_choice in ['2', '3']:
                    playlists = get_spotify_playlists()
                    print("\nPlaylists:")
                    for i, p in enumerate(playlists, 1):
                        print(f"{i}. {p['name']} ({p['tracks_total']})")
                    
                    selected = []
                    while not selected:
                        choice = input("\nNumbers (comma-separated or 'all'): ").strip()
                        if not choice:
                            print("Please enter at least one number or 'all'.")
                            continue
                        if choice.lower() == 'all':
                            selected = playlists
                        else:
                            try:
                                indices = [int(x.strip())-1 for x in choice.split(',') if x.strip()]
                                selected = [playlists[i] for i in indices if 0 <= i < len(playlists)]
                                if not selected:
                                    print("No valid playlists selected. Try again.")
                            except ValueError:
                                print("Invalid input. Enter numbers separated by commas or 'all'.")
                    
                    for p in selected:
                        print(f"\nFetching '{p['name']}'...")
                        all_songs.extend(get_spotify_playlist_songs(p['id'], p['name']))
                if spotify_choice == '4':
                    url = input("\nSpotify URL: ")
                    _, songs = get_spotify_playlist_from_url(url)
                    all_songs.extend(songs)
            else:
                print("⚠️  No credentials. Public URL only.")
                url = input("Spotify URL: ")
                _, songs = get_spotify_playlist_from_url(url)
                all_songs.extend(songs)
        
        if source_choice in ['2', '3']:
            print("\n--- YOUTUBE MUSIC ---")
            print("1. Liked\n2. Playlist URL")
            ytm_choice = input("\nChoice (1-2): ")
            if ytm_choice == '1':
                all_songs.extend(get_ytmusic_liked_songs())
            elif ytm_choice == '2':
                url = input("\nYouTube Music URL: ")
                _, songs = get_ytmusic_playlist_from_url(url)
                all_songs.extend(songs)
    # Remove duplicates
    unique_songs = []
    seen = set()
    for song in all_songs:
        identifier = f"{song['name']}|{song['artist']}"
        if identifier not in seen:
            seen.add(identifier)
            unique_songs.append(song)
    
    print(f"\n\nTotal: {len(unique_songs)} unique songs")
    if len(unique_songs) > 1000:
        if input("⚠ 1000+ songs. Continue? (y/n): ").lower() != 'y':
            return
    
    action = "Downloading" if download_songs else "Processing"
    print(f"\n{action} with {MAX_CONCURRENT_DOWNLOADS} workers...\n")
    
    results = []
    successful = 0
    
    # Process songs with threading for better performance
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        futures = {executor.submit(process_song, song, download_songs, i, len(unique_songs)): song
                  for i, song in enumerate(unique_songs, 1)}
        for future in as_completed(futures):
            success, result, message = future.result()
            print(message)
            results.append(result)
            if success:
                successful += 1
    
    with open('results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n\n=== Summary ===")
    print(f"Processed: {len(unique_songs)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(unique_songs) - successful}")
    if download_songs:
        spotify_direct = sum(1 for r in results if r.get('spotify_direct'))
        if spotify_direct:
            print(f"Direct Spotify: {spotify_direct}")
        print(f"\nLocation: {os.path.abspath(DOWNLOAD_FOLDER)}/")
    print(f"Results: results.json")

if __name__ == "__main__":
    main()
