"""Tests for pure functions in scilex.abstract_validation module."""

import pandas as pd
import pytest

from scilex.abstract_validation import (
    AbstractQualityIssue,
    AbstractQualityScore,
    detect_boilerplate,
    detect_formatting_issues,
    detect_language_issues,
    detect_length_issues,
    detect_truncation,
    normalize_abstract,
    validate_abstract_quality,
    validate_dataframe_abstracts,
)


# -------------------------------------------------------------------------
# AbstractQualityScore
# -------------------------------------------------------------------------
class TestAbstractQualityScore:
    def test_initial_score_is_100(self):
        qs = AbstractQualityScore("some text")
        assert qs.get_score() == 100

    def test_critical_deducts_40(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("X", AbstractQualityIssue.CRITICAL, "desc"))
        assert qs.get_score() == 60

    def test_warning_deducts_15(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("X", AbstractQualityIssue.WARNING, "desc"))
        assert qs.get_score() == 85

    def test_info_deducts_5(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("X", AbstractQualityIssue.INFO, "desc"))
        assert qs.get_score() == 95

    def test_score_floor_at_zero(self):
        qs = AbstractQualityScore("text")
        for _ in range(5):
            qs.add_issue(
                AbstractQualityIssue("X", AbstractQualityIssue.CRITICAL, "desc")
            )
        assert qs.get_score() == 0

    def test_multiple_issues_accumulate(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("A", AbstractQualityIssue.WARNING, "w1"))
        qs.add_issue(AbstractQualityIssue("B", AbstractQualityIssue.INFO, "i1"))
        assert qs.get_score() == 100 - 15 - 5

    def test_has_critical_issues_false_when_none(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("X", AbstractQualityIssue.WARNING, "desc"))
        assert qs.has_critical_issues() is False

    def test_has_critical_issues_true(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("X", AbstractQualityIssue.CRITICAL, "desc"))
        assert qs.has_critical_issues() is True

    def test_is_acceptable_no_issues(self):
        qs = AbstractQualityScore("text")
        assert qs.is_acceptable() is True

    def test_is_acceptable_fails_with_critical(self):
        qs = AbstractQualityScore("text")
        qs.add_issue(AbstractQualityIssue("X", AbstractQualityIssue.CRITICAL, "desc"))
        assert qs.is_acceptable() is False

    def test_is_acceptable_fails_below_threshold(self):
        qs = AbstractQualityScore("text")
        for _ in range(3):
            qs.add_issue(
                AbstractQualityIssue("X", AbstractQualityIssue.WARNING, "desc")
            )
        # 100 - 3*15 = 55, which is >= 50 by default
        assert qs.is_acceptable() is True

    def test_is_acceptable_custom_threshold(self):
        qs = AbstractQualityScore("text")
        for _ in range(3):
            qs.add_issue(
                AbstractQualityIssue("X", AbstractQualityIssue.WARNING, "desc")
            )
        # 55 < 70
        assert qs.is_acceptable(min_score=70) is False


# -------------------------------------------------------------------------
# normalize_abstract
# -------------------------------------------------------------------------
class TestNormalizeAbstract:
    def test_plain_string_returned(self):
        assert normalize_abstract("Hello world") == "Hello world"

    def test_dict_with_p_key_joined(self):
        result = normalize_abstract({"p": ["First sentence.", "Second sentence."]})
        assert result == "First sentence. Second sentence."

    def test_whitespace_collapsed(self):
        result = normalize_abstract("too   many   spaces")
        assert result == "too many spaces"

    def test_none_returns_empty(self):
        assert normalize_abstract(None) == ""

    def test_na_string_returns_empty(self):
        assert normalize_abstract("NA") == ""

    def test_empty_string_returns_empty(self):
        assert normalize_abstract("") == ""

    def test_strips_leading_trailing_whitespace(self):
        assert normalize_abstract("  hello  ") == "hello"


# -------------------------------------------------------------------------
# detect_truncation
# -------------------------------------------------------------------------
class TestDetectTruncation:
    def test_ellipsis_is_critical(self):
        issue = detect_truncation("This paper presents a method...")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.CRITICAL

    def test_more_tag_is_critical(self):
        issue = detect_truncation("This paper presents results[more]")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.CRITICAL

    def test_continued_is_critical(self):
        issue = detect_truncation("The results are shown[continued]")
        assert issue is not None

    def test_et_al_at_end_is_critical(self):
        issue = detect_truncation("We used the method by Smith et al")
        assert issue is not None

    def test_truncated_tag_is_critical(self):
        issue = detect_truncation("[truncated] This is the abstract.")
        assert issue is not None

    def test_ends_with_comma_is_warning(self):
        issue = detect_truncation("The results show accuracy,")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.WARNING

    def test_ends_with_conjunction_is_warning(self):
        issue = detect_truncation("The method works and")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.WARNING

    def test_good_abstract_returns_none(self):
        issue = detect_truncation(
            "This paper presents a novel method for knowledge graph completion. "
            "We evaluate on standard benchmarks and achieve state-of-the-art results."
        )
        assert issue is None

    def test_empty_abstract_returns_none(self):
        assert detect_truncation("") is None

    def test_na_returns_none(self):
        assert detect_truncation("NA") is None


