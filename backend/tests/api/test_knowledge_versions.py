"""B6 Task 6.2 source/version lifecycle API tests."""

import httpx
import pytest
from sqlalchemy import text

from app.db.session import engine
from app.main import app as fastapi_app


@pytest.fixture
async def client(graph_ready):
    async with engine.begin() as conn:
        await conn.execute(text(
            "TRUNCATE knowledge_chunk, knowledge_file, knowledge_version, knowledge_source, "
            "knowledge_document RESTART IDENTITY CASCADE"
        ))
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def admin_headers():
    return {"Authorization": "Bearer mock:u_admin_001"}


@pytest.mark.asyncio
async def test_version_draft_publish_and_history_are_preserved(client, admin_headers):
    payload = {
        "source_name": "员工手册",
        "filename": "handbook.md",
        "content": "# V1\n\n请假需要审批。",
        "permission_tags": ["employee"],
    }
    first = await client.post("/api/admin/knowledge/versions", json=payload, headers=admin_headers)
    assert first.status_code == 200
    first_data = first.json()["data"]
    assert first_data["version"] == 1
    assert first_data["status"] == "draft"
    assert first_data["parse_status"] == "READY"

    published = await client.post(
        f"/api/admin/knowledge/versions/{first_data['id']}/publish", headers=admin_headers
    )
    assert published.status_code == 200
    assert published.json()["data"]["status"] == "published"

    second = await client.post(
        "/api/admin/knowledge/versions",
        json={**payload, "content": "# V2\n\n新版请假需要审批。"},
        headers=admin_headers,
    )
    assert second.status_code == 200
    second_data = second.json()["data"]
    assert second_data["version"] == 2

    published_second = await client.post(
        f"/api/admin/knowledge/versions/{second_data['id']}/publish", headers=admin_headers
    )
    assert published_second.status_code == 200

    from sqlalchemy import select
    from app.models.knowledge_version import KnowledgeVersion
    from app.db.session import async_session_factory

    async with async_session_factory() as session:
        rows = (await session.execute(select(KnowledgeVersion).order_by(KnowledgeVersion.version))).scalars().all()
        assert [row.status for row in rows] == ["offline", "published"]


@pytest.mark.asyncio
async def test_version_invalid_window_returns_structured_400(client, admin_headers):
    response = await client.post(
        "/api/admin/knowledge/versions",
        json={
            "source_name": "过期制度",
            "filename": "expired.md",
            "content": "内容",
            "expire_at": "2020-01-01T00:00:00Z",
        },
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "10001"


@pytest.mark.asyncio
async def test_search_prefers_current_published_version_citations(client, admin_headers):
    created = await client.post(
        "/api/admin/knowledge/versions",
        json={
            "source_name": "检索制度",
            "filename": "policy.md",
            "content": "# 请假\n\n请假需要逐级审批。",
            "permission_tags": [],
        },
        headers=admin_headers,
    )
    version_id = created.json()["data"]["id"]
    await client.post(f"/api/admin/knowledge/versions/{version_id}/publish", headers=admin_headers)

    from app.db.session import async_session_factory
    from app.services.knowledge_service import search

    async with async_session_factory() as session:
        hits = await search(session, query="请假审批", permission_tags=[], top_k=3)
    assert hits
    assert hits[0]["version"] == 1
    assert "section=请假" in hits[0]["source_location"]


@pytest.mark.asyncio
async def test_multipart_upload_accepts_html_and_stores_source_file(client, admin_headers, tmp_path):
    response = await client.post(
        "/api/admin/knowledge/versions/upload",
        data={"source_name": "HTML制度", "permission_tags": "employee,manager"},
        files={"file": ("policy.html", "<h1>制度</h1><p>正文</p>".encode("utf-8"), "text/html")},
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "draft"
