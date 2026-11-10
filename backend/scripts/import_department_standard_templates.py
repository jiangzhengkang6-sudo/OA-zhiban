"""导入“部门业务标准模板资料包”。

默认仅预检；使用 --apply 后才会写入知识源、版本、切片、向量、租户授权和审计。
重复执行按内容哈希复用版本，避免重复导入和重复生成向量。
"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.migrations import assert_schema_current
from app.db.session import engine
from app.models.identity import OAUser
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.services.authorization_service import require_fresh_identity, require_permission
from app.services.identity_service import current_identity
from app.services.knowledge_version_service import create_version, publish_version
from app.services.oa_scope_service import create_binding, record_audit
from app.storage.local import LocalObjectStore

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "department-business-knowledge"


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_manifest() -> tuple[dict, list[dict]]:
    manifest_path = CORPUS / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = []
    for item in manifest["documents"]:
        path = (CORPUS / item["file"]).resolve()
        if CORPUS.resolve() not in path.parents or path.parent.name != "documents" or path.suffix != ".md":
            raise ValueError("invalid_document_path")
        content = path.read_bytes()
        documents.append({**item, "path": path, "content": content, "content_hash": sha256(content)})
    return manifest, documents


async def build_actor(db, username: str):
    settings = get_settings()
    user = await db.scalar(select(OAUser).where(
        OAUser.tenant_id == settings.auth_tenant_id,
        OAUser.normalized_username == username,
        OAUser.status == "active",
    ))
    if user is None:
        raise ValueError("active_user_not_found")
    actor = await current_identity(db, user)
    actor = await require_fresh_identity(actor, session=db)
    require_permission(actor, "knowledge", "write")
    return actor


async def inspect_or_apply(db, actor, manifest, documents, apply: bool):
    store = LocalObjectStore(get_settings().knowledge_storage_dir)
    results = []
    created_count = 0

    for item in documents:
        source = await db.scalar(select(KnowledgeSource).where(
            KnowledgeSource.tenant_id == actor.tenant_id,
            KnowledgeSource.name == item["title"],
        ))
        existing_version = None
        if source is not None:
            existing_version = await db.scalar(select(KnowledgeVersion).where(
                KnowledgeVersion.source_id == source.id,
                KnowledgeVersion.content_hash == item["content_hash"],
                KnowledgeVersion.parse_status == "READY",
            ).order_by(KnowledgeVersion.version.desc()))

        if not apply:
            results.append({
                "id": item["id"],
                "title": item["title"],
                "source_exists": source is not None,
                "matching_version_exists": existing_version is not None,
                "matching_version_published": bool(existing_version and existing_version.status == "published"),
                "action": "复用" if existing_version and existing_version.status == "published" else "待创建或发布",
            })
            continue

        action = "复用已发布版本"
        version = existing_version
        if version is None:
            version = await create_version(
                db,
                source_name=item["title"],
                content=item["content"],
                filename=item["path"].name,
                permission_tags=[],
                owner_id=actor.user_id,
                store=store,
                content_type="text/markdown",
                tenant_id=actor.tenant_id,
            )
            action = "创建并发布新版本"
            created_count += 1
        elif version.status != "published":
            action = "发布既有同内容版本"

        source = await db.get(KnowledgeSource, version.source_id)
        source.source_type = "standard_template"
        source.owner_id = actor.user_id
        source.description = f"{manifest['dataset_name']}｜{item['template_no']}｜标准模板（试运行）"

        if version.status != "published":
            version = await publish_version(db, version.id)

        await create_binding(
            db,
            actor=actor,
            source_id=source.id,
            owner_id=actor.user_id,
            department_id=None,
            access_scope="tenant",
            version_rule={
                "dataset_id": manifest["dataset_id"],
                "template_no": item["template_no"],
                "status": "standard_template_trial",
            },
        )
        results.append({
            "id": item["id"],
            "title": item["title"],
            "source_id": str(source.id),
            "version_id": str(version.id),
            "version": version.version,
            "action": action,
        })

    if apply:
        await record_audit(
            db,
            actor=actor,
            resource="knowledge",
            action="standard_templates_apply",
            object_type="standard_template_corpus",
            object_id=manifest["dataset_id"],
            source_type="fixture",
            source_id=str(CORPUS),
            detail={
                "documents": len(documents),
                "new_versions": created_count,
                "status": "standard_template_trial",
                "applied_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return results


async def run(options):
    manifest, documents = load_manifest()
    async with engine.begin() as conn:
        await conn.run_sync(assert_schema_current)

    from app.db.session import async_session_factory
    async with async_session_factory() as db:
        actor = await build_actor(db, options.username)
        results = await inspect_or_apply(db, actor, manifest, documents, options.apply)
        if options.apply:
            await db.commit()
        else:
            await db.rollback()

    return {
        "dataset_id": manifest["dataset_id"],
        "dataset_name": manifest["dataset_name"],
        "apply": options.apply,
        "documents_total": len(documents),
        "results": results,
        "note": "标准模板（试运行），不自动代表公司正式制度。",
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="实际写入数据库；默认仅预检")
    parser.add_argument("--username", default="oa_admin", help="执行导入的管理员登录账号")
    return parser.parse_args()


if __name__ == "__main__":
    async def main():
        options = parse_args()
        try:
            report = await run(options)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        finally:
            await engine.dispose()

    sys.exit(asyncio.run(main()))
