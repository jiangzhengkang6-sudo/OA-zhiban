"""Evaluate actual published evidence through the persistent FAQ graph and services."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import set_current_user
from app.db.session import async_session_factory, engine
from app.graph.graph_service import runtime
from app.models.knowledge_source import KnowledgeSource
from app.services import thread_service
from scripts.import_public_company_knowledge import CORPUS, OUTPUT, actor_for_import, load_corpus


def automatic_check(case, answer, source_ids, expected_ids, next_action):
    if next_action == 'human':
        return {'accepted': case['kind'] == 'injection', 'safe_handoff': True, 'outcome': 'human',
                'source_hit': False, 'lexical_checks_pass': None}
    lexical = all(any(term.casefold() in answer.casefold() for term in group) for group in case['terms'])
    hit = bool(source_ids & expected_ids)
    required_hit = bool(case['documents']) and case['kind'] in {'answer', 'scenario'}
    unsafe = bool(case.get('forbidden_claim') and case['forbidden_claim'] in answer)
    accepted = bool(answer) and next_action == 'answered' and lexical and (hit or not required_hit) and not unsafe
    return {'accepted': accepted, 'outcome': next_action, 'source_hit': hit,
            'lexical_checks_pass': lexical, 'manual_semantic_review': 'PENDING'}


async def evaluate(options):
    manifest, documents = load_corpus()
    cases = json.loads((CORPUS / 'questions.json').read_text(encoding='utf-8'))
    settings = get_settings()
    if settings.llm_provider == 'mock' or settings.embedding_provider != 'ark':
        raise ValueError('real_models_required')
    async with async_session_factory() as db:
        actor = await actor_for_import(db, options.username)
        source_ids = {}
        for doc in documents:
            identifier = await db.scalar(select(KnowledgeSource.id).where(
                KnowledgeSource.tenant_id == actor.tenant_id, KnowledgeSource.name == doc['title']))
            if identifier is None:
                raise ValueError('published_corpus_required')
            source_ids[doc['id']] = str(identifier)
    set_current_user(actor)
    # Initialize only the graph checkpointer; do not launch HTTP lifespan/schedulers.
    await runtime.initialize()
    results = []
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = OUTPUT / ('faq-' + stamp + '.json')
    report = dict(checked_at=datetime.now(timezone.utc).isoformat(), dataset_id=manifest['dataset_id'],
        provider=settings.llm_provider, fallback=settings.llm_fallback_provider,
        embedding_dimension=settings.embedding_dim, results=results, manual_review_required=True,
        scope='Formal service and visible detail projection, persistent graph, database retrieval, real embedding and text; no browser UI or department trial.',
        production_acceptance=False)
    for case in cases:
        started = monotonic()
        row = dict(case=case['id'], kind=case['kind'], question=case['question'],
                   reference_answer=case['reference_answer'], manual_semantic_review='PENDING')
        try:
            async with async_session_factory() as db:
                thread = await thread_service.create_thread(db, scene='faq',
                    business_id=('public-uat-' + stamp + '-' + case['id']))
                await db.commit()
                row['thread_id'] = str(thread.id)
                _, status, next_action = await thread_service.send_message(db, thread, case['question'],
                    idempotency_key='public-corpus-' + case['id'])
                await db.commit()
                detail = await thread_service.build_thread_detail(db, thread)
            answer = detail.answer or {}
            row.update(answer=answer.get('answer', ''), sources=answer.get('sources', []),
                       confidence=answer.get('confidence'), status=status, next_action=detail.next_action,
                       send_next_action=next_action, visible_projection_checked=True)
            found = {item.get('source_id') for item in row['sources']}
            expected = {source_ids[key] for key in case['documents']}
            row.update(automatic_check(case, row['answer'], found, expected, detail.next_action))
        except Exception as error:
            row.update(error=type(error).__name__, accepted=False)
        row['seconds'] = round(monotonic() - started, 3)
        results.append(row)
        report['automatic_failures'] = [item['case'] for item in results if not item['accepted']]
        OUTPUT.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'case': case['id'], 'accepted': row['accepted'], 'seconds': row['seconds']}), flush=True)
    print(json.dumps({'report': str(target), 'cases': len(results), 'automatic_failures': report['automatic_failures'],
                      'manual_review_required': True, 'production_acceptance': False}))
    return 1 if report['automatic_failures'] else 0


async def main(options):
    try:
        return await evaluate(options)
    except Exception as error:
        print(json.dumps({'error': 'public_faq_evaluation_failed', 'category': type(error).__name__}))
        return 1
    finally:
        set_current_user(None)
        await runtime.close()
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='oa_admin')
    sys.exit(asyncio.run(main(parser.parse_args())))
