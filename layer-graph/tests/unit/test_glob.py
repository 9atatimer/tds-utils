"""Layer glob matching, the adherence engine's semantics."""

from hypothesis import given
from hypothesis import strategies as st

from layer_graph.domain.glob import is_literal, matches, static_prefix

SEGMENT = st.text(alphabet="abcdefgh-_.", min_size=1, max_size=6).filter(
    lambda s: s not in {".", ".."}
)


def test_matches_double_star_crosses_directories() -> None:
    """Given a ** glob, When a path lies several levels below, Then it matches."""
    assert matches("packages/core/src/**", "packages/core/src/a/b/c.ts")


def test_matches_single_star_stays_in_one_segment() -> None:
    """Given a * glob, When the path has a further directory, Then it does not
    match."""
    assert matches("tests/*.py", "tests/a.py")
    assert not matches("tests/*.py", "tests/unit/a.py")


def test_matches_trailing_double_star_needs_one_segment() -> None:
    """Given dir/**, When the path is the directory itself, Then it does not
    match: a trailing ** matches one or more segments."""
    assert not matches("src/**", "src")


def test_static_prefix_stops_at_first_wildcard_segment() -> None:
    """Given a glob, When its static prefix is taken, Then it is the segments
    before the first wildcard."""
    assert static_prefix("packages/*/test/**") == "packages"
    assert static_prefix("packages/core/src/domain/**") == "packages/core/src/domain"
    assert static_prefix("**/*.py") == ""


def test_is_literal_tells_a_file_from_a_glob() -> None:
    """Given a pattern, When asked whether it names one path, Then only a
    pattern with no glob character does."""
    assert is_literal("packages/core/src/index.ts")
    assert not is_literal("packages/core/src/*.ts")


@given(st.lists(SEGMENT, min_size=1, max_size=5))
def test_matches_literal_path_matches_itself(segments: list[str]) -> None:
    """Given any literal path, When matched against itself, Then it matches."""
    path = "/".join(segments)
    assert matches(path, path)


@given(
    st.lists(SEGMENT, min_size=1, max_size=4), st.lists(SEGMENT, min_size=1, max_size=4)
)
def test_matches_prefix_double_star_matches_every_descendant(
    prefix: list[str], rest: list[str]
) -> None:
    """Given dir/**, When any path below dir is matched, Then it matches and
    dir is the static prefix."""
    directory = "/".join(prefix)
    assert matches(f"{directory}/**", f"{directory}/{'/'.join(rest)}")
    assert static_prefix(f"{directory}/**") == directory
