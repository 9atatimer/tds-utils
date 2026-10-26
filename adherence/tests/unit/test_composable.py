"""The Composable quality's checks -- Values in and out, No nesting, Helpers
take values -- driven through `measure` with a fake behind every port
(DESIGN.ARCH-ADHERENCE.md, Behaviors; ARCHITECTURE.ARCH-ADHERENCE.md,
Use-case surface)."""

from __future__ import annotations

from adherence.container import SHIPPED_VOCABULARY
from adherence.domain.finding import Finding
from adherence.domain.model import Binding, Layer
from adherence.domain.report import Report
from tests.facts_kit import (
    FS,
    RULES,
    STORE,
    TEST,
    USE,
    facts,
    function,
    keyword,
    port,
    type_,
    value,
)
from tests.measure_kit import measure_with


def _of(report: Report, check: str) -> list[Finding]:
    return [f for f in report.findings if f.check.name == check]


def test_measure_with_a_function_inside_another_finds_both() -> None:
    """Given a function defined inside a use case, a method of a class
    defined inside a domain function, and a function nested in a test, When
    No nesting runs, Then a finding names each non-test nested function and
    the function enclosing it, and the test's is clean."""
    files = {USE: b"x\n" * 9, RULES: b"x\n" * 9, TEST: b"x\n" * 9}
    definitions = [
        function(USE, "close_order", 1, end=6),
        function(USE, "close_order.helper", 3, parent="close_order", nested=True),
        function(RULES, "make", 1, end=8),
        type_(RULES, "make.Local", 2, parent="make", nested=True),
        function(RULES, "make.Local.run", 3, parent="make.Local", nested=True),
        function(TEST, "test_it", 1, end=5),
        function(TEST, "test_it.inner", 2, parent="test_it", nested=True),
    ]

    report = measure_with(files, facts(definitions))

    assert "No nesting" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject, f.layer) for f in _of(report, "No nesting")}
    assert found == {
        (
            "close_order.helper",
            "close_order.helper inside close_order",
            Layer.APPLICATION,
        ),
        ("make.Local.run", "make.Local.run inside make", Layer.DOMAIN),
    }
    assert all(f.check.quality.value == "Composable" for f in _of(report, "No nesting"))


def test_measure_with_a_helper_taking_a_port_or_callable_finds_both() -> None:
    """Given domain helpers that take a port, a callable and (as a method) a
    port, a domain helper that takes values, and a use case that takes the
    port, When Helpers take values runs, Then a finding names each helper
    and the parameter, and the helper taking values and the use case are
    clean."""
    files = {RULES: b"x\n" * 9, USE: b"x\n" * 9, STORE: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        type_(RULES, "Order", 1, end=3),
        function(
            RULES,
            "Order.keep",
            2,
            (value("self"), value("store", '"Store"')),
            parent="Order",
        ),
        function(
            RULES, "price", 5, (value("order", "Order"), keyword("store", "Store"))
        ),
        function(RULES, "apply", 6, (value("rule", "Callable[[int], int]"),)),
        function(RULES, "total", 7, (value("order", "Order"),), returns="int"),
        function(USE, "close", 1, (value("order", "Order"), keyword("store", "Store"))),
    ]

    report = measure_with(files, facts(definitions))

    assert "Helpers take values" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject) for f in _of(report, "Helpers take values")}
    assert found == {
        ("Order.keep", 'store: "Store"'),
        ("price", "store: Store"),
        ("apply", "rule: Callable[[int], int]"),
    }


