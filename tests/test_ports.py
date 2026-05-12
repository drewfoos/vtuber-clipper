import socket
from clipper.util.ports import find_free_port


def test_find_free_port_in_range():
    port = find_free_port(start=8765, end=8800)
    assert 8765 <= port <= 8800


def test_find_free_port_skips_busy():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 8765))
    s.listen(1)
    try:
        port = find_free_port(start=8765, end=8800)
        assert port != 8765
    finally:
        s.close()


def test_find_free_port_raises_when_exhausted():
    import pytest
    with pytest.raises(RuntimeError, match="No free port"):
        find_free_port(start=1, end=0)  # invalid range
