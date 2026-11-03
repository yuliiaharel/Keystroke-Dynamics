from keystroke_dynamics.core.events import KeyPress
from keystroke_dynamics.core.features import Feature, extract_features


def test_extract_features_hold_and_flight_for_two_ordinary_keys() -> None:
    presses = [
        KeyPress(code="KeyA", down_t_ms=0, up_t_ms=50),
        KeyPress(code="KeyB", down_t_ms=100, up_t_ms=160),
    ]
    features = extract_features(presses)
    assert Feature(key=("hold", "KeyA"), value_ms=50) in features
    assert Feature(key=("hold", "KeyB"), value_ms=60) in features
    assert Feature(key=("flight", "KeyA", "KeyB"), value_ms=100) in features
    assert len(features) == 3


def test_extract_features_excludes_modifier_hold() -> None:
    presses = [KeyPress(code="ShiftLeft", down_t_ms=0, up_t_ms=50)]
    assert extract_features(presses) == []


def test_extract_features_flight_does_not_span_an_excluded_key() -> None:
    # A, Shift, B in sequence: no flight A->B should appear, since
    # Shift sits between them. No flight A->Shift or Shift->B either,
    # since both of those pairs include the excluded key.
    presses = [
        KeyPress(code="KeyA", down_t_ms=0, up_t_ms=10),
        KeyPress(code="ShiftLeft", down_t_ms=20, up_t_ms=30),
        KeyPress(code="KeyB", down_t_ms=40, up_t_ms=50),
    ]
    features = extract_features(presses)
    flight_keys = [f.key for f in features if f.key[0] == "flight"]
    assert flight_keys == []


def test_extract_features_long_pause_creates_no_flight() -> None:
    presses = [
        KeyPress(code="KeyA", down_t_ms=0, up_t_ms=50),
        KeyPress(code="KeyB", down_t_ms=5000, up_t_ms=5050),  # 5s gap
    ]
    features = extract_features(presses, max_pause_ms=2000)
    flight_keys = [f.key for f in features if f.key[0] == "flight"]
    assert flight_keys == []


def test_extract_features_flight_at_exactly_the_pause_limit_is_kept() -> None:
    presses = [
        KeyPress(code="KeyA", down_t_ms=0, up_t_ms=10),
        KeyPress(code="KeyB", down_t_ms=2000, up_t_ms=2010),
    ]
    features = extract_features(presses, max_pause_ms=2000)
    assert Feature(key=("flight", "KeyA", "KeyB"), value_ms=2000) in features


def test_extract_features_empty_input() -> None:
    assert extract_features([]) == []
