"""Filtering progress tracker for the aggregation pipeline."""


class FilteringTracker:
    """Track filtering stages and generate comprehensive reports."""

    def __init__(self):
        self.stages: list[dict] = []
        self.initial_count: int = 0

    def set_initial(
        self, count: int, description: str = "Raw papers collected"
    ) -> None:
        """Set initial paper count."""
        self.initial_count = count
        self.stages.append(
            {
                "stage": "Initial",
                "description": description,
                "papers": count,
                "removed": 0,
                "removal_rate": 0.0,
            }
        )

    def add_stage(
        self, stage_name: str, papers_remaining: int, description: str = ""
    ) -> None:
        """Add a filtering stage with paper count."""
        if not self.stages:
            self.set_initial(papers_remaining, "Starting point")
            return

        prev_count = self.stages[-1]["papers"]
        removed = prev_count - papers_remaining
        removal_rate = (removed / prev_count * 100) if prev_count > 0 else 0.0

        self.stages.append(
            {
                "stage": stage_name,
                "description": description,
                "papers": papers_remaining,
                "removed": removed,
                "removal_rate": removal_rate,
            }
        )

    def generate_report(self) -> str:
        """Generate comprehensive filtering summary report."""
        if not self.stages or self.initial_count == 0:
            return "No filtering data available"

        lines = []
        lines.append("\n" + "=" * 80)
        lines.append("FILTERING PIPELINE SUMMARY")
        lines.append("=" * 80)

        for i, stage_info in enumerate(self.stages):
            stage = stage_info["stage"]
            desc = stage_info["description"]
            papers = stage_info["papers"]
            removed = stage_info["removed"]
            removal_rate = stage_info["removal_rate"]

            # Calculate cumulative removal
            cumulative_removed = self.initial_count - papers
            cumulative_rate = (
                (cumulative_removed / self.initial_count * 100)
                if self.initial_count > 0
                else 0.0
            )

            lines.append("")
            if i == 0:
                lines.append(f"[{stage}] {desc}")
                lines.append(f"  Papers: {papers:,}")
            else:
                lines.append(f"[{stage}] {desc}")
                lines.append(f"  Papers remaining: {papers:,}")
                lines.append(f"  Removed this stage: {removed:,} ({removal_rate:.1f}%)")
                lines.append(
                    f"  Cumulative removal: {cumulative_removed:,} ({cumulative_rate:.1f}%)"
                )

        final_count = self.stages[-1]["papers"]
        total_removed = self.initial_count - final_count
        total_removal_rate = (
            (total_removed / self.initial_count * 100)
            if self.initial_count > 0
            else 0.0
        )

        lines.append("")
        lines.append("-" * 80)
        lines.append("FINAL RESULTS:")
        lines.append(f"  Started with: {self.initial_count:,} papers")
        lines.append(f"  Final output: {final_count:,} papers")
        lines.append(
            f"  Total removed: {total_removed:,} papers ({total_removal_rate:.1f}%)"
        )
        lines.append(f"  Retention rate: {100 - total_removal_rate:.1f}%")
        lines.append("=" * 80)

        return "\n".join(lines)
