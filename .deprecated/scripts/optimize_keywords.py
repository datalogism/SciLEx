#!/usr/bin/env python3
"""
Keyword Optimization Utility for SciLEx

This script analyzes keyword combinations in scilex.config.yml and provides
recommendations for reducing redundancy and improving query efficiency.
"""

import os
import sys
from itertools import product

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import yaml


def load_config():
    """Load the scilex configuration"""
    config_path = os.path.join(os.path.dirname(__file__), "scilex.config.yml")
    try:
        with open(config_path) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: Configuration file not found at {config_path}")
        sys.exit(1)


def analyze_keywords(config):
    """Analyze keyword combinations and provide statistics"""
    keywords = config.get("keywords", [[], []])
    years = config.get("years", [])
    apis = config.get("apis", [])

    # Check if dual keyword mode
    dual_mode = len(keywords) == 2 and len(keywords[0]) > 0 and len(keywords[1]) > 0

    if dual_mode:
        keyword_combinations = list(product(keywords[0], keywords[1]))
    else:
        keyword_combinations = keywords[0]

    num_combinations = len(keyword_combinations)
    num_apis = len(apis)
    num_years = len(years)
    total_queries = num_combinations * num_apis * num_years

    return {
        "dual_mode": dual_mode,
        "keyword_groups": keywords,
        "num_combinations": num_combinations,
        "num_apis": num_apis,
        "num_years": num_years,
        "total_queries": total_queries,
        "combinations": keyword_combinations,
        "apis": apis,
        "years": years,
    }


def find_redundancies(stats):
    """Identify redundant keywords (singular/plural, etc.)"""
    redundancies = []

    if stats["dual_mode"]:
        for group_idx, group in enumerate(stats["keyword_groups"]):
            group_redundancies = []
            checked = set()

            for i, kw1 in enumerate(group):
                if kw1 in checked:
                    continue

                for j, kw2 in enumerate(group):
                    if i >= j:
                        continue

                    # Check for plural/singular
                    if kw1.rstrip("s") == kw2.rstrip("s"):
                        group_redundancies.append((kw1, kw2, "plural/singular"))
                        checked.add(kw1)
                        checked.add(kw2)

                    # Check for very similar (one contains the other)
                    elif kw1 in kw2 or kw2 in kw1:
                        group_redundancies.append((kw1, kw2, "substring"))
                        checked.add(kw1)
                        checked.add(kw2)

            if group_redundancies:
                redundancies.append(
                    {
                        "group": f"Group {group_idx + 1}",
                        "redundancies": group_redundancies,
                    }
                )

    return redundancies


def generate_recommendations(stats, redundancies):
    """Generate optimization recommendations"""
    recommendations = []

    # Recommendation 1: Reduce redundancies
    if redundancies:
        total_redundant = sum(len(r["redundancies"]) for r in redundancies)
        recommendations.append(
            {
                "priority": "HIGH",
                "title": "Remove Redundant Keywords",
                "description": f"Found {total_redundant} pairs of redundant keywords",
                "potential_reduction": f"Could reduce by ~{total_redundant * 2} keyword terms",
                "action": "Combine singular/plural forms and substring duplicates",
            }
        )

    # Recommendation 2: API reduction
    if stats["num_apis"] > 5:
        recommendations.append(
            {
                "priority": "HIGH",
                "title": "Reduce Number of APIs",
                "description": f"Currently using {stats['num_apis']} APIs",
                "potential_reduction": f"Reducing to 3-4 core APIs could cut queries by {((stats['num_apis'] - 3) / stats['num_apis'] * 100):.0f}%",
                "action": "Focus on SemanticScholar, OpenAlex, and 1-2 specialized APIs",
            }
        )

    # Recommendation 3: Keyword explosion warning
    if stats["total_queries"] > 2000:
        recommendations.append(
            {
                "priority": "CRITICAL",
                "title": "Excessive Total Queries",
                "description": f"Current configuration generates {stats['total_queries']} API calls",
                "potential_reduction": "Target: 500-1000 total queries",
                "action": "Reduce keyword combinations and/or number of APIs",
            }
        )

    return recommendations


def print_report(stats, redundancies, recommendations):
    """Print optimization report"""
    print("\n" + "=" * 70)
    print("  SCILEX KEYWORD OPTIMIZATION REPORT")
    print("=" * 70 + "\n")

    # Current Configuration
    print("CURRENT CONFIGURATION:")
    print(
        f"  Mode: {'Dual Keyword Group' if stats['dual_mode'] else 'Single Keyword Group'}"
    )
    print(f"  Keyword Combinations: {stats['num_combinations']}")
    print(f"  APIs: {stats['num_apis']} ({', '.join(stats['apis'])})")
    print(f"  Years: {stats['num_years']} ({', '.join(map(str, stats['years']))})")
    print(f"  Total API Calls: {stats['total_queries']}\n")

    # Redundancies
    if redundancies:
        print("REDUNDANT KEYWORDS DETECTED:")
        for group_info in redundancies:
            print(f"\n  {group_info['group']}:")
            for kw1, kw2, reason in group_info["redundancies"]:
                print(f"    • '{kw1}' ↔ '{kw2}' ({reason})")
        print()

    # Recommendations
    if recommendations:
        print("RECOMMENDATIONS:")
        for i, rec in enumerate(recommendations, 1):
            print(f"\n  {i}. [{rec['priority']}] {rec['title']}")
            print(f"     {rec['description']}")
            print(f"     Potential Reduction: {rec['potential_reduction']}")
            print(f"     Action: {rec['action']}")

    print("\n" + "=" * 70 + "\n")


def generate_optimized_config(stats, output_path="scilex.config.optimized.yml"):
    """Generate an optimized configuration suggestion"""
    optimized = {
        "# OPTIMIZED CONFIGURATION": "Review and adjust as needed",
        "keywords": stats["keyword_groups"],
        "years": stats["years"],
        "# RECOMMENDED": "Reduce to 3-4 core APIs",
        "apis_recommended": ["SemanticScholar", "OpenAlex", "IEEE"],
        "apis_current": stats["apis"],
    }

    print(f"\nOptimized configuration saved to: {output_path}")
    print("Review the suggestions and manually update scilex.config.yml as needed.\n")


def main():
    print("\nLoading configuration...")
    config = load_config()

    print("Analyzing keywords...")
    stats = analyze_keywords(config)

    print("Finding redundancies...")
    redundancies = find_redundancies(stats)

    print("Generating recommendations...")
    recommendations = generate_recommendations(stats, redundancies)

    print_report(stats, redundancies, recommendations)


if __name__ == "__main__":
    main()
