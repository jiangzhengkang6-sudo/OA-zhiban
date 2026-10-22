"""Fail closed before any test fixture connects to or resets a database."""
from sqlalchemy.engine import make_url


def validate_test_targets(environment: str, allow_reset: bool, *urls: str) -> None:
    if environment != "test" or not allow_reset or len(urls) != 3:
        raise RuntimeError("数据库测试需要 ENVIRONMENT=test 与 ALLOW_TEST_DATABASE_RESET=true")
    identities = []
    for value in urls:
        try:
            url = make_url(value)
            name = url.database or ""
            if url.get_backend_name() != "postgresql" or not name.endswith("_test"):
                raise ValueError("unsafe database")
            identities.append((url.host, url.port or 5432, name, url.username))
        except Exception:
            raise RuntimeError("拒绝数据库测试：三个连接地址必须指向同一个独立 PostgreSQL *_test 库") from None
    if len(set(identities)) != 1:
        raise RuntimeError("拒绝数据库测试：业务、迁移和 Checkpointer 连接目标不一致")
