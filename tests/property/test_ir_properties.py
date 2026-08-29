"""Property tests for serialization and value constraints."""

from hypothesis import given
from hypothesis import strategies as st

from edge_delegate.contracts import PlanIR, PlanStep, Route, ValueKind, ValueSpec
from edge_delegate.ir import canonicalize_plan, parse_plan

JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(2**31), max_value=2**31 - 1),
    st.floats(allow_nan=False, allow_infinity=False, width=32),
    st.text(max_size=50),
)


@given(value=JSON_SCALARS)
def test_canonical_plan_round_trip_preserves_json_scalar(value) -> None:
    plan = PlanIR(
        request_id="property-request",
        route=Route.LOCAL,
        steps=(
            PlanStep(
                step_id="echo",
                capability_id="utility.echo",
                arguments={"value": value},
            ),
        ),
    )
    assert parse_plan(canonicalize_plan(plan)) == plan


@given(value=st.integers(), minimum=st.integers(), width=st.integers(min_value=0, max_value=1000))
def test_integer_bounds_are_enforced(value: int, minimum: int, width: int) -> None:
    maximum = minimum + width
    spec = ValueSpec(kind=ValueKind.INTEGER, minimum=minimum, maximum=maximum)
    assert spec.matches(value) is (minimum <= value <= maximum)