# -------------------------------------------------------------------------
# detect_boilerplate
# -------------------------------------------------------------------------
class TestDetectBoilerplate:
    def test_this_paper_presents_detected(self):
        issue = detect_boilerplate("This paper presents a new approach.")
        assert issue is not None
        assert issue.issue_type == "BOILERPLATE"
        assert issue.severity == AbstractQualityIssue.WARNING

    def test_no_abstract_available(self):
        issue = detect_boilerplate("No abstract available")
        assert issue is not None

    def test_abstract_word_alone(self):
        issue = detect_boilerplate("Abstract:")
        assert issue is not None

    def test_copyright_notice(self):
        issue = detect_boilerplate("Copyright 2024 Authors. All rights reserved.")
        assert issue is not None

    def test_good_abstract_returns_none(self):
        issue = detect_boilerplate(
            "We propose a graph neural network that achieves 94% accuracy "
            "on link prediction tasks across multiple datasets."
        )
        assert issue is None

    def test_empty_abstract_returns_none(self):
        assert detect_boilerplate("") is None


# -------------------------------------------------------------------------
# detect_length_issues
# -------------------------------------------------------------------------
class TestDetectLengthIssues:
    def _make_abstract(self, n_words: int) -> str:
        return " ".join(["word"] * n_words)

    def test_missing_abstract_is_critical(self):
        issue = detect_length_issues("NA")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.CRITICAL
        assert issue.issue_type == "MISSING"

    def test_empty_abstract_is_critical(self):
        issue = detect_length_issues("")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.CRITICAL

    def test_too_short_is_warning(self):
        issue = detect_length_issues(self._make_abstract(10), min_words=30)
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.WARNING
        assert issue.issue_type == "TOO_SHORT"

    def test_too_long_is_warning(self):
        issue = detect_length_issues(self._make_abstract(1500), max_words=1000)
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.WARNING
        assert issue.issue_type == "TOO_LONG"

    def test_good_length_returns_none(self):
        issue = detect_length_issues(self._make_abstract(100))
        assert issue is None

    def test_max_words_zero_disables_upper_limit(self):
        issue = detect_length_issues(self._make_abstract(5000), max_words=0)
        # Should not flag TOO_LONG when max_words=0
        # But might flag TOO_SHORT since default min_words=30
        if issue is not None:
            assert issue.issue_type != "TOO_LONG"


# -------------------------------------------------------------------------
# detect_language_issues
# -------------------------------------------------------------------------
class TestDetectLanguageIssues:
    def test_english_text_passes(self):
        text = (
            "This paper presents a novel approach to knowledge graph completion "
            "using deep learning. We evaluate the method on standard benchmarks."
        )
        issue = detect_language_issues(text)
        assert issue is None

    def test_short_text_skipped(self):
        # Less than 10 words — should not flag
        issue = detect_language_issues("Bonjour le monde voici une phrase.")
        assert issue is None

    def test_non_english_detected(self):
        # Pure French — will have very low ratio of English common words
        french = (
            "Ce papier présente une nouvelle approche pour compléter les graphes "
            "de connaissances utilisant l'apprentissage profond. "
            "Nous évaluons la méthode sur des benchmarks standards."
        )
        issue = detect_language_issues(french)
        assert issue is not None
        assert issue.issue_type == "LANGUAGE"
        assert issue.severity == AbstractQualityIssue.INFO

    def test_non_english_expected_language_skipped(self):
        # If expected_language != "english", skip
        french = (
            "Ce papier présente une nouvelle approche pour compléter les graphes "
            "de connaissances utilisant l'apprentissage profond."
        )
        issue = detect_language_issues(french, expected_language="french")
        assert issue is None


