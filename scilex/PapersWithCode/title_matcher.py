#!/usr/bin/env python3
"""Title matching for academic papers using exact and fuzzy algorithms.

Handles:
- Exact string matching (case-insensitive)
- Fuzzy matching with configurable threshold
- Title normalization (remove punctuation, LaTeX, etc.)
- Multiple match disambiguation
"""

import re
import unicodedata

from rapidfuzz import fuzz, process

from scilex.constants import is_valid


class TitleMatcher:
    """Match paper titles to candidate titles using fuzzy matching.

    Attributes:
        threshold: Minimum similarity score (0-100) for fuzzy matches
        scorer: Fuzzy matching algorithm (default: fuzz.token_sort_ratio)
    """

    def __init__(self, threshold: int = 85):
        """Initialize title matcher.

        Args:
            threshold: Minimum fuzzy match score (0-100). Default: 85
                      - 90+: Very strict (exact match required)
                      - 85: Recommended (tolerates minor differences)
                      - 75: Lenient (may include false positives)
        """
        self.threshold = threshold
        self.scorer = fuzz.token_sort_ratio  # Best for academic titles

    @staticmethod
    def normalize_title(title: str) -> str:
        """Normalize academic paper title for matching.

        Handles:
        - Lowercase conversion
        - Unicode normalization (accents, special chars)
        - LaTeX command removal ($, \\textbf{}, etc.)
        - Punctuation removal (keep hyphens, keep spaces)
        - Extra whitespace collapse

        Examples:
            >>> TitleMatcher.normalize_title("BERT: Pre-training of Deep Bidirectional")
            "bert pre-training of deep bidirectional"

            >>> TitleMatcher.normalize_title("GPT-3: Language Models are Few-Shot Learners")
            "gpt-3 language models are few-shot learners"

        Args:
            title: Original paper title

        Returns:
            Normalized title (lowercase, no punctuation except hyphens)
        """
        if not is_valid(title):
            return ""

        # Remove LaTeX math mode
        title = re.sub(r"\$.*?\$", "", title)

        # Remove LaTeX commands like \textbf{}, \alpha
        title = re.sub(r"\\[a-zA-Z]+\{.*?\}", "", title)
        title = re.sub(r"\\[a-zA-Z]+", "", title)

        # Normalize unicode (accents → base chars)
        title = unicodedata.normalize("NFKD", title)
        title = title.encode("ascii", "ignore").decode("utf-8")

        # Lowercase
        title = title.lower()

        # Remove punctuation (keep hyphens and spaces)
        title = re.sub(r"[^\w\s-]", " ", title)

        # Collapse whitespace
        title = re.sub(r"\s+", " ", title).strip()

        return title

    def find_best_match(
        self, paper_title: str, candidates: list[dict], key: str = "title"
    ) -> tuple[dict | None, int]:
        """Find best matching candidate for paper title.

        Args:
            paper_title: Academic paper title
            candidates: Candidate dictionaries (e.g. search results)
            key: Dictionary key holding the candidate title (default: "title")

        Returns:
            Tuple of (best_match_dict, confidence_score)
            - best_match_dict: Full dictionary of best match, or None
            - confidence_score: 0-100 (0 if no match above threshold)

        Example:
            >>> matcher = TitleMatcher(threshold=85)
            >>> papers = [{"title": "Attention Is All You Need"}, {"title": "BERT"}]
            >>> match, score = matcher.find_best_match("Attention is all you need", papers)
            >>> match["title"], score
            ('Attention Is All You Need', 100)
        """
        if not candidates:
            return None, 0

        # Normalize paper title
        normalized_title = self.normalize_title(paper_title)

        # Extract candidate names and normalize
        candidate_names = [c.get(key, "") for c in candidates]
        normalized_candidates = [self.normalize_title(name) for name in candidate_names]

        # Use rapidfuzz.process.extractOne for best match
        result = process.extractOne(
            normalized_title, normalized_candidates, scorer=self.scorer
        )

        if result is None:
            return None, 0

        best_match_text, score, best_idx = result

        if score < self.threshold:
            return None, 0

        return candidates[best_idx], int(score)
