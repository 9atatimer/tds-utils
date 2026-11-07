"""Context derivation: which node a unit file belongs to within its layer."""

from layer_graph.domain.context import Origin, context_for, qualified_contexts


def test_context_for_file_in_subdirectory_is_first_segment_after_prefix() -> None:
    """Given a glob ending in **, When a file sits in a subdirectory of its
    static prefix, Then the context is that subdirectory's name."""
    assert (
        context_for(
            "packages/core/src/domain/**",
            "packages/core/src/domain/timeline/fold.ts",
        )
        == "timeline"
    )


def test_context_for_deeply_nested_file_is_still_first_segment() -> None:
    """Given a file several directories below the prefix, When its context is
    derived, Then only the first segment after the prefix names it."""
    assert (
        context_for("apps/web/server/api/**", "apps/web/server/api/games/[id]/x.ts")
        == "games"
    )


def test_context_for_file_directly_in_prefix_is_prefix_label() -> None:
    """Given a file directly in the glob's prefix, When its context is derived,
    Then it is the prefix's last segment."""
    assert context_for("adherence/tests/*.py", "adherence/tests/kit.py") == "tests"


def test_context_for_prefix_ending_in_src_takes_the_package_name() -> None:
    """Given a prefix whose last segment is the generic src, When a file sits
    directly in it, Then the label is the directory above, so two adapter
    packages stay apart."""
    assert (
        context_for(
            "packages/adapters-memory/src/**",
            "packages/adapters-memory/src/index.ts",
        )
        == "adapters-memory"
    )


def test_context_for_single_file_glob_is_the_file_stem() -> None:
    """Given a glob naming one file, When its context is derived, Then it is
    the file's stem."""
    assert context_for("packages/core/src/index.ts", "packages/core/src/index.ts") == (
        "index"
    )


def test_context_for_wildcard_in_middle_uses_matched_segment() -> None:
    """Given a glob whose wildcard is a package directory, When a file matches,
    Then the context is the package the file is in."""
    assert context_for("packages/*/test/**", "packages/core/test/a.test.ts") == "core"


def test_qualified_contexts_leaves_unique_names_alone() -> None:
    """Given two origins with different context names, When qualified, Then
    each keeps its own name."""
    a = Origin("domain", "packages/core/src/domain", "table", "packages/core")
    b = Origin("domain", "packages/core/src/domain", "timeline", "packages/core")
    assert qualified_contexts([a, b]) == {a: "table", b: "timeline"}


def test_qualified_contexts_prefixes_package_on_collision() -> None:
    """Given two globs in different packages yielding the same context in one
    layer, When qualified, Then each name carries its package directory."""
    core = Origin(
        "composition root", "packages/core/src/index.ts", "index", "packages/core"
    )
    bot = Origin(
        "composition root",
        "cloudflare/assistant/src/index.ts",
        "index",
        "cloudflare/assistant",
    )
    assert qualified_contexts([core, bot]) == {
        core: "core:index",
        bot: "assistant:index",
    }


def test_qualified_contexts_same_package_uses_differing_segment() -> None:
    """Given two globs in one package yielding the same context, When
    qualified, Then each name carries the first path segment that differs."""
    server = Origin(
        "composition root", "apps/web/server/composition", "composition", "apps/web"
    )
    app = Origin(
        "composition root", "apps/web/app/composition", "composition", "apps/web"
    )
    assert qualified_contexts([server, app]) == {
        server: "server:composition",
        app: "app:composition",
    }


def test_qualified_contexts_other_layer_does_not_collide() -> None:
    """Given the same context name in two layers, When qualified, Then neither
    is prefixed: nodes are per layer."""
    a = Origin("domain", "x/domain", "table", "x")
    b = Origin("application", "x/application", "table", "x")
    assert qualified_contexts([a, b]) == {a: "table", b: "table"}
