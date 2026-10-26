from __future__ import annotations

import unittest

from app.embedding import blob_to_vector, vector_to_blob
from app.query import clip_query
from app.services.add import _is_feedback, _split_long
from app.text import cjk_bigrams, fts_query, trigram_query


class SplitLongTest(unittest.TestCase):
    def test_short_content_is_not_split(self) -> None:
        self.assertEqual(_split_long("hello world"), ["hello world"])

    def test_single_paragraph_over_threshold_is_split(self) -> None:
        content = "x" * 5000
        pieces = _split_long(content)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= 3000 for piece in pieces))

    def test_long_paragraph_with_sentences_is_wrapped(self) -> None:
        sentence = "This is a reasonably long sentence about the project. "
        content = "Header line\n\n" + sentence * 400
        pieces = _split_long(content)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= 3000 for piece in pieces))
        self.assertTrue(all(piece.startswith("Header line") for piece in pieces))

    def test_paragraphs_split_and_share_header(self) -> None:
        first = "Document title: Example"
        body = "\n\n".join(f"paragraph {index} " + "y" * 400 for index in range(12))
        content = f"{first}\n\n{body}"
        pieces = _split_long(content)
        self.assertGreater(len(pieces), 1)
        for piece in pieces:
            self.assertLessEqual(len(piece), 3000)
        self.assertTrue(all(piece.startswith(first) for piece in pieces))

    def test_empty_content_round_trips(self) -> None:
        self.assertEqual(_split_long(""), [""])


class FeedbackDetectionTest(unittest.TestCase):
    def test_prefix_is_case_and_space_insensitive(self) -> None:
        self.assertTrue(_is_feedback("  STREAMING ONLINE QA FEEDBACK: {\"x\": 1}"))
        self.assertTrue(_is_feedback("Streaming online QA feedback:\n{}"))

    def test_other_streaming_messages_are_not_feedback(self) -> None:
        self.assertFalse(
            _is_feedback('Streaming intra-transfer train trajectory: {"task_index": 1}')
        )
        self.assertFalse(_is_feedback("Streaming model update notes"))


class QueryInjectionTest(unittest.TestCase):
    def test_quotes_never_reach_fts_query_bare(self) -> None:
        for text in ['ab"cd', 'he said "hello world"', 'a (b) c', "foo*bar", "a:b"]:
            query = fts_query(text)
            self.assertEqual(query.count('"') % 2, 0, text)
            self.assertNotIn("*", query)
            self.assertNotIn(":", query)

    def test_trigram_query_drops_quotes_and_parens(self) -> None:
        query = trigram_query('say "hello" (world)')
        self.assertNotIn("(", query)
        self.assertNotIn(")", query)
        self.assertEqual(query.count('"') % 2, 0)
        self.assertEqual(query.count('"'), 6)
        self.assertIn('"say"', query)
        self.assertIn('"hello"', query)
        self.assertIn('"world"', query)

    def test_empty_query_yields_empty_match(self) -> None:
        self.assertEqual(fts_query("   "), "")
        self.assertEqual(trigram_query("   "), "")

    def test_stopwords_are_dropped(self) -> None:
        self.assertEqual(fts_query("the of and"), "")


class CjkTest(unittest.TestCase):
    def test_bigrams_cover_runs(self) -> None:
        self.assertEqual(cjk_bigrams("患者复查"), ["患者", "者复", "复查"])
        self.assertEqual(cjk_bigrams("单"), ["单"])

    def test_mixed_text_bigrams_only_cjk(self) -> None:
        self.assertEqual(cjk_bigrams("INR复查x"), ["复查"])


class ClipQueryTest(unittest.TestCase):
    def test_never_exceeds_limit(self) -> None:
        query = "\n\n".join(f"line {index} " + "z" * 500 for index in range(60))
        clipped = clip_query(query, 12000)
        self.assertLessEqual(len(clipped), 12000)

    def test_short_query_is_untouched(self) -> None:
        self.assertEqual(clip_query("short query", 12000), "short query")


class VectorRoundTripTest(unittest.TestCase):
    def test_blob_round_trip_is_exact_for_float32(self) -> None:
        vector = [0.5, -0.25, 0.125, 1.0]
        restored = blob_to_vector(vector_to_blob(vector), 4)
        self.assertEqual(restored, vector)

    def test_bad_dimension_raises(self) -> None:
        with self.assertRaises(ValueError):
            blob_to_vector(b"\x00" * 8, 3)
        with self.assertRaises(ValueError):
            vector_to_blob([])


class RerankParseTest(unittest.TestCase):
    def test_duplicate_index_is_rejected(self) -> None:
        from app.rerank import RerankClient

        with self.assertRaises(ValueError):
            RerankClient._parse(
                {"results": [{"index": 0, "score": 1.0}, {"index": 0, "score": 2.0}]}, 2
            )

    def test_scores_map_by_index(self) -> None:
        from app.rerank import RerankClient

        self.assertEqual(
            RerankClient._parse(
                {"results": [{"index": 1, "score": 0.5}, {"index": 0, "score": 0.9}]}, 2
            ),
            [0.9, 0.5],
        )

    def test_missing_index_leaves_zero_but_length_guard_catches(self) -> None:
        from app.rerank import RerankClient

        with self.assertRaises(ValueError):
            RerankClient._parse({"results": [{"index": 0, "score": 1.0}]}, 2)


class MigrationTest(unittest.TestCase):
    def test_migrate_is_idempotent(self) -> None:
        import tempfile
        from pathlib import Path

        from app.storage.database import Database, _SCHEMA_VERSION

        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / "t.sqlite3")
            self.assertEqual(database.migrate(), _SCHEMA_VERSION)
            self.assertEqual(database.migrate(), _SCHEMA_VERSION)
            tables = {
                row[0]
                for row in database.connection().execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertTrue({"messages", "message_vectors", "embedding_cache", "rerank_cache"} <= tables)
            database.close()


class HardWrapTest(unittest.TestCase):
    def test_long_word_is_cut_to_limit(self) -> None:
        from app.services.add import _hard_wrap

        pieces = _hard_wrap("a" * 5000, 1200)
        self.assertEqual(max(len(piece) for piece in pieces), 1200)
        self.assertEqual(sum(len(piece) for piece in pieces), 5000)

    def test_cjk_without_spaces_is_cut(self) -> None:
        from app.services.add import _hard_wrap

        pieces = _hard_wrap("汉字" * 3000, 1200)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(piece) <= 1200 for piece in pieces))

    def test_sentences_are_kept_whole_when_possible(self) -> None:
        from app.services.add import _hard_wrap

        pieces = _hard_wrap("This is a sentence. " * 300, 1200)
        self.assertTrue(all(len(piece) <= 1200 for piece in pieces))
        self.assertTrue(all(piece.endswith(".") for piece in pieces))

    def test_empty_text_is_returned_as_is(self) -> None:
        from app.services.add import _hard_wrap

        self.assertEqual(_hard_wrap("", 1200), [""])


if __name__ == "__main__":
    unittest.main()
