"""Source-grounded project-document evaluation, distinct from business UAT.

Uses the application's actual schema, clients and embedding model. No DB writes,
knowledge publishing, model-as-judge scoring or department acceptance claims.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.llm.compatible import CompatibleLLM
from app.llm.embedding import ArkEmbedding
from app.llm.intent import intent_messages
from app.llm.schemas import IntentClassification, TicketExtraction

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'output' / 'business-acceptance-private'


def failure_code(client):
    attempts = client.last_attempts
    status = attempts[-1]['status'] if attempts else None
    return status if status in {'unavailable', 'rejected', 'invalid_output'} else 'generation_failed'


def documents():
    path = ROOT / 'OA智能体管理系统-正式PRD-V1.4.md'
    content = path.read_text(encoding='utf-8')
    sections = []
    for index, section in enumerate(content.split('\n### ')):
        if any(marker in section[:100] for marker in ('5.1 ', '5.4 ', '5.5 ')):
            sections.append(dict(id=str(index), title=section.splitlines()[0], content=section))
    if len(sections) != 3:
        raise ValueError('source_sections_missing')
    return path, content, sections


async def evaluate():
    settings = get_settings()
    if settings.llm_provider == 'mock' or settings.embedding_provider != 'ark':
        raise ValueError('real_models_required')
    path, content, sections = documents()
    cases = [
        ('login', '账号连续登录失败几次会锁定，锁定多久？', '5.1 ', [['5', '五'], ['15', '十五']]),
        ('backup', '项目要求多长时间备份，多久恢复演练，恢复目标是多少？', '5.4 ',
         [['每日', '每天'], ['每周', '一周'], ['15', '十五']]),
        ('announcement', '通知公告需要哪些功能？', '5.5 ', [['发布'], ['撤回'], ['已读'], ['部门']]),
    ]
    vectors = await ArkEmbedding().embed([item['content'] for item in sections] + [case[1] for case in cases])
    def cosine(a, b):
        return sum(x*y for x,y in zip(a,b)) / ((sum(x*x for x in a)*sum(y*y for y in b)) ** .5)
    retrieval = []
    for offset, (key, question, expected, _) in enumerate(cases):
        scores = [cosine(vectors[len(sections)+offset], vector) for vector in vectors[:len(sections)]]
        best = max(range(len(scores)), key=scores.__getitem__)
        retrieval.append(dict(case=key, top_section=sections[best]['title'], score=round(scores[best],4),
                              expected_section=expected, correct=expected in sections[best]['title']))
    providers = [settings.llm_provider]
    if settings.llm_fallback_provider not in {'none', settings.llm_provider}:
        providers.append(settings.llm_fallback_provider)
    results = []
    for provider in providers:
        for key, question, section, terms in cases:
            evidence = next(item['content'] for item in sections if section in item['title'])
            started = monotonic()
            client = CompatibleLLM(provider)
            try:
                response = await client.complete([
                    {'role':'system','content':'仅依据给定知识片段回答，并保持可追溯来源。'},
                    {'role':'user','content':f'知识片段：{evidence}\n问题：{question}'}], max_tokens=500)
                answer = response['choices'][0]['message']['content']
                results.append(dict(provider=provider, case=key, kind='grounded_answer', answer=answer,
                    lexical_checks_pass=all(any(term in answer for term in group) for group in terms),
                    manual_semantic_review='PENDING', seconds=round(monotonic()-started,3), usage=client.last_usage))
            except Exception:
                results.append(dict(provider=provider, case=key, kind='grounded_answer', error=failure_code(client),
                                    seconds=round(monotonic()-started,3)))
        for key, question, expected in [
            ('leave_intent','我想申请明天一天的年假，怎么提交请假申请？','leave'),
            ('faq_intent','公司的请假制度是什么，申请前需要哪些材料？','faq'),
            ('advance_notice_intent','年假申请需要提前多久？','faq'),
            ('ticket_intent','我的办公电脑无法开机，请帮我报修。','ticket'),
            ('human_intent','请帮我转人工客服。','human'),
            ('greeting_intent','你好','unknown')]:
            client = CompatibleLLM(provider)
            started = monotonic()
            try:
                result = await client.structured(intent_messages(question), IntentClassification,
                                                  max_tokens=160)
                results.append(dict(provider=provider,case=key,kind='intent',result=result.model_dump(),
                    correct=result.intent==expected and (expected=='unknown' or result.confidence>=.6),
                    seconds=round(monotonic()-started,3)))
            except Exception:
                results.append(dict(provider=provider,case=key,kind='intent',error=failure_code(client)))
        client = CompatibleLLM(provider)
        try:
            result = await client.structured([{'role':'user','content':
                '核验本项目业务邮件与企业微信群通知，由本人核对收件结果。影响范围仅本人，优先级中。'}],
                TicketExtraction,max_tokens=300)
            results.append(dict(provider=provider,case='actual_acceptance_request',kind='ticket_extraction',
                result=result.model_dump(),correct=result.priority=='medium' and bool(result.summary)))
        except Exception:
            results.append(dict(provider=provider,case='actual_acceptance_request',kind='ticket_extraction',error=failure_code(client)))
        client = CompatibleLLM(provider)
        try:
            response=await client.complete([{'role':'system','content':'仅依据给定知识片段回答，并保持可追溯来源。'},
                {'role':'user','content':f"知识片段：{sections[0]['content']}\n问题：本公司的差旅住宿报销上限是每晚多少元？"}],max_tokens=180)
            answer=response['choices'][0]['message']['content']
            results.append(dict(provider=provider,case='missing_evidence',kind='abstention',answer=answer,
                manual_semantic_review='PENDING'))
        except Exception:
            results.append(dict(provider=provider,case='missing_evidence',kind='abstention',error=failure_code(client)))
    return dict(checked_at=datetime.now(timezone.utc).isoformat(), source=path.name,
        source_sha256=hashlib.sha256(content.encode()).hexdigest(), source_kind='actual_project_requirements',
        embedding_dimension=settings.embedding_dim, retrieval=retrieval, results=results,
        scope='Client/schema and source-grounded component evaluation; not UI/RAG workflow UAT.',
        business_policy_quality='UNVERIFIED', department_pilot='UNVERIFIED', production_acceptance=False)


def automated_failures(report):
    failures = [f"retrieval:{item['case']}" for item in report['retrieval'] if not item['correct']]
    for item in report['results']:
        if ('error' in item or item.get('correct') is False or item.get('lexical_checks_pass') is False):
            failures.append(f"{item['provider']}:{item['case']}")
    return failures


def main():
    try:
        report=asyncio.run(evaluate())
    except Exception:
        print(json.dumps({'error':'quality_evaluation_incomplete','production_acceptance':False}))
        return 1
    OUTPUT.mkdir(parents=True,exist_ok=True)
    report['automated_failures'] = automated_failures(report)
    report['manual_review_required'] = True
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target=OUTPUT/('model-quality-'+stamp+'.json')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(target),'retrieval':report['retrieval'],'cases':len(report['results']),
        'errors':sum('error' in item for item in report['results']),
        'automated_failures':report['automated_failures'],'manual_review_required':True,
        'production_acceptance':False},ensure_ascii=True))
    return 1 if report['automated_failures'] else 0


if __name__=='__main__':
    sys.exit(main())
