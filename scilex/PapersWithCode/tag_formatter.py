#!/usr/bin/env python3
"""Format Papers with Code metadata into Zotero-compatible tags.

Tag prefixes (compatible with existing PWC tags):
- TASK: - Task type (e.g., TASK:TextClassification)
- PTM: - Pre-trained model (e.g., PTM:BERT)
- ARCHI: - Architecture (e.g., ARCHI:Transformer)
- DATASET: - Training dataset (e.g., DATASET:SQuAD)
- FRAMEWORK: - ML framework (e.g., FRAMEWORK:PyTorch)
- GITHUB_STARS: - GitHub star count (e.g., GITHUB_STARS:366)
- CITED_BY_DATASET: - Dataset that cites the paper (e.g., CITED_BY_DATASET:Glue)
- (no prefix) - AI-extracted keywords from paper
"""

import re

from scilex.constants import is_valid


class TagFormatter:
    """Format Papers with Code metadata into structured Zotero tags.

    Attributes:
        tag_prefixes: Dictionary of tag prefix constants
    """

    # Tag prefix constants (matches PWC format)
    TAG_TASK = "TASK:"
    TAG_PTM = "PTM:"
    TAG_ARCHI = "ARCHI:"
    TAG_DATASET = "DATASET:"
    TAG_FRAMEWORK = "FRAMEWORK:"
    TAG_GITHUB_STARS = "GITHUB_STARS:"
    TAG_CITED_BY_DATASET = "CITED_BY_DATASET:"

    # List of known pre-trained models (from getLPWC_collect.py)
    KNOWN_MODELS = [
        "BERT",
        "BART",
        "RoBERTA",
        "T5",
        "GPT",
        "GPT2",
        "GPT3",
        "GPT4",
        "ELECTRA",
        "ALBERT",
        "XLNET",
        "DISTILBERT",
        "SPANBERT",
        "SCIBERT",
        "PUBMEDBERT",
        "BIOBERT",
        "TRANSFORMERXL",
        "MT5",
        "DEBERTA",
        "GLM",
        "COMET",
        "MBART",
        "REBEL",
        "PEGASUS",
        "BERTSUM",
        "PURE",
        "CASREL",
        "FLAN",
        "LLAMA",
        "VICUNA",
        "ALPACA",
        "LUKE",
        "CLIP",
        "XLM",
        "KBERT",
        "KEPLER",
        "FLAIR",
        "LONGFORMER",
    ]

    def __init__(self):
        """Initialize tag formatter."""
        self.tag_prefixes = [
            self.TAG_TASK,
            self.TAG_PTM,
            self.TAG_ARCHI,
            self.TAG_DATASET,
            self.TAG_FRAMEWORK,
            self.TAG_GITHUB_STARS,
            self.TAG_CITED_BY_DATASET,
        ]

    @staticmethod
    def normalize_tag_value(value: str) -> str:
        """Normalize tag value to consistent format.

        Rules:
        - Remove all spaces
        - Convert to PascalCase (capitalize each word)
        - Remove special characters except hyphens

        Examples:
            >>> TagFormatter.normalize_tag_value("text classification")
            "TextClassification"

            >>> TagFormatter.normalize_tag_value("squad-v2")
            "SquadV2"

        Args:
            value: Raw value string

        Returns:
            Normalized value (PascalCase, no spaces)
        """
        if not is_valid(value):
            return ""

        # Remove special chars except hyphens and spaces
        value = re.sub(r"[^\w\s-]", "", value)

        # Split on spaces and hyphens, capitalize each word
        words = re.split(r"[\s-]+", value)
        normalized = "".join(word.capitalize() for word in words if word)

        return normalized

    def format_task_tag(self, task: str | None) -> str | None:
        """Format task into Zotero tag.

        Args:
            task: Task name (e.g., "TextClassification")

        Returns:
            Formatted tag (e.g., "TASK:TextClassification") or None
        """
        if not is_valid(task):
            return None

        normalized = self.normalize_tag_value(task)
        return f"{self.TAG_TASK}{normalized}"

    def format_architecture_tag(self, architecture: str | None) -> str | None:
        """Format architecture into Zotero tag.

        Decides whether to use PTM: or ARCHI: prefix based on value.

        Logic:
        - If architecture is in KNOWN_MODELS list → PTM: prefix
        - Otherwise → ARCHI: prefix

        Args:
            architecture: Architecture name (e.g., "BERT", "Transformer")

        Returns:
            Formatted tag (e.g., "PTM:BERT" or "ARCHI:Transformer")
        """
        if not is_valid(architecture):
            return None

        normalized = self.normalize_tag_value(architecture)

        # Check if it's a known pre-trained model
        if normalized.upper() in [m.upper() for m in self.KNOWN_MODELS]:
            return f"{self.TAG_PTM}{normalized}"
        else:
            return f"{self.TAG_ARCHI}{normalized}"

    def format_dataset_tags(self, datasets: list[str]) -> list[str]:
        """Format dataset names into Zotero tags.

        Args:
            datasets: List of dataset names (e.g., ["squad", "glue"])

        Returns:
            List of formatted tags (e.g., ["DATASET:Squad", "DATASET:Glue"])
        """
        tags = []
        for dataset in datasets:
            if is_valid(dataset):
                normalized = self.normalize_tag_value(dataset)
                tags.append(f"{self.TAG_DATASET}{normalized}")
        return tags

    def format_framework_tag(self, framework: str | None) -> str | None:
        """Format framework into Zotero tag.

        Args:
            framework: Framework name (e.g., "PyTorch")

        Returns:
            Formatted tag (e.g., "FRAMEWORK:PyTorch")
        """
        if not is_valid(framework):
            return None

        normalized = self.normalize_tag_value(framework)
        return f"{self.TAG_FRAMEWORK}{normalized}"

    def format_github_stars_tag(self, stars: int | None) -> str | None:
        """Format GitHub stars count into Zotero tag.

        Args:
            stars: GitHub star count (e.g., 366)

        Returns:
            Formatted tag (e.g., "GITHUB_STARS:366")
        """
        if stars is None or stars < 0:
            return None

        return f"{self.TAG_GITHUB_STARS}{stars}"

    def format_citing_dataset_tags(self, datasets: list[str]) -> list[str]:
        """Format citing dataset names into Zotero tags.

        These are datasets that CITE the paper, not datasets used by the paper.

        Args:
            datasets: List of dataset names that cite the paper

        Returns:
            List of formatted tags (e.g., ["CITED_BY_DATASET:Glue"])
        """
        tags = []
        for dataset in datasets:
            if is_valid(dataset):
                normalized = self.normalize_tag_value(dataset)
                tags.append(f"{self.TAG_CITED_BY_DATASET}{normalized}")
        return tags

    def format_ai_keywords_tags(self, keywords: list[str]) -> list[str]:
        """Format AI-extracted keywords into Zotero tags (no prefix).

        These are keywords extracted by AI from the paper content.

        Args:
            keywords: List of AI-extracted keywords

        Returns:
            List of tags (no prefix, as-is)
        """
        tags = []
        for keyword in keywords:
            if is_valid(keyword):
                # Keep original case and format for readability
                tags.append(keyword.strip())
        return tags

    def format_all_tags(self, metadata: dict) -> list[str]:
        """Format all metadata into list of Zotero tags.

        Args:
            metadata: Extracted metadata from MetadataExtractor or paper info
                Expected keys:
                - pipeline_tag: Task type (e.g., "TextClassification")
                - architecture: Model architecture (e.g., "BERT")
                - datasets: List of dataset names
                - framework: ML framework (e.g., "PyTorch")
                - github_stars: GitHub star count (int)
                - citing_datasets: List of datasets that cite the paper
                - ai_keywords: List of AI-extracted keywords

        Returns:
            List of formatted tags:
            [
                "TASK:TextClassification",
                "PTM:BERT",
                "DATASET:Squad",
                "FRAMEWORK:PyTorch",
                "GITHUB_STARS:366",
                "CITED_BY_DATASET:Glue",
                "multi-document question answering"
            ]
        """
        tags = []

        # Task
        if task_tag := self.format_task_tag(metadata.get("pipeline_tag")):
            tags.append(task_tag)

        # Architecture (PTM or ARCHI)
        if arch_tag := self.format_architecture_tag(metadata.get("architecture")):
            tags.append(arch_tag)

        # Datasets (multiple)
        tags.extend(self.format_dataset_tags(metadata.get("datasets", [])))

        # Framework
        if fw_tag := self.format_framework_tag(metadata.get("framework")):
            tags.append(fw_tag)

        # GitHub Stars (from paper info)
        if stars_tag := self.format_github_stars_tag(metadata.get("github_stars")):
            tags.append(stars_tag)

        # Citing Datasets (datasets that cite this paper)
        tags.extend(
            self.format_citing_dataset_tags(metadata.get("citing_datasets", []))
        )

        # AI Keywords (no prefix, as-is)
        tags.extend(self.format_ai_keywords_tags(metadata.get("ai_keywords", [])))

        return tags
