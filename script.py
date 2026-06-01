import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials
from spotipy.exceptions import SpotifyOauthError, SpotifyException
from yt_dlp import YoutubeDL
import time
import json
import os
import re
import shutil
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'y')


def env_list(name, default=None, sep=','):
    value = os.getenv(name)
    if value is None:
        return list(default) if default is not None else []
    return [item.strip() for item in value.split(sep) if item.strip()]


def guess_node_runtime():
    node_path = shutil.which('node')
    return f'node:{node_path}' if node_path else 'node'


def parse_args():
    parser = argparse.ArgumentParser(description='Download music from Spotify and YouTube using yt-dlp')
    parser.add_argument('-o', '--output-template', dest='output_template',
                        help='yt-dlp output template to use for saved files')
    return parser.parse_args()


# Load environment variables from .env file
load_dotenv()
# Spotify API credentials
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
SPOTIFY_CACHE_PATH = os.getenv('SPOTIFY_CACHE_PATH', '.spotify_cache')

# Download settings
DOWNLOAD_FOLDER = os.getenv('DOWNLOAD_FOLDER', 'downloaded_songs')
AUDIO_FORMAT = os.getenv('AUDIO_FORMAT', os.getenv('YTDLP_AUDIO_FORMAT', 'opus'))  # Options: opus, m4a, mp3, flac, wav
AUDIO_QUALITY = os.getenv('AUDIO_QUALITY', os.getenv('YTDLP_AUDIO_QUALITY', 'best'))  # Options: best, 256, 192, 160, 128
MAX_CONCURRENT_DOWNLOADS = int(os.getenv('MAX_CONCURRENT_DOWNLOADS', '3'))

# yt-dlp options (can be configured with environment variables)
YTDLP_FFMPEG_LOCATION = os.getenv('YTDLP_FFMPEG_LOCATION')
YTDLP_OUTPUT_TEMPLATE = os.getenv('YTDLP_OUTPUT_TEMPLATE')
YTDLP_DOWNLOAD_ARCHIVE = os.getenv('YTDLP_DOWNLOAD_ARCHIVE', 'channels_archive.txt')
YTDLP_RETRIES = int(os.getenv('YTDLP_RETRIES', '10'))
YTDLP_FRAGMENT_RETRIES = int(os.getenv('YTDLP_FRAGMENT_RETRIES', '10'))
YTDLP_RETRY_SLEEP = int(os.getenv('YTDLP_RETRY_SLEEP', '5'))
YTDLP_SLEEP_INTERVAL = int(os.getenv('YTDLP_SLEEP_INTERVAL', '2'))
YTDLP_MAX_SLEEP_INTERVAL = int(os.getenv('YTDLP_MAX_SLEEP_INTERVAL', '5'))
YTDLP_IGNORE_ERRORS = env_bool('YTDLP_IGNORE_ERRORS', True)
YTDLP_NO_ABORT_ON_ERROR = env_bool('YTDLP_NO_ABORT_ON_ERROR', True)
YTDLP_CONCURRENT_FRAGMENTS = int(os.getenv('YTDLP_CONCURRENT_FRAGMENTS', '4'))
YTDLP_JSRUNTIMES = env_list('YTDLP_JSRUNTIMES', default=[os.getenv('YTDLP_JS_RUNTIME', guess_node_runtime())])
YTDLP_REMOTE_COMPONENTS = env_list('YTDLP_REMOTE_COMPONENTS', default=['ejs:github'])
YTDLP_CONVERT_THUMBNAILS = os.getenv('YTDLP_CONVERT_THUMBNAILS', 'png')
YTDLP_EMBED_THUMBNAIL = env_bool('YTDLP_EMBED_THUMBNAIL', True)
YTDLP_ADD_METADATA = env_bool('YTDLP_ADD_METADATA', True)
YTDLP_METADATA_TEMPLATE = os.getenv('YTDLP_METADATA_TEMPLATE', '%(title)s:%(meta_title)s')

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


