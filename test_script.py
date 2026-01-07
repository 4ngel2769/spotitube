"""Tests - Run with pytest test_script.py -v"""
import pytest
from unittest.mock import patch, MagicMock
import script


class TestSpotifyUrlParsing:
    def test_playlist_url_standard(self):
        playlist_id, url_type = script.parse_spotify_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M")
        assert playlist_id == "37i9dQZF1DXcBWIGoYBM5M" and url_type == "playlist"
    
    def test_playlist_url_with_params(self):
        playlist_id, url_type = script.parse_spotify_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123")
        assert playlist_id == "37i9dQZF1DXcBWIGoYBM5M" and url_type == "playlist"
    
    def test_track_url(self):
        track_id, url_type = script.parse_spotify_url("https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh")
        assert track_id == "4iV5W9uYEdYUVa79Axb7Rh" and url_type == "track"
    
    def test_spotify_uri_playlist(self):
        playlist_id, url_type = script.parse_spotify_url("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")
        assert playlist_id == "37i9dQZF1DXcBWIGoYBM5M" and url_type == "playlist"
    
    def test_spotify_uri_track(self):
        track_id, url_type = script.parse_spotify_url("spotify:track:4iV5W9uYEdYUVa79Axb7Rh")
        assert track_id == "4iV5W9uYEdYUVa79Axb7Rh" and url_type == "track"
    
    def test_invalid_url(self):
        assert script.parse_spotify_url("https://example.com/not-spotify") == (None, None)
    
    def test_empty_string(self):
        assert script.parse_spotify_url("") == (None, None)


class TestYouTubeUrlParsing:
    def test_youtube_music_playlist(self):
        assert script.parse_youtube_url("https://music.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf") == "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    
    def test_youtube_standard_playlist(self):
        assert script.parse_youtube_url("https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf") == "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    
    def test_youtube_video_with_list(self):
        assert script.parse_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf") == "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    
    def test_liked_music_playlist(self):
        assert script.parse_youtube_url("https://music.youtube.com/playlist?list=LM") == "LM"
    
    def test_invalid_url(self):
        assert script.parse_youtube_url("https://example.com/not-youtube") is None
    
    def test_empty_string(self):
        assert script.parse_youtube_url("") is None


class TestFilenameSanitization:
    @staticmethod
    def sanitize(artist, track):
        return "".join(c for c in f"{artist} - {track}" if c.isalnum() or c in (' ', '-', '_')).strip()
    
    def test_basic_filename(self):
        assert self.sanitize("Artist Name", "Track Name") == "Artist Name - Track Name"
    
    def test_special_characters_removed(self):
        safe = self.sanitize("Artist/Name:Test", "Track<>Name")
        assert all(c not in safe for c in "/:><")
    
    def test_unicode_preserved(self):
        assert len(self.sanitize("アーティスト", "トラック")) > 0
    
    def test_emoji_removed(self):
        safe = self.sanitize("Artist 🎵", "Song 💿")
        assert "🎵" not in safe and "💿" not in safe


class TestEnvironmentVariables:
    def test_audio_format(self):
        assert script.AUDIO_FORMAT in ['opus', 'm4a', 'mp3', 'flac', 'wav']
    
    def test_audio_quality(self):
        assert script.AUDIO_QUALITY in ['best', '256', '192', '160', '128']
    
    def test_download_folder(self):
        assert script.DOWNLOAD_FOLDER and len(script.DOWNLOAD_FOLDER) > 0
    
    def test_max_concurrent_downloads(self):
        assert isinstance(script.MAX_CONCURRENT_DOWNLOADS, int) and script.MAX_CONCURRENT_DOWNLOADS > 0


class TestProcessSong:
    @patch('script.search_youtube_for_song')
    def test_spotify_song_found(self, mock_search):
        mock_search.return_value = {'title': 'Test', 'url': 'https://youtube.com/watch?v=test123', 'id': 'test123'}
        song = {'name': 'Test', 'artist': 'Artist', 'album': 'Album', 'source': 'spotify', 'collection': 'Playlist'}
        success, _, message = script.process_song(song, download=False, index=1, total=1)
        assert success and mock_search.called
    
    @patch('script.search_youtube_for_song')
    def test_spotify_song_not_found(self, mock_search):
        mock_search.return_value = None
        song = {'name': 'Unknown', 'artist': 'Unknown', 'album': 'Unknown', 'source': 'spotify', 'collection': 'Playlist'}
        success, _, message = script.process_song(song, download=False, index=1, total=1)
        assert not success and "Not found" in message
    
    @patch('script.download_youtube_audio')
    def test_ytmusic_song_with_video_id(self, mock_download):
        mock_download.return_value = '/path/to/file.opus'
        song = {'name': 'Song', 'artist': 'Artist', 'album': 'Unknown', 'videoId': 'abc123', 'source': 'ytmusic', 'collection': 'Liked'}
        success, result, _ = script.process_song(song, download=True, index=1, total=1)
        assert success and result['youtube']['id'] == 'abc123'


