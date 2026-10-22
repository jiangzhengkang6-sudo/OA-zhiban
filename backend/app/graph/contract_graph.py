"""Four explicit nodes; only validated state is persisted by the resource service."""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from copy import deepcopy
from ..services.contract_rules import check_rules, RULE_VERSION, RULES
from ..services.contract_deepagents import analyze_long_contract


class ContractState(TypedDict, total=False):
    parsed: dict
    clauses: list
    risks: list
    analysis: dict
    draft: dict
    node_trace: list
    rule_version: str
    rule_snapshot: list


def build_contract_graph():
    graph = StateGraph(ContractState)

    def extract(state):
        return {'clauses':state['parsed']['paragraphs'], 'node_trace':['extract_clauses'],
            'rule_version': RULE_VERSION, 'rule_snapshot': deepcopy(RULES)}

    def rules(state):
        return {'risks':check_rules(state['parsed'], rules=state['rule_snapshot'], rule_version=state['rule_version']),
            'node_trace':state['node_trace'] + ['check_rules']}

    async def analyze(state):
        analysis = await analyze_long_contract(state['parsed']) if len(state['parsed']['text']) > 8000 else dict(engine='deterministic',model_calls=0,usage=[],observations=[])
        return {'analysis':analysis,'node_trace':state['node_trace'] + ['analyze_risks']}

    def summarize(state):
        draft = dict(rule_version=state['rule_version'], risks=state['risks'], observations=state['analysis']['observations'],
            analysis_engine=state['analysis']['engine'], summary='四类演示规则检查已完成，请指定复核人逐项核对。此结果无法律批准效力。',
            source_hash=state['parsed']['sha256'])
        return {'draft':draft, 'node_trace':state['node_trace'] + ['summarize']}

    graph.add_node('extract_clauses',extract)
    graph.add_node('check_rules',rules)
    graph.add_node('analyze_risks',analyze)
    graph.add_node('summarize',summarize)
    def entry(state):
        completed = state.get('node_trace',[])
        for node in ['extract_clauses','check_rules','analyze_risks','summarize']:
            if node not in completed:
                return node
        return END
    graph.add_conditional_edges(START,entry)
    graph.add_edge('extract_clauses','check_rules')
    graph.add_edge('check_rules','analyze_risks')
    graph.add_edge('analyze_risks','summarize')
    graph.add_edge('summarize',END)
    return graph.compile()


contract_graph = build_contract_graph()