def is_spotify_app_premium_required_error(error):
    """Return True if Spotify API request failed due to app-owner Premium requirement."""
    if not isinstance(error, SpotifyException):
        return False

    error_text = str(error).lower()
    return (
        getattr(error, 'http_status', None) == 403 and
        'active premium subscription required for the owner of the app' in error_text
    )

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
            cache_path=SPOTIFY_CACHE_PATH
        )
        
        # If no cached token, provide manual authentication
        try:
            token_info = auth_manager.get_cached_token()
        except SpotifyOauthError as e:
            error_text = str(e).lower()
            if 'invalid_grant' in error_text or 'refresh token revoked' in error_text:
                print("⚠️ Spotify refresh token is no longer valid. Re-authentication required.")
                try:
                    if os.path.exists(SPOTIFY_CACHE_PATH):
                        os.remove(SPOTIFY_CACHE_PATH)
                        print("✓ Removed old Spotify token cache")
                except OSError as cache_error:
                    print(f"  ✗ Could not remove token cache: {cache_error}")
                token_info = None
            else:
                raise
        if not token_info:
            print("\n=== Spotify Authentication ===")
            print("No cached token found. Starting OAuth flow...\n")
            print(f"Using redirect URI: {SPOTIFY_REDIRECT_URI}\n")
            
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
                token_info = auth_manager.get_access_token(code, as_dict=False)
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
            print("⚠️  Spotify public URL fetching requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.")
            return None
    return sp_public


def ensure_dotenv_file():
    env_path = Path('.env')
    if env_path.exists():
        return
    if Path('example.env').exists():
        env_path.write_text(Path('example.env').read_text())
    else:
        env_path.write_text(
            "SPOTIFY_CLIENT_ID=\n"
            "SPOTIFY_CLIENT_SECRET=\n"
            "SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback\n\n"
            "AUDIO_FORMAT=opus\n"
            "AUDIO_QUALITY=best\n"
            "DOWNLOAD_FOLDER=downloaded_songs\n"
            "MAX_CONCURRENT_DOWNLOADS=3\n"
            "USE_ZOTIFY=false\n"
            "ZOTIFY_USERNAME=\n"
            "ZOTIFY_PASSWORD=\n"
        )
    print("✓ Created .env with default values.")


def set_env_var(key, value):
    env_path = Path('.env')
    if not env_path.exists():
        ensure_dotenv_file()
    lines = env_path.read_text().splitlines()
    key_prefix = f"{key}="
    updated = False
    for idx, line in enumerate(lines):
        if line.startswith(key_prefix):
            lines[idx] = f"{key}={value}"
            updated = True
            break
    if not updated:
        if lines and lines[-1] != '':
            lines.append('')
        lines.append(f"{key}={value}")
    env_path.write_text('\n'.join(lines) + '\n')


def prompt_for_spotify_credentials():
    global SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI
    if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
        return True

    print("\n=== Spotify API credentials required ===")
    print("Enter your Spotify Client ID, Client Secret, and redirect URI to access playlists, albums, or liked songs.")
    SPOTIFY_CLIENT_ID = input("SPOTIFY_CLIENT_ID: ").strip()
    SPOTIFY_CLIENT_SECRET = input("SPOTIFY_CLIENT_SECRET: ").strip()
    redirect_default = SPOTIFY_REDIRECT_URI or 'http://127.0.0.1:8888/callback'
    redirect_input = input(f"SPOTIFY_REDIRECT_URI [{redirect_default}]: ").strip()
    SPOTIFY_REDIRECT_URI = redirect_input or redirect_default

    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        print("✗ Both SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET are required to continue.")
        return False

    save = input("Save these credentials to .env? (y/n): ").strip().lower()
    if save == 'y':
        ensure_dotenv_file()
        set_env_var('SPOTIFY_CLIENT_ID', SPOTIFY_CLIENT_ID)
        set_env_var('SPOTIFY_CLIENT_SECRET', SPOTIFY_CLIENT_SECRET)
        set_env_var('SPOTIFY_REDIRECT_URI', SPOTIFY_REDIRECT_URI)
        print("✓ Saved Spotify credentials and redirect URI to .env")

    return True


YTMUSIC_COOKIE_FILE = 'ytmusic_cookie.txt'


