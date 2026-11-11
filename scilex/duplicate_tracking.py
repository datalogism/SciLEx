"""Duplicate source tracking and API overlap analysis for SciLEx.

This module analyzes:
- Which APIs found which papers
- Overlap between API pairs
- Which APIs provide unique papers
- API quality metrics (metadata completeness)
- Recommendations for optimizing API selection
"""

import logging
from collections import defaultdict

import pandas as pd

from scilex.constants import MISSING_VALUE, is_missing, is_valid, parse_archive_apis


class DuplicateSourceAnalyzer:
    """Analyzes duplicate sources and API overlap."""

    def __init__(self):
        # Track papers by API
        self.papers_by_api: dict[str, set[str]] = defaultdict(set)

        # Track papers found by multiple APIs (DOI or title as key)
        self.duplicate_papers: dict[str, list[str]] = defaultdict(list)

        # Track unique papers per API
        self.unique_papers_by_api: dict[str, set[str]] = defaultdict(set)

        # Statistics
        self.total_papers = 0
        self.total_unique_papers = 0
        self.apis_encountered = set()

    def add_paper(self, paper_id: str, api_source: str):
        """Record that a paper was found by an API.

        Args:
            paper_id: Unique identifier (DOI or normalized title)
            api_source: Name of API that found this paper
        """
        self.papers_by_api[api_source].add(paper_id)
        self.duplicate_papers[paper_id].append(api_source)
        self.apis_encountered.add(api_source)

    def analyze_from_dataframe(self, df: pd.DataFrame, archive_column: str = "archive"):
        """Analyze duplicate sources from aggregated DataFrame.

        The archive column should contain API sources, possibly semicolon-separated
        (e.g., "SemanticScholar;IEEE*" where * indicates the chosen source).

        Args:
            df: DataFrame with aggregated papers
            archive_column: Column containing API source information
        """
        self.total_papers = len(df)

        for idx, row in df.iterrows():
            archive = row.get(archive_column, "")

            if is_missing(archive):
                continue

            # Parse archive field (may be "API1;API2;API3*")
            apis = parse_archive_apis(archive)

            # Get paper identifier (prefer DOI, fall back to title)
            paper_id = row.get("DOI")
            if is_missing(paper_id):
                paper_id = row.get("title", f"unknown_{idx}")

            # Record this paper for each API that found it
            for api in apis:
                if api:
                    self.add_paper(str(paper_id), api)

        # Calculate unique papers per API
        self._calculate_unique_papers()

        # Total unique papers is the union of all papers
        all_papers = set()
        for papers in self.papers_by_api.values():
            all_papers.update(papers)
        self.total_unique_papers = len(all_papers)

    def _calculate_unique_papers(self):
        """Calculate which papers are unique to each API."""
        # Find papers found by only one API
        for paper_id, apis in self.duplicate_papers.items():
            if len(apis) == 1:
                api = apis[0]
                self.unique_papers_by_api[api].add(paper_id)

    def get_api_overlap(self, api1: str, api2: str) -> tuple[int, float]:
        """Calculate overlap between two APIs.

        Args:
            api1: First API name
            api2: Second API name

        Returns:
            (overlap_count, overlap_percentage): Number of shared papers and
                                                  percentage relative to smaller API
        """
        papers1 = self.papers_by_api.get(api1, set())
        papers2 = self.papers_by_api.get(api2, set())

        if not papers1 or not papers2:
            return 0, 0.0

        overlap = papers1.intersection(papers2)
        overlap_count = len(overlap)

        # Calculate percentage relative to smaller API
        smaller_count = min(len(papers1), len(papers2))
        overlap_percentage = (
            (overlap_count / smaller_count * 100) if smaller_count > 0 else 0.0
        )

        return overlap_count, overlap_percentage

    def get_all_overlaps(self) -> list[tuple[str, str, int, float]]:
        """Get all pairwise API overlaps.

        Returns:
            List of (api1, api2, overlap_count, overlap_percentage) tuples,
            sorted by overlap count (descending)
        """
        overlaps = []
        apis = sorted(self.apis_encountered)

        for i, api1 in enumerate(apis):
            for api2 in apis[i + 1 :]:
                count, percentage = self.get_api_overlap(api1, api2)
                if count > 0:
                    overlaps.append((api1, api2, count, percentage))

        # Sort by overlap count (descending)
        overlaps.sort(key=lambda x: x[2], reverse=True)

        return overlaps

    def get_api_statistics(self) -> dict[str, dict]:
        """Get detailed statistics for each API.

        Returns:
            Dictionary mapping API name to statistics
        """
        stats = {}

        for api in sorted(self.apis_encountered):
            total_papers = len(self.papers_by_api[api])
            unique_papers = len(self.unique_papers_by_api[api])
            duplicate_papers = total_papers - unique_papers

            unique_percentage = (
                (unique_papers / total_papers * 100) if total_papers > 0 else 0.0
            )
            coverage_percentage = (
                (unique_papers / self.total_unique_papers * 100)
                if self.total_unique_papers > 0
                else 0.0
            )

            stats[api] = {
                "total_papers": total_papers,
                "unique_papers": unique_papers,
                "duplicate_papers": duplicate_papers,
                "unique_percentage": unique_percentage,
                "coverage_percentage": coverage_percentage,
            }

        return stats

    def generate_report(self) -> str:
        """Generate duplicate source tracking report."""
        if not self.apis_encountered:
            return "No API source information available."

        report_lines = [
            "\n" + "=" * 70,
            "DUPLICATE SOURCE TRACKING REPORT",
            "=" * 70,
            f"Total papers in collection: {self.total_papers}",
            f"Total unique papers: {self.total_unique_papers}",
            f"APIs used: {len(self.apis_encountered)}",
            "",
            "=" * 70,
            "API STATISTICS",
            "=" * 70,
        ]

        # API statistics table
        stats = self.get_api_statistics()

        report_lines.append(
            f"{'API':<20} {'Total':>8} {'Unique':>8} {'Unique %':>10} {'Exclusive':>10}"
        )
        report_lines.append("-" * 70)

        for api in sorted(
            stats.keys(), key=lambda a: stats[a]["unique_papers"], reverse=True
        ):
            api_stats = stats[api]
            report_lines.append(
                f"{api:<20} {api_stats['total_papers']:>8} "
                f"{api_stats['unique_papers']:>8} "
                f"{api_stats['unique_percentage']:>9.1f}% "
                f"{api_stats['coverage_percentage']:>9.1f}%"
            )

        report_lines.extend(
            [
                "",
                "Legend:",
                "  Total: Number of papers found by this API",
                "  Unique: Papers found ONLY by this API",
                "  Unique %: Percentage of this API's papers that are unique",
                "  Exclusive: Percentage of all unique papers found ONLY by this API",
                "",
                "=" * 70,
                "API OVERLAP ANALYSIS",
                "=" * 70,
            ]
        )

        # Pairwise overlaps
        overlaps = self.get_all_overlaps()

        if overlaps:
            report_lines.append(f"{'API Pair':<40} {'Overlap':>10} {'Overlap %':>12}")
            report_lines.append("-" * 70)

            for api1, api2, count, percentage in overlaps[:10]:  # Show top 10
                pair_name = f"{api1} + {api2}"
                report_lines.append(f"{pair_name:<40} {count:>10} {percentage:>11.1f}%")

            if len(overlaps) > 10:
                report_lines.append(f"... and {len(overlaps) - 10} more pairs")
        else:
            report_lines.append(
                "No overlaps detected (each API found different papers)"
            )

        report_lines.extend(
            [
                "",
                "=" * 70,
                "RECOMMENDATIONS",
                "=" * 70,
            ]
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(stats, overlaps)
        report_lines.extend(recommendations)

        report_lines.append("=" * 70 + "\n")

        return "\n".join(report_lines)

    def _generate_recommendations(
        self, stats: dict[str, dict], overlaps: list[tuple[str, str, int, float]]
    ) -> list[str]:
        """Generate actionable recommendations based on analysis."""
        recommendations = []
        high_overlap_pairs = []  # Initialize to avoid UnboundLocalError

        # Find APIs with high unique content
        high_value_apis = [
            api
            for api, s in stats.items()
            if s["unique_papers"] > 10 and s["unique_percentage"] > 20
        ]

        if high_value_apis:
            recommendations.append("✓ High-value APIs (many unique papers):")
            for api in sorted(
                high_value_apis, key=lambda a: stats[a]["unique_papers"], reverse=True
            ):
                unique = stats[api]["unique_papers"]
                pct = stats[api]["unique_percentage"]
                recommendations.append(
                    f"  - {api}: {unique} unique papers ({pct:.1f}%)"
                )
            recommendations.append("")

        # Find APIs with high overlap (may be redundant)
        if overlaps:
            high_overlap_pairs = [
                (api1, api2, pct) for api1, api2, count, pct in overlaps if pct > 70
            ]

            if high_overlap_pairs:
                recommendations.append("⚠️  High-overlap API pairs (>70% overlap):")
                for api1, api2, pct in high_overlap_pairs[:5]:
                    recommendations.append(f"  - {api1} + {api2}: {pct:.1f}% overlap")
                recommendations.append(
                    "  Consider using only one from each pair to reduce costs."
                )
                recommendations.append("")

        # Find low-yield APIs
        low_yield_apis = [
            api
            for api, s in stats.items()
            if s["unique_papers"] < 5 and s["total_papers"] > 10
        ]

        if low_yield_apis:
            recommendations.append("⚠️  Low-yield APIs (few unique papers):")
            for api in low_yield_apis:
                unique = stats[api]["unique_papers"]
                total = stats[api]["total_papers"]
                recommendations.append(
                    f"  - {api}: Only {unique} unique out of {total} total papers"
                )
            recommendations.append(
                "  Consider dropping these APIs for future collections."
            )
            recommendations.append("")

        # Overall recommendation
        if not recommendations:
            recommendations.append(
                "✓ All APIs provide good value with reasonable overlap."
            )
        else:
            recommendations.append("Summary:")
            recommendations.append(
                f"  - Keep {len(high_value_apis)}/{len(stats)} APIs with high unique content"
            )
            if low_yield_apis:
                recommendations.append(
                    f"  - Consider dropping {len(low_yield_apis)} low-yield APIs"
                )
            if high_overlap_pairs:
                recommendations.append(
                    f"  - {len(high_overlap_pairs)} API pairs have high overlap - consolidate?"
                )

        return recommendations


def analyze_api_metadata_quality(df: pd.DataFrame) -> dict[str, dict]:
    """Analyze metadata completeness by API source.

    Args:
        df: DataFrame with papers and archive column

    Returns:
        Dictionary mapping API to metadata quality statistics
    """
    key_fields = [
        "DOI",
        "title",
        "authors",
        "date",
        "abstract",
        "journalAbbreviation",
        "itemType",
    ]

    api_quality = defaultdict(lambda: {field: 0 for field in key_fields})
    api_counts = defaultdict(int)

    for _, row in df.iterrows():
        archive = row.get("archive", "")

        if is_missing(archive):
            continue

        # Parse archive (primary API is marked with *)
        apis = parse_archive_apis(archive)
        primary_api = next(
            (api for api in apis if "*" in str(row.get("archive", "")) and api),
            apis[0] if apis else "Unknown",
        )

        # Count papers per API
        api_counts[primary_api] += 1

        # Count non-missing fields
        for field in key_fields:
            if is_valid(row.get(field)):
                api_quality[primary_api][field] += 1

    # Calculate percentages
    quality_stats = {}
    for api, counts in api_quality.items():
        total_papers = api_counts[api]
        quality_stats[api] = {
            "total_papers": total_papers,
            "field_completeness": {
                field: {
                    "count": count,
                    "percentage": (count / total_papers * 100)
                    if total_papers > 0
                    else 0.0,
                }
                for field, count in counts.items()
            },
        }

    return quality_stats


def generate_metadata_quality_report(quality_stats: dict[str, dict]) -> str:
    """Generate metadata quality report by API."""
    if not quality_stats:
        return "No metadata quality data available."

    report_lines = [
        "\n" + "=" * 70,
        "METADATA QUALITY BY API",
        "=" * 70,
    ]

    for api in sorted(quality_stats.keys()):
        stats = quality_stats[api]
        total = stats["total_papers"]

        report_lines.append(f"\n{api} ({total} papers):")
        report_lines.append("-" * 40)

        field_comp = stats["field_completeness"]
        for field in [
            "DOI",
            "title",
            "authors",
            "date",
            "abstract",
            "journalAbbreviation",
            "itemType",
        ]:
            if field in field_comp:
                count = field_comp[field]["count"]
                pct = field_comp[field]["percentage"]
                report_lines.append(
                    f"  {field:<25}: {count:>4}/{total:>4} ({pct:>5.1f}%)"
                )

    report_lines.append("\n" + "=" * 70 + "\n")

    return "\n".join(report_lines)


def generate_itemtype_distribution_report(df: pd.DataFrame) -> str:
    """Generate itemType distribution report by API.

    Args:
        df: DataFrame with papers, archive column, and itemType column

    Returns:
        Formatted report showing itemType counts and percentages per API
    """
    if df.empty:
        return "No data available for itemType distribution."

    report_lines = [
        "\n" + "=" * 70,
        "ITEMTYPE DISTRIBUTION BY API",
        "=" * 70,
    ]

    # Group by API and itemType
    api_itemtype_counts = defaultdict(lambda: defaultdict(int))
    api_totals = defaultdict(int)

    for _, row in df.iterrows():
        archive = row.get("archive", "")

        if is_missing(archive):
            continue

        # Parse archive (primary API is marked with *)
        apis = parse_archive_apis(archive)
        primary_api = next(
            (api for api in apis if "*" in str(row.get("archive", "")) and api),
            apis[0] if apis else "Unknown",
        )

        # Count total papers per API
        api_totals[primary_api] += 1

        # Count itemType occurrences
        item_type = row.get("itemType", MISSING_VALUE)
        if is_missing(item_type):
            item_type = "Missing/NA"
        api_itemtype_counts[primary_api][item_type] += 1

    # Generate report for each API
    for api in sorted(api_itemtype_counts.keys()):
        total = api_totals[api]
        itemtype_counts = api_itemtype_counts[api]

        report_lines.append(f"\n{api} ({total} papers):")
        report_lines.append("-" * 40)

        # Sort by count (descending) then by itemType name
        sorted_items = sorted(itemtype_counts.items(), key=lambda x: (-x[1], x[0]))

        for item_type, count in sorted_items:
            pct = (count / total * 100) if total > 0 else 0.0
            report_lines.append(f"  {item_type:<25}: {count:>4} ({pct:>5.1f}%)")

    report_lines.append("\n" + "=" * 70 + "\n")

    return "\n".join(report_lines)


def analyze_and_report_duplicates(
    df: pd.DataFrame, generate_report: bool = True
) -> tuple[DuplicateSourceAnalyzer, dict]:
    """Analyze duplicate sources and metadata quality.

    Args:
        df: DataFrame with aggregated papers
        generate_report: Whether to generate and log reports

    Returns:
        (analyzer, metadata_quality): Analyzer object and metadata quality stats
    """
    analyzer = DuplicateSourceAnalyzer()
    analyzer.analyze_from_dataframe(df)

    metadata_quality = analyze_api_metadata_quality(df)

    if generate_report:
        # Generate duplicate tracking report
        dup_report = analyzer.generate_report()
        logging.info(dup_report)

        # Generate metadata quality report
        quality_report = generate_metadata_quality_report(metadata_quality)
        logging.info(quality_report)

    return analyzer, metadata_quality
