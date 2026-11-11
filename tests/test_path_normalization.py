"""Unit tests for path normalization utilities."""

from scilex.constants import normalize_path_component


def test_normalize_leading_slash():
    """Test normalization of paths with leading slashes."""
    assert normalize_path_component("/file.csv") == "file.csv"
    assert (
        normalize_path_component("/aggregated_results.csv") == "aggregated_results.csv"
    )


def test_normalize_trailing_slash():
    """Test normalization of paths with trailing slashes."""
    assert normalize_path_component("dirname/") == "dirname"
    assert normalize_path_component("collect_name/") == "collect_name"


def test_normalize_both_slashes():
    """Test normalization of paths with both leading and trailing slashes."""
    assert normalize_path_component("/dirname/") == "dirname"
    assert normalize_path_component("/collect_20260114/") == "collect_20260114"


def test_normalize_no_slashes():
    """Test that normal paths are not modified."""
    assert normalize_path_component("normal_path") == "normal_path"
    assert (
        normalize_path_component("aggregated_results.csv") == "aggregated_results.csv"
    )


def test_normalize_multiple_leading():
    """Test normalization of paths with multiple leading slashes."""
    assert normalize_path_component("///file.csv") == "file.csv"
    assert normalize_path_component("////dirname") == "dirname"


def test_normalize_multiple_trailing():
    """Test normalization of paths with multiple trailing slashes."""
    assert normalize_path_component("file.csv///") == "file.csv"
    assert normalize_path_component("dirname////") == "dirname"


def test_normalize_multiple_both():
    """Test normalization of paths with multiple leading and trailing slashes."""
    assert normalize_path_component("///file.csv///") == "file.csv"
    assert normalize_path_component("////dirname////") == "dirname"


def test_normalize_with_subdirs():
    """Test that internal slashes are preserved."""
    assert normalize_path_component("/path/to/file.csv") == "path/to/file.csv"
    assert normalize_path_component("path/to/file.csv/") == "path/to/file.csv"
    assert normalize_path_component("/path/to/file.csv/") == "path/to/file.csv"


def test_normalize_empty_string():
    """Test normalization of edge case: empty string."""
    assert normalize_path_component("") == ""


def test_normalize_only_slashes():
    """Test normalization of edge case: only slashes."""
    assert normalize_path_component("/") == ""
    assert normalize_path_component("//") == ""
    assert normalize_path_component("///") == ""


if __name__ == "__main__":
    """Run all tests when script is executed directly."""
    import inspect
    import sys

    # Get all test functions
    test_functions = [
        (name, obj)
        for name, obj in inspect.getmembers(sys.modules[__name__])
        if inspect.isfunction(obj) and name.startswith("test_")
    ]

    print(f"Running {len(test_functions)} tests...\n")

    passed = 0
    failed = 0

    for test_name, test_func in test_functions:
        try:
            test_func()
            print(f"✓ {test_name}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {test_name}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test_name}: Unexpected error: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    sys.exit(0 if failed == 0 else 1)