def is_ytmusic_cookie_error(error):
    message = str(error).lower()
    return any(keyword in message for keyword in [
        'playlist does not exist',
        'this playlist does not exist',
        'login required',
        'sign in',
        'cookie',
        'authentication',
        'status code: 401',
        'status code: 403',
        'forbidden',
    ])


def prompt_for_ytmusic_cookie():
    print("\n=== YouTube Music Cookie Setup ===")
    print("Paste your YouTube Music cookie here:")
    print("(Get it from browser dev tools → Network → any request → cookie header)")
    cookie = input().strip()

    if not cookie:
        print("✗ Cookie cannot be empty. Please try again.")
        return prompt_for_ytmusic_cookie()

    with open(YTMUSIC_COOKIE_FILE, 'w', encoding='utf-8') as f:
        f.write(cookie)
    print("✓ Cookie saved")
    return cookie


def get_ytmusic_cookie(force_refresh=False):
    if force_refresh and os.path.exists(YTMUSIC_COOKIE_FILE):
        try:
            os.remove(YTMUSIC_COOKIE_FILE)
        except OSError:
            pass

    if not os.path.exists(YTMUSIC_COOKIE_FILE):
        return prompt_for_ytmusic_cookie()

    with open(YTMUSIC_COOKIE_FILE, 'r', encoding='utf-8') as f:
        cookie = f.read().strip()

    if not cookie:
        return prompt_for_ytmusic_cookie()

    return cookie


def write_ytmusic_cookiefile(cookie):
    cookie_lines = ['# Netscape HTTP Cookie File\n']
    for pair in cookie.split('; '):
        if '=' in pair:
            name, value = pair.split('=', 1)
            cookie_lines.append(f'.youtube.com\tTRUE\t/\tTRUE\t0\t{name}\t{value}\n')
    with open('cookies.txt', 'w', encoding='utf-8') as f:
        f.writelines(cookie_lines)


def extract_ytmusic_info(url):
    for attempt in range(2):
        cookie = get_ytmusic_cookie(force_refresh=(attempt > 0))
        write_ytmusic_cookiefile(cookie)
        try:
            with YoutubeDL({'quiet': True, 'no_warnings': True, 'extract_flat': True,
                           'cookiefile': 'cookies.txt'}) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            if attempt == 0 and is_ytmusic_cookie_error(e):
                print("\n⚠️ YouTube Music cookie appears invalid or expired.")
                print("Please paste a fresh cookie to continue.")
                get_ytmusic_cookie(force_refresh=True)
                continue
            raise


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

def download_youtube_audio(url, track_name, artist_name, subfolder=None, output_template=None):
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
        # Download best audio and prefer WebM first, then m4a, then any audio
        format_str = 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best'
        postprocessors = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'opus', 
                          'preferredquality': AUDIO_QUALITY if AUDIO_QUALITY != 'best' else '0'}]
    elif AUDIO_FORMAT == 'm4a':
        # Download best m4a/aac audio, fallback to any audio
        format_str = 'bestaudio[ext=m4a]/bestaudio/best'
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

    if YTDLP_ADD_METADATA:
        postprocessors.append({'key': 'FFmpegMetadata', 'add_metadata': True})
    if YTDLP_EMBED_THUMBNAIL:
        postprocessors.append({'key': 'EmbedThumbnail'})
    
    ytdlp_outtmpl = output_template or YTDLP_OUTPUT_TEMPLATE or f'{download_path}/%(uploader)s/%(title)s.%(ext)s'

    ydl_opts = {
        'format': format_str,
        'postprocessors': postprocessors,
        'outtmpl': ytdlp_outtmpl,
        'writethumbnail': True,
        'quiet': True,
        'no_warnings': True,
        'prefer_ffmpeg': True,
        'ffmpeg_location': YTDLP_FFMPEG_LOCATION,
        'download_archive': YTDLP_DOWNLOAD_ARCHIVE,
        'retries': YTDLP_RETRIES,
        'fragment_retries': YTDLP_FRAGMENT_RETRIES,
        'retry_sleep': YTDLP_RETRY_SLEEP,
        'sleep_interval': YTDLP_SLEEP_INTERVAL,
        'max_sleep_interval': YTDLP_MAX_SLEEP_INTERVAL,
        'ignoreerrors': YTDLP_IGNORE_ERRORS,
        'abort_on_error': not YTDLP_NO_ABORT_ON_ERROR,
        'concurrent_fragments': YTDLP_CONCURRENT_FRAGMENTS,
        'jsruntimes': YTDLP_JSRUNTIMES,
        'remote_components': YTDLP_REMOTE_COMPONENTS,
        'convert_thumbnails': YTDLP_CONVERT_THUMBNAILS,
        'embed_thumbnail': YTDLP_EMBED_THUMBNAIL,
        'add_metadata': YTDLP_ADD_METADATA,
        'extractaudio': True,
        'audioformat': AUDIO_FORMAT,
        'audioquality': AUDIO_QUALITY,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        },
        'postprocessor_args': ['-metadata', f'title={track_name}', '-metadata', f'artist={artist_name}',
                              '-metadata', f'album={subfolder if subfolder else "Downloaded"}'],
    }
    if os.path.exists('cookies.txt'):
        ydl_opts['cookiefile'] = 'cookies.txt'
    if YTDLP_METADATA_TEMPLATE:
        ydl_opts['metadata'] = [YTDLP_METADATA_TEMPLATE]
    
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return f"{download_path}/{safe_filename}.{AUDIO_FORMAT}"
    except:
        return None

