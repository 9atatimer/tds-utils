#!/usr/bin/env bash
# release_test -- the fixture's own smoke test.

test_release_needs_a_unit() {
    bash bin/release.sh </dev/null
}
