import pytest

from app.services.deliveries import ORDER_TARGET, TRANSITIONS, order_path


@pytest.mark.parametrize(
    ("current", "target", "path"),
    [
        ("CONFIRMED", "OUT_FOR_DELIVERY", ["READY_FOR_DELIVERY", "OUT_FOR_DELIVERY"]),
        ("PROCESSING", "DELIVERED", ["READY_FOR_DELIVERY", "DELIVERED"]),  # customer pickup skips "out"
        ("OUT_FOR_DELIVERY", "DELIVERED", ["DELIVERED"]),
        ("OUT_FOR_DELIVERY", "READY_FOR_DELIVERY", ["READY_FOR_DELIVERY"]),  # failed attempt
        ("DELIVERED", "RETURNED", ["RETURNED"]),
        ("READY_FOR_DELIVERY", "READY_FOR_DELIVERY", []),
        ("CANCELLED", "DELIVERED", []),  # unreachable
    ],
)
def test_order_follows_delivery(current: str, target: str, path: list[str]) -> None:
    assert order_path(current, target) == path


def test_never_passes_through_a_stop_state() -> None:
    # NEW → DELIVERED would need CANCELLED/REJECTED as a hop if stops were allowed; it must go via CONFIRMED.
    assert order_path("NEW", "DELIVERED") == ["CONFIRMED", "READY_FOR_DELIVERY", "DELIVERED"]


def test_every_delivery_status_has_an_order_rule() -> None:
    assert set(TRANSITIONS) - {"PENDING"} == set(ORDER_TARGET)