def test_measure_with_a_wire_format_in_a_signature_finds_the_parameter() -> None:
    """Given use cases whose signatures carry a wire format (a parameter and
    a return), an SDK type and a concrete adapter, a private application
    helper taking a wire format, and a use case taking values and a port,
    When Values in and out runs, Then a finding names each parameter of a
    use case that carries one, and the rest are clean."""
    files = {USE: b"x\n" * 9, STORE: b"x\n" * 9, FS: b"x\n" * 9}
    definitions = [
        *port(STORE, "Store", 1),
        type_(FS, "FsStore", 1),
        function(
            USE,
            "fetch",
            1,
            (value("payload", "dict[str, object]"), keyword("store", "Store")),
            returns="Response",
        ),
        function(USE, "send", 2, (keyword("session", "requests.Session"),)),
        function(
            USE, "save", 3, (value("order", "Order"), keyword("store", "FsStore"))
        ),
        function(USE, "_parse", 4, (value("raw", "dict"),)),
        function(
            USE,
            "close",
            5,
            (value("order", "Order"), keyword("store", "Store")),
            returns="str",
        ),
    ]

    report = measure_with(files, facts(definitions))

    assert "Values in and out" in {c.name for c in report.ran}
    found = {(f.unit.symbol, f.subject) for f in _of(report, "Values in and out")}
    assert found == {
        ("fetch", "payload: dict[str, object]"),
        ("fetch", "return: Response"),
        ("send", "session: requests.Session"),
        ("save", "store: FsStore"),
    }


def test_measure_with_a_domain_type_named_like_a_wire_format_is_clean() -> None:
    """Given, under the shipped vocabulary, a domain value the repository
    defines under a wire format's name (Request), use cases taking it, a
    typed mapping of domain values, a Dict of them and bytes, and one use
    case taking a Response the repository does not define, When Values in
    and out runs, Then only the Response is found: a name the measured
    repository defines is its own, and a typed mapping or bytes is a
    value, not a wire format."""
    files = {USE: b"x\n" * 9, RULES: b"x\n" * 9}
    definitions = [
        type_(RULES, "Request", 1),
        function(
            USE,
            "req",
            1,
            (value("order", "Order"), value("r", "Request")),
            returns="dict[str, Order]",
        ),
        function(USE, "index", 2, (value("orders", "Dict[str, Order]"),)),
        function(USE, "load", 3, (value("data", "bytes"),)),
        function(USE, "send", 4, (value("reply", "Response"),)),
    ]

    report = measure_with(files, facts(definitions), vocabulary=SHIPPED_VOCABULARY)

    found = {(f.unit.symbol, f.subject) for f in _of(report, "Values in and out")}
    assert found == {("send", "reply: Response")}


def test_measure_with_a_type_alias_of_a_wire_format_finds_the_parameter() -> None:
    """Given a module-level alias of a wire format (`Payload = dict`), an
    alias of an alias, and a local name bound in a use case under the same
    spelling, When Values in and out runs, Then a finding names each
    use-case parameter annotated with a module alias: an alias is resolved
    before it is matched, and only a module-level one names a type."""
    files = {USE: b"x\n" * 9}
    definitions = [
        function(USE, "aliased", 3, (value("p", "Payload"),)),
        function(USE, "twice", 4, (value("q", "Body"),)),
        function(USE, "local", 5, (value("r", "Thing"),), end=7),
    ]
    bindings = (
        Binding(USE, 1, None, "Payload", "dict"),
        Binding(USE, 2, None, "Body", "Payload"),
        Binding(USE, 6, "local", "Thing", "dict"),
    )

    report = measure_with(files, facts(definitions, bindings=bindings))

    found = {(f.unit.symbol, f.subject) for f in _of(report, "Values in and out")}
    assert found == {("aliased", "p: Payload"), ("twice", "q: Body")}


def test_measure_with_an_sdk_type_imported_by_name_finds_the_parameter() -> None:
    """Given a use case taking an SDK type imported by name (`from requests
    import Client`), one taking it through an aliased vendor module, and
    one taking a type imported from the repository's own domain, When
    Values in and out runs, Then a finding names each parameter whose type
    resolves to a vendor module, and the domain type is clean."""
    files = {USE: b"x\n" * 12}
    definitions = [
        function(USE, "call", 4, (value("c", "Client"),)),
        function(USE, "boto", 5, (value("s", "b3.Session"),)),
        function(USE, "keep", 6, (value("order", "Order"),)),
    ]
    bindings = (
        Binding(USE, 1, None, "Client", "requests.Client"),
        Binding(USE, 2, None, "b3", "boto3"),
        Binding(USE, 3, None, "Order", "app.domain.rules.Order"),
    )

    report = measure_with(files, facts(definitions, bindings=bindings))

    found = {(f.unit.symbol, f.subject) for f in _of(report, "Values in and out")}
    assert found == {("call", "c: Client"), ("boto", "s: b3.Session")}
