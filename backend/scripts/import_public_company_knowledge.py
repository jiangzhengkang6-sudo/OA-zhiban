"""Publish a fixed, attributed public corpus through the formal knowledge services."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.context import set_current_user
from app.db.migrations import assert_schema_current
from app.db.session import async_session_factory, engine
from app.models.identity import OAUser
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_version import KnowledgeVersion
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_file import KnowledgeFile
from app.models.oa_ai_scope import OAKnowledgeBinding
from app.services.authorization_service import require_fresh_identity, require_permission
from app.services.identity_service import current_identity
from app.services import knowledge_version_service as versions
from app.services import oa_scope_service as scopes
from app.services.document_parser import parse_bytes
from app.storage.local import LocalObjectStore

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / 'fixtures' / 'public-company-knowledge'
OUTPUT = ROOT / 'output' / 'business-acceptance-private' / 'public-company-knowledge'


def digest(content):
    return hashlib.sha256(content).hexdigest()


def load_corpus():
    manifest = json.loads((CORPUS / 'manifest.json').read_text(encoding='utf-8'))
    documents = []
    for item in manifest['documents']:
        path = (CORPUS / item['file']).resolve()
        if CORPUS.resolve() not in path.parents or path.parent.name != 'documents' or path.suffix != '.md':
            raise ValueError('invalid_document_path')
        content = path.read_bytes()
        blocks = parse_bytes(content, path.name)
        documents.append(dict(item, content=content, sha256=digest(content),
                              block_count=len(blocks), filename=path.name))
    return manifest, documents


async def fetch_sources(manifest):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'sources': []}
    async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
        for source in manifest['sources']:
            response = await client.get(source['raw_url'])
            response.raise_for_status()
            raw = response.content
            if not response.text.startswith('---') or not all(
                fragment in response.text for fragment in source['check_fragments']
            ):
                raise ValueError('public_source_changed_requires_review:' + source['id'])
            (OUTPUT / (source['id'] + '.md')).write_bytes(raw)
            report['sources'].append(dict(id=source['id'], url=source['url'], raw_url=source['raw_url'],
                sha256=digest(raw), bytes=len(raw)))
        license_response = await client.get(manifest['license_page'])
        license_response.raise_for_status()
        if 'https://creativecommons.org/licenses/by-sa/4.0/' not in license_response.text:
            raise ValueError('public_license_not_verified')
        (OUTPUT / 'license-page.html').write_bytes(license_response.content)
        report['license_page_sha256'] = digest(license_response.content)
    report['manifest_sha256'] = digest((CORPUS / 'manifest.json').read_bytes())
    (OUTPUT / 'source-receipt.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def verified_receipt(manifest):
    receipt = json.loads((OUTPUT / 'source-receipt.json').read_text(encoding='utf-8'))
    if receipt['manifest_sha256'] != digest((CORPUS / 'manifest.json').read_bytes()):
        raise ValueError('source_receipt_manifest_mismatch')
    by_id = {item['id']: item for item in receipt['sources']}
    for source in manifest['sources']:
        raw = (OUTPUT / (source['id'] + '.md')).read_bytes()
        if digest(raw) != by_id[source['id']]['sha256'] or not all(
            fragment in raw.decode('utf-8') for fragment in source['check_fragments']
        ):
            raise ValueError('source_snapshot_mismatch')
    page = (OUTPUT / 'license-page.html').read_bytes()
    if digest(page) != receipt['license_page_sha256'] or b'https://creativecommons.org/licenses/by-sa/4.0/' not in page:
        raise ValueError('license_snapshot_mismatch')
    return receipt


async def actor_for_import(db, username):
    settings = get_settings()
    if settings.auth_provider != 'builtin' or settings.oa_provider != 'builtin':
        raise ValueError('formal_builtin_identity_required')
    user = await db.scalar(select(OAUser).where(OAUser.tenant_id == settings.auth_tenant_id,
        OAUser.normalized_username == username, OAUser.status == 'active'))
    actor = await current_identity(db, user)
    actor = await require_fresh_identity(actor, session=db)
    require_permission(actor, 'knowledge', 'write')
    if not actor.depts:
        raise ValueError('existing_department_required')
    return actor


async def inspect_version(db, version, document, store, dimension):
    files = list((await db.scalars(select(KnowledgeFile).where(KnowledgeFile.version_id == version.id))).all())
    chunks = list((await db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == version.id))).all())
    if len(files) != 1 or files[0].sha256 != document['sha256'] or digest(store.get(files[0].storage_ref)) != document['sha256']:
        raise ValueError('stored_original_mismatch')
    expected = [block.text for block in parse_bytes(document['content'], document['filename'])]
    ordered = sorted(chunks, key=lambda item: item.chunk_index)
    if [item.content for item in ordered] != expected or any(
        chunk.embedding is None or len(chunk.embedding) != dimension or
        chunk.content_hash != digest(chunk.content.encode('utf-8')) for chunk in chunks
    ):
        raise ValueError('stored_chunks_or_vectors_incomplete')
    return len(chunks)


async def import_documents(db, actor, documents, manifest, receipt, store):
    actor = await require_fresh_identity(actor, session=db)
    require_permission(actor, 'knowledge', 'write')
    await db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))'),
        {'key': 'public-knowledge:' + actor.tenant_id})
    rows = []
    for document in documents:
        source = await db.scalar(select(KnowledgeSource).where(KnowledgeSource.tenant_id == actor.tenant_id,
            KnowledgeSource.name == document['title']))
        if source is not None:
            existing = list((await db.scalars(select(KnowledgeVersion).where(
                KnowledgeVersion.source_id == source.id))).all())
            if len(existing) != 1 or existing[0].content_hash != document['sha256']:
                raise ValueError('existing_source_conflict')
            version = existing[0]
            if (version.status != 'published' or version.parse_status != 'READY' or version.effective_at or
                version.expire_at or version.permission_tags != actor.depts):
                raise ValueError('existing_version_state_conflict')
            binding = await db.scalar(select(OAKnowledgeBinding).where(
                OAKnowledgeBinding.tenant_id == actor.tenant_id, OAKnowledgeBinding.source_id == source.id))
            if (binding is None or binding.status != 'active' or binding.access_scope != 'department' or
                binding.department_id != actor.depts[0] or binding.owner_id != actor.user_id or
                binding.version_rule.get('dataset_id') != manifest['dataset_id']):
                raise ValueError('existing_binding_conflict')
            action = 'reused'
        else:
            version = await versions.create_version(db, source_name=document['title'],
                content=document['content'], filename=document['filename'], permission_tags=actor.depts,
                owner_id=actor.user_id, tenant_id=actor.tenant_id, store=store, content_type='text/markdown')
            await scopes.create_binding(db, actor=actor, source_id=version.source_id, owner_id=actor.user_id,
                department_id=actor.depts[0], access_scope='department', version_rule={
                    'dataset_id': manifest['dataset_id'], 'provenance': 'public_external_reference',
                    'source_ids': document['source_ids'], 'license': manifest['license'],
                    'source_snapshot_checked_at': receipt['checked_at'], 'adopted_company_policy': False})
            await versions.publish_version(db, version.id)
            await scopes.record_audit(db, actor=actor, resource='knowledge', action='knowledge.imported',
                object_type='knowledge_version', object_id=str(version.id), source_type='knowledge',
                source_id=str(version.source_id), detail={'dataset_id': manifest['dataset_id'],
                    'content_sha256': document['sha256'], 'source_ids': document['source_ids'],
                    'provenance': 'public_external_reference', 'adopted_company_policy': False})
            action = 'created'
        count = await inspect_version(db, version, document, store, get_settings().embedding_dim)
        rows.append(dict(id=document['id'], source_id=str(version.source_id), version_id=str(version.id),
            title=document['title'], version=version.version, status=version.status, action=action,
            chunks=count, sha256=document['sha256'], access_scope='department'))
    await require_fresh_identity(actor, session=db)
    await db.commit()
    return rows


async def run(options):
    manifest, documents = load_corpus()
    if options.fetch_sources:
        receipt = await fetch_sources(manifest)
        print(json.dumps({'source_snapshots': len(receipt['sources']), 'license_verified': True}))
    if not options.apply:
        print(json.dumps({'documents': len(documents), 'blocks': sum(d['block_count'] for d in documents),
                          'database_written': False, 'evaluation_answers_indexed': False}))
        return
    settings = get_settings()
    if settings.embedding_provider != 'ark' or settings.llm_provider == 'mock':
        raise ValueError('real_models_required')
    receipt = verified_receipt(manifest)
    async with async_session_factory() as db:
        await (await db.connection()).run_sync(assert_schema_current)
        actor = await actor_for_import(db, options.username)
        set_current_user(actor)
        rows = await import_documents(db, actor, documents, manifest, receipt,
            LocalObjectStore(settings.knowledge_storage_dir))
        report = dict(checked_at=datetime.now(timezone.utc).isoformat(), dataset_id=manifest['dataset_id'],
            tenant_id=actor.tenant_id, department_id=actor.depts[0], documents=rows,
            embedding_dimension=settings.embedding_dim, evaluation_answers_indexed=False,
            department_pilot='UNVERIFIED', production_acceptance=False)
        OUTPUT.mkdir(parents=True, exist_ok=True)
        target = OUTPUT / ('import-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'report': str(target), 'published': len(rows), 'chunks': sum(r['chunks'] for r in rows),
            'created': sum(r['action'] == 'created' for r in rows), 'reused': sum(r['action'] == 'reused' for r in rows)}))


async def main_async(options):
    try:
        await run(options)
        return 0
    except Exception as error:
        # Never echo network bodies, connection strings, credentials or raw exceptions.
        print(json.dumps({'error': 'public_knowledge_import_failed', 'category': type(error).__name__}))
        return 1
    finally:
        set_current_user(None)
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch-sources', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--username', default='oa_admin')
    sys.exit(asyncio.run(main_async(parser.parse_args())))