def search_youtube_for_song(track_name, artist_name, download=False, subfolder=None, output_template=None):
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
                        video_info['url'], track_name, artist_name, subfolder, output_template=output_template)
                return video_info
    except:
        pass
    return None

def parse_spotify_url(url):
    patterns = [
        (r'spotify\.com/playlist/([a-zA-Z0-9]+)', 'playlist'),
        (r'spotify\.com/album/([a-zA-Z0-9]+)', 'album'),
        (r'spotify\.com/track/([a-zA-Z0-9]+)', 'track'),
        (r'spotify:playlist:([a-zA-Z0-9]+)', 'playlist'),
        (r'spotify:album:([a-zA-Z0-9]+)', 'album'),
        (r'spotify:track:([a-zA-Z0-9]+)', 'track'),
    ]
    for pattern, url_type in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), url_type
    return None, None

def get_spotify_playlist_from_url(spotify_url):
    item_id, url_type = parse_spotify_url(spotify_url)
    if not item_id or url_type not in ('playlist', 'album'):
        print(f"✗ Invalid Spotify URL (use playlist or album)")
        return None, []
    try:
        client = init_spotify() if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET else None
        if not client:
            client = init_spotify_public()
        if not client:
            print("✗ Spotify playlist/album lookup requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.")
            return None, []
        
        songs = []
        if url_type == 'album':
            album = client.album(item_id)
            collection_name = album['name']
            for track in album['tracks']['items']:
                songs.append({'name': track['name'],
                            'artist': ', '.join([a['name'] for a in track['artists']]),
                            'album': collection_name, 'uri': track['uri'],
                            'source': 'spotify', 'collection': collection_name})
        else:  # playlist
            playlist = client.playlist(item_id)
            collection_name = playlist['name']
            offset = 0
            while True:
                results = client.playlist_tracks(item_id, limit=100, offset=offset)
                if not results['items']:
                    break
                for item in results['items']:
                    if item['track']:
                        track = item['track']
                        songs.append({'name': track['name'], 
                                    'artist': ', '.join([a['name'] for a in track['artists']]),
                                    'album': track['album']['name'], 'uri': track['uri'],
                                    'source': 'spotify', 'collection': collection_name})
                offset += 100
                if len(results['items']) < 100:
                    break
        print(f"✓ Found: {collection_name} ({len(songs)} tracks)")
        return collection_name, songs
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
    try:
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
    except SpotifyException as e:
        if is_spotify_app_premium_required_error(e):
            print("\n✗ Spotify API denied access to liked songs.")
            print("  Active Premium subscription is required for the Spotify app owner.")
            print("  Use credentials from an app owned by a Premium account, then retry.")
            return []
        print(f"\n✗ Spotify API error while fetching liked songs: {e}")
        return []
    except Exception as e:
        print(f"\n✗ Error while fetching liked songs: {e}")
        return []
    print(f"\nFound {len(liked_songs)} songs")
    return liked_songs

