import sys
sys.stdout.reconfigure(encoding='utf-8')
import unittest
from core.lyrics_engine import (
    LyricsEngine, LRCLIBClient, YouTubeDescriptionLyricsClient,
    SpotifyLyricsClient, LyricsTrack, LyricsLine, LyricsWord,
    get_song_candidates, clean_song_title
)

class TestNewLyricsFeatures(unittest.TestCase):
    def test_candidates_cleaning_and_channels(self):
        title = "Main Tera Boyfriend Song | Raabta | Sushant Singh Rajput | Kriti Sanon | Arijit S"
        artist = "T-Series"
        cands = get_song_candidates(title, artist)
        self.assertTrue(len(cands) > 0)
        track_names = [c[0].lower() for c in cands]
        self.assertIn("main tera boyfriend", track_names)
        # Verify T-Series was stripped from artist
        for _, a in cands:
            self.assertNotEqual(a.lower(), "t-series")

    def test_baawli_description_extraction(self):
        sample_info = {
            'title': 'Baawli Official Visualizer : Suyash | Danny | Avvy Ballagan',
            'duration': 180.0,
            'description': """
Song - Baawli
Singer - Suyash & Danny
Lyrics & Composition - Avvy Ballagan

Song Lyrics
-------------------
“Kis Tariyon Batau Jazbaat Baawli
Saara Din Kare Jau Teri Baat Baawli
Hor mannai baakiyan ki lod koye na
Bas to thaam rakhiye ri haath baawli”

Koisa Karagi Jaadu Tona Meri Aakhyaan Ne
Jee Kawa Din Saara Sunu Teri Baatyaan ne

Streaming Links:
Spotify: https://open.spotify.com/album/3zv9ywMo9fxImAiXEqbnjr
            """
        }
        track = YouTubeDescriptionLyricsClient.fetch_from_info(sample_info, "Baawli", "Suyash")
        self.assertIsNotNone(track)
        self.assertEqual(track.source, "YouTube Description")
        self.assertTrue(len(track.lines) >= 6)
        self.assertEqual(track.lines[0].original_text, "Kis Tariyon Batau Jazbaat Baawli")
        self.assertTrue(track.is_synced)

    def test_word_cadence_interpolation(self):
        line = LyricsLine(time_sec=10.0, original_text="Kis Tariyon Batau Jazbaat Baawli")
        words = line.build_words(next_time_sec=15.0)
        self.assertEqual(len(words), 5)
        self.assertEqual(words[0].text, "Kis")
        self.assertEqual(words[-1].text, "Baawli")
        self.assertAlmostEqual(words[0].start_sec, 10.0)
        self.assertAlmostEqual(words[-1].end_sec, 15.0)

    def test_spotify_client_methods(self):
        self.assertTrue(hasattr(SpotifyLyricsClient, "get_access_token"))
        self.assertTrue(hasattr(SpotifyLyricsClient, "fetch_lyrics"))

if __name__ == '__main__':
    unittest.main()
