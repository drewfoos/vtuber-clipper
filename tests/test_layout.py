from clipper.layout import classify_layout


def test_large_face_classifies_as_tracking():
    summary = {"avg_x": 0.5, "avg_y": 0.5, "avg_bbox_w": 0.35, "avg_bbox_h": 0.5, "hit_rate": 0.9}
    assert classify_layout(summary) == "tracking"


def test_small_corner_face_classifies_as_stacked():
    summary = {"avg_x": 0.82, "avg_y": 0.85, "avg_bbox_w": 0.12, "avg_bbox_h": 0.20, "hit_rate": 0.95}
    assert classify_layout(summary) == "stacked"


def test_low_hit_rate_classifies_as_static():
    summary = {"avg_x": 0.6, "avg_y": 0.5, "avg_bbox_w": 0.15, "avg_bbox_h": 0.20, "hit_rate": 0.30}
    assert classify_layout(summary) == "static"


def test_no_detections_at_all_is_static():
    summary = {"avg_x": None, "avg_y": None, "avg_bbox_w": 0.0, "avg_bbox_h": 0.0, "hit_rate": 0.0}
    assert classify_layout(summary) == "static"


def test_threshold_is_configurable():
    summary = {"avg_x": 0.5, "avg_y": 0.5, "avg_bbox_w": 0.22, "avg_bbox_h": 0.4, "hit_rate": 0.9}
    assert classify_layout(summary, tracking_bbox_threshold=0.25) == "stacked"
    assert classify_layout(summary, tracking_bbox_threshold=0.20) == "tracking"