def get_spotify_playlists():
    sp = init_spotify()
    if not sp:
        return []
    playlists = []
    offset = 0
    try:
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
    except SpotifyException as e:
        if is_spotify_app_premium_required_error(e):
            print("\n✗ Spotify API denied access to playlists.")
            print("  Active Premium subscription is required for the Spotify app owner.")
            print("  Use credentials from an app owned by a Premium account, then retry.")
            return []
        print(f"\n✗ Spotify API error while fetching playlists: {e}")
        return []
    except Exception as e:
        print(f"\n✗ Error while fetching playlists: {e}")
        return []
    return playlists

def get_spotify_playlist_songs(playlist_id, playlist_name):
    sp = init_spotify()
    if not sp:
        return []
    songs = []
    offset = 0
    try:
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
    except SpotifyException as e:
        if is_spotify_app_premium_required_error(e):
            print(f"  ✗ Spotify API denied playlist tracks for '{playlist_name}'.")
            print("    Active Premium subscription is required for the Spotify app owner.")
            print("    Use credentials from an app owned by a Premium account, then retry.")
            return []
        print(f"  ✗ Spotify API error for '{playlist_name}': {e}")
        return []
    except Exception as e:
        print(f"  ✗ Error fetching '{playlist_name}': {e}")
        return []
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
    liked_songs = []
    try:
        result = extract_ytmusic_info('https://music.youtube.com/playlist?list=LM')
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

    songs = []
    playlist_name = 'YouTube Music Playlist'
    try:
        result = extract_ytmusic_info(playlist_url)
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

def process_song(song, download, index, total, output_template=None):
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
                download_path = download_youtube_audio(video_url, song['name'], song['artist'], safe_subfolder, output_template=output_template)
                if download_path:
                    result['youtube']['download_path'] = download_path
                    return (True, result, f"[{index}/{total}] ✓ YouTube: {song['name']} - {song['artist']}")
                else:
                    return (False, result, f"[{index}/{total}] ✗ Failed: {song['name']}")
            else:
                return (True, result, f"[{index}/{total}] ✓ Found: {song['name']}")
        
        yt_result = search_youtube_for_song(song['name'], song['artist'], download=download, subfolder=safe_subfolder, output_template=output_template)
        result['youtube'] = yt_result
        if yt_result:
            if download:
                if yt_result.get('download_path'):
                    return (True, result, f"[{index}/{total}] ✓ YouTube: {song['name']} - {song['artist']}")
                return (False, result, f"[{index}/{total}] ✗ Failed: {song['name']}")
            return (True, result, f"[{index}/{total}] ✓ Found: {song['name']}")
        return (False, result, f"[{index}/{total}] ✗ Not found: {song['name']}")
    except Exception as e:
        return (False, result, f"[{index}/{total}] ✗ Error: {song['name']}")

def main():
    args = parse_args()
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
            spotify_credentials_ok = True
            if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
                spotify_credentials_ok = prompt_for_spotify_credentials()

            if spotify_credentials_ok:
                print("1. Liked\n2. Playlists\n3. Both\n4. Public URL (playlist/album)")
                spotify_choice = input("\nChoice (1-4): ")
                if spotify_choice in ['1', '3']:
                    all_songs.extend(get_spotify_liked_songs())
                if spotify_choice in ['2', '3']:
                    playlists = get_spotify_playlists()
                    if not playlists:
                        print("\n✗ No Spotify playlists available (or access denied).")
                    else:
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
                print("⚠️  Spotify cannot be used without API credentials.")
                if source_choice == '1':
                    print("Exiting because Spotify was the only selected source.")
                    return
                else:
                    print("Continuing with YouTube Music only.")
        
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
        futures = {executor.submit(process_song, song, download_songs, i, len(unique_songs), args.output_template): song
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