# -------------------------------------------------------------------------
# detect_formatting_issues
# -------------------------------------------------------------------------
class TestDetectFormattingIssues:
    def test_html_tags_detected(self):
        issue = detect_formatting_issues("This is a <b>paper</b> about graphs.")
        assert issue is not None
        assert issue.issue_type == "FORMATTING"
        assert issue.severity == AbstractQualityIssue.WARNING

    def test_xml_tags_detected(self):
        issue = detect_formatting_issues("We use <jats:p>XML</jats:p> formatting.")
        assert issue is not None

    def test_excessive_special_chars_detected(self):
        # Insert many special chars (>5% of text)
        text = "normal text " + "§¶†‡" * 20 + " more text"
        issue = detect_formatting_issues(text)
        assert issue is not None

    def test_repeated_chars_detected(self):
        issue = detect_formatting_issues("This paper aaaaaaaa presents results.")
        assert issue is not None
        assert issue.severity == AbstractQualityIssue.INFO

    def test_clean_text_returns_none(self):
        issue = detect_formatting_issues(
            "We propose a novel graph neural network architecture. "
            "Experiments on standard benchmarks show state-of-the-art results."
        )
        assert issue is None

    def test_empty_returns_none(self):
        assert detect_formatting_issues("") is None


# -------------------------------------------------------------------------
# validate_abstract_quality
# -------------------------------------------------------------------------
class TestValidateAbstractQuality:
    def test_good_abstract_score_100(self):
        text = (
            "We propose a novel graph neural network architecture for knowledge "
            "graph completion. We evaluate on FB15k-237 and WN18RR benchmarks. "
            "Our method achieves state-of-the-art results on link prediction tasks. "
            "The approach combines transformer attention with graph convolutions "
            "and shows improvements over all baseline methods."
        )
        quality = validate_abstract_quality(text)
        assert quality.get_score() == 100
        assert quality.is_acceptable()

    def test_missing_abstract_critical(self):
        quality = validate_abstract_quality("NA")
        assert quality.has_critical_issues()
        assert not quality.is_acceptable()

    def test_truncated_abstract_critical(self):
        quality = validate_abstract_quality("The method is applied...")
        assert quality.has_critical_issues()

    def test_short_abstract_warning(self):
        quality = validate_abstract_quality("A short abstract.")
        # TOO_SHORT is WARNING, so score drops to 85
        assert quality.get_score() == 85

    def test_check_language_false_skips_language(self):
        # Using check_language=False means language check is skipped
        text = (
            "Ce papier présente une nouvelle approche pour compléter les graphes "
            "de connaissances utilisant l'apprentissage profond sur des benchmarks."
        )
        quality = validate_abstract_quality(text, check_language=False)
        # May still have other issues (length), but no LANGUAGE issue
        lang_issues = [i for i in quality.issues if i.issue_type == "LANGUAGE"]
        assert len(lang_issues) == 0

    def test_expected_language_fr_no_mismatch(self):
        # French abstract with expected_language="fr" must not raise a LANGUAGE issue
        french = (
            "Ce papier présente une nouvelle approche pour compléter les graphes "
            "de connaissances en utilisant l'apprentissage profond. "
            "Nous évaluons la méthode sur des benchmarks standards et obtenons "
            "des résultats à l'état de l'art sur la prédiction de liens."
        )
        quality = validate_abstract_quality(french, expected_language="fr")
        lang_issues = [i for i in quality.issues if i.issue_type == "LANGUAGE"]
        assert len(lang_issues) == 0


# -------------------------------------------------------------------------
# validate_dataframe_abstracts
# -------------------------------------------------------------------------
class TestValidateDataframeAbstracts:
    def _make_df(self, abstracts: list) -> pd.DataFrame:
        return pd.DataFrame({"abstract": abstracts, "title": ["T"] * len(abstracts)})

    def test_adds_quality_columns(self):
        df = self._make_df(["NA", "This is a short abstract."])
        df_result, stats = validate_dataframe_abstracts(df)
        assert "abstract_quality_score" in df_result.columns
        assert "abstract_quality_issues" in df_result.columns

    def test_missing_column_returns_unchanged(self):
        df = pd.DataFrame({"title": ["T1"]})
        df_result, stats = validate_dataframe_abstracts(df, abstract_column="abstract")
        assert stats == {}
        assert "abstract_quality_score" not in df_result.columns

    def test_empty_df_returns_unchanged(self):
        df = pd.DataFrame({"abstract": []})
        df_result, stats = validate_dataframe_abstracts(df)
        assert stats == {}

    def test_stats_total_count(self):
        df = self._make_df(["NA", "NA", "A good abstract with enough words here " * 3])
        _, stats = validate_dataframe_abstracts(df)
        assert stats["total"] == 3

    def test_stats_truncated_counted(self):
        df = self._make_df(["This is truncated..."])
        _, stats = validate_dataframe_abstracts(df)
        assert stats["truncated"] == 1

    def test_stats_average_score_computed(self):
        df = self._make_df(["NA"])
        _, stats = validate_dataframe_abstracts(df)
        assert "average_score" in stats
        # "NA" normalizes to "" → MISSING (CRITICAL, -40) → score = 60
        assert stats["average_score"] == pytest.approx(60.0)
