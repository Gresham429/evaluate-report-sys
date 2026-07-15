"""脚手架冒烟测试。"""


def test_src_importable() -> None:
    import src

    assert src.__name__ == "src"
