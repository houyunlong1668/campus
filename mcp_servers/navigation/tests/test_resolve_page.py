import pytest

from server import PAGE_REGISTRY, resolve_page_impl


def test_registry_has_four_pages():
    assert len(PAGE_REGISTRY) == 4
    paths = {p.path for p in PAGE_REGISTRY}
    assert paths == {"/academic/schedule", "/academic/grades", "/academic/makeup", "/library"}


@pytest.mark.parametrize(
    ("intent", "expected_path"),
    [
        ("我想看看这学期要上什么课", "/academic/schedule"),
        ("查一下我的成绩", "/academic/grades"),
        ("补考时间是什么时候", "/academic/makeup"),
        ("图书馆还能借书吗", "/library"),
    ],
)
def test_keyword_hit(intent, expected_path):
    resolved = resolve_page_impl(intent)
    assert resolved.path == expected_path


def test_no_match_raises():
    with pytest.raises(ValueError, match="no matching page"):
        resolve_page_impl("今天天气怎么样")