class TestInputValidation:
    @staticmethod
    def parse(choice):
        return [int(x.strip())-1 for x in choice.split(',') if x.strip()]
    
    def test_comma_separated(self):
        assert self.parse("1, 2, 3") == [0, 1, 2]
    
    def test_single_number(self):
        assert self.parse("5") == [4]
    
    def test_trailing_comma(self):
        assert self.parse("1,2,3,") == [0, 1, 2]
    
    def test_with_spaces(self):
        assert self.parse("  1  ,  2  ,  3  ") == [0, 1, 2]
    
    def test_empty_input(self):
        assert self.parse("") == []
    
    def test_bounds_checking(self):
        playlists = [{'id': '1'}, {'id': '2'}, {'id': '3'}]
        indices = self.parse("1, 5, 2")
        selected = [playlists[i] for i in indices if 0 <= i < len(playlists)]
        assert len(selected) == 2


class TestDeduplication:
    @staticmethod
    def dedupe(songs):
        seen, unique = set(), []
        for s in songs:
            key = f"{s['name']}|{s['artist']}"
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return unique
    
    def test_removes_duplicates(self):
        songs = [{'name': 'A', 'artist': '1'}, {'name': 'B', 'artist': '2'}, {'name': 'A', 'artist': '1'}]
        assert len(self.dedupe(songs)) == 2
    
    def test_keeps_different_versions(self):
        songs = [{'name': 'A', 'artist': '1'}, {'name': 'A', 'artist': '2'}]
        assert len(self.dedupe(songs)) == 2


class TestPlaylistsFile:
    def test_not_exists(self):
        with patch('os.path.exists', return_value=False):
            assert script.process_playlists_file() == []


class TestSpotifyAPI:
    @patch('script.sp')
    @patch('script.init_spotify')
    def test_get_playlists(self, mock_init, mock_sp):
        mock_client = MagicMock()
        mock_init.return_value = mock_client
        mock_client.current_user_playlists.return_value = {
            'items': [{'id': 'p1', 'name': 'Playlist', 'tracks': {'total': 10}}]
        }
        script.sp = mock_client
        playlists = script.get_spotify_playlists()
        assert len(playlists) == 1 and playlists[0]['tracks_total'] == 10
    
    @patch('script.sp')
    @patch('script.init_spotify')
    def test_get_liked_songs_empty(self, mock_init, mock_sp):
        mock_client = MagicMock()
        mock_init.return_value = mock_client
        mock_client.current_user_saved_tracks.return_value = {'items': []}
        script.sp = mock_client
        assert len(script.get_spotify_liked_songs()) == 0


class TestEndToEnd:
    @patch('script.search_youtube_for_song')
    def test_full_workflow(self, mock_search):
        mock_search.return_value = {'title': 'Song', 'url': 'https://youtube.com/watch?v=xyz', 'id': 'xyz', 'download_path': '/file.opus'}
        songs = [{'name': f'Song {i}', 'artist': f'Artist {i}', 'source': 'spotify', 'collection': 'Test'} for i in range(2)]
        results = [script.process_song(s, download=True, index=i+1, total=2) for i, s in enumerate(songs)]
        assert all(r[0] for r in results) and mock_search.call_count == 2
    
    @patch('script.search_youtube_for_song')
    def test_partial_failures(self, mock_search):
        mock_search.side_effect = [{'title': 'Song', 'url': 'https://youtube.com/watch?v=abc', 'id': 'abc'}, None]
        songs = [{'name': f'Song {i}', 'artist': f'Artist {i}', 'source': 'spotify', 'collection': 'Test'} for i in range(2)]
        results = [script.process_song(s, download=False, index=i+1, total=2) for i, s in enumerate(songs)]
        assert results[0][0] and not results[1][0]


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
