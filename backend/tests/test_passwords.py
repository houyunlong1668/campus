import re

from app.auth.passwords import hash_password, verify_password


def test_同一密码两次哈希结果不同():
    assert hash_password("demo1234") != hash_password("demo1234")


def test_格式符合约定():
    encoded = hash_password("demo1234")
    assert re.fullmatch(r"pbkdf2_sha256\$600000\$[A-Za-z0-9+/=]{22,}\$[A-Za-z0-9+/=]{43,}", encoded)


def test_正确密码通过_错误密码不通过():
    encoded = hash_password("demo1234")
    assert verify_password("demo1234", encoded) is True
    assert verify_password("wrong", encoded) is False


def test_空串与畸形哈希不抛异常():
    assert verify_password("", "") is False
    assert verify_password("x", "pbkdf2_sha256$600000$abc") is False
    assert verify_password("x", "bcrypt$600000$abc$def") is False
    assert verify_password("x", "pbkdf2_sha256$不是数字$abc$def") is False
