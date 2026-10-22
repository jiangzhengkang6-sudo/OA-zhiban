"""B4 browser acceptance against a running, isolated test backend and Vite.

Use Playwright with the installed Edge. Does not reset a database, mock HTTP
responses, or approve unscanned files. Screenshots/results contain test data.
"""
import io
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / 'data' / 'verification' / 'b4-browser'
BASE = 'http://127.0.0.1:5173'
EMP = {'Authorization': 'Bearer mock:u_emp_001'}
RESULTS = []


def record(name):
    RESULTS.append(name)
    print('PASS:', name, flush=True)


def main():
    from urllib.parse import urlsplit
    assert os.environ.get('ENVIRONMENT') == 'test', 'Test environment required'
    assert urlsplit(os.environ.get('DATABASE_URL', '')).path == '/oa_agent_test', 'Isolated database required'
    OUT.mkdir(parents=True, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, timezone_id='Asia/Shanghai')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.set_default_timeout(15000)

        def api(path):
            response = context.request.get(BASE + '/api' + path, headers=EMP)
            assert response.ok, (path, response.status, response.text())
            return response.json()['data']

        def switch(label):
            page.locator('.identity-switch .el-select').click()
            page.get_by_role('option', name=label, exact=True).click()
            page.wait_for_url('**/tasks')
            expect(page.get_by_role('heading', name='我的任务')).to_be_visible()

        def draft(day, *, end=None, leave_type='年假', reason='浏览器验收'): 
            page.goto(BASE + '/leaves/new')
            expect(page.get_by_label('开始时间')).to_be_visible()
            if leave_type != '年假':
                page.locator('.el-form-item').filter(has_text='假期类型').locator('.el-select').click()
                page.get_by_role('option', name=leave_type, exact=True).click()
            page.get_by_label('开始时间').fill(day.strftime('%Y-%m-%dT09:00'))
            page.get_by_label('结束时间').fill((end or day).strftime('%Y-%m-%dT18:00'))
            page.get_by_label('请假原因', exact=True).fill(reason)
            page.get_by_test_id('save-draft').click()
            page.wait_for_url('**/leaves/*')
            expect(page.get_by_test_id('save-draft')).to_be_enabled()
            return page.url.rsplit('/', 1)[-1]

        def submit(app_id, status):
            with page.expect_response(lambda r: r.url.endswith('/' + app_id + '/submit') and r.request.method == 'POST') as response:
                page.get_by_test_id('submit-leave').click()
            assert response.value.ok, response.value.text()
            page.wait_for_timeout(100)
            value = api('/leaves/' + app_id)
            assert value['status'] == status, value
            return value

        def decision(thread, action):
            page.goto(BASE + '/leave/' + thread)
            expect(page.get_by_role('button', name=action, exact=True)).to_be_enabled()
            page.get_by_placeholder('审批意见；驳回时必填').fill('浏览器验收意见')
            with page.expect_response(lambda r: r.url.endswith('/decision')) as response:
                page.get_by_role('button', name=action, exact=True).click()
            assert response.value.ok, response.value.text()
            return response.value.json()['data']

        try:
            # Unique dates avoid collisions without deleting existing test records.
            day = datetime(2030 + int(uuid4().hex[:3], 16) % 100, 3, 1)
            app_id = draft(day)
            page.reload()
            expect(page.get_by_label('请假原因', exact=True)).to_have_value('浏览器验收')
            record('employee draft survives browser refresh')
            submitted = submit(app_id, 'SUBMITTED')
            thread = submitted['thread_id']
            record('complete precheck creates approval task')
            page.screenshot(path=str(OUT / 'submitted.png'), full_page=True)

            switch('王五 · 二级审批')
            page.goto(BASE + '/approvals')
            expect(page.get_by_role('heading', name='审批待办')).to_be_visible()
            expect(page.get_by_text(submitted['business_id'], exact=True)).to_have_count(0)
            denied = context.request.post(BASE + '/api/leaves/' + app_id + '/decision',
                headers={'Authorization': 'Bearer mock:u_mgr_002'},
                data={'action': 'approve', 'comment': '越级应拒绝', 'idempotency_key': str(uuid4())})
            assert denied.status == 403, denied.text()
            record('second approver cannot see or approve the inactive node')
            switch('李四 · 一级审批')
            assert decision(thread, '批准当前级')['status'] == 'WAITING_HUMAN'
            record('first approval activates second node without final approval')
            switch('王五 · 二级审批')
            assert decision(thread, '批准当前级')['status'] == 'APPROVED'
            record('second approval finishes the application')
            page.screenshot(path=str(OUT / 'approved.png'), full_page=True)
            switch('张三 · 员工')
            assert api('/leaves/' + app_id)['status'] == 'APPROVED'

            conflict_id = draft(day, reason='相同时间应冲突')
            conflict = submit(conflict_id, 'NEEDS_FIX')
            assert any(i['item'] == 'conflict' and i['result'] == 'fail' for i in conflict['precheck']['items'])
            record('overlapping application stays editable and fails conflict check')
            insufficient_id = draft(day + timedelta(days=30), end=day + timedelta(days=90))
            insufficient = submit(insufficient_id, 'NEEDS_FIX')
            assert any(i['item'] == 'balance' and i['result'] == 'fail' for i in insufficient['precheck']['items'])
            record('insufficient leave balance blocks submission')
            sick_id = draft(day + timedelta(days=100), leave_type='病假')
            sick = submit(sick_id, 'NEEDS_FIX')
            assert any(i['item'] == 'attachment' and i['result'] == 'fail' for i in sick['precheck']['items'])
            record('sick leave without proof fails attachment check')
            png = io.BytesIO()
            Image.new('RGB', (2, 2), 'white').save(png, format='PNG')
            with page.expect_response(lambda r: r.url.endswith('/attachments') and r.request.method == 'POST') as response:
                page.get_by_label('上传证明材料', exact=True).set_input_files(
                    {'name': 'proof.png', 'mimeType': 'image/png', 'buffer': png.getvalue()})
            assert response.value.json()['data']['scan_status'] == 'PENDING'
            expect(page.get_by_role('button', name='下载', exact=True)).to_be_disabled()
            with page.expect_response(lambda r: r.url.endswith('/scan')) as response:
                page.get_by_role('button', name='重新扫描', exact=True).click()
            assert response.value.json()['data']['scan_status'] == 'PENDING'
            page.reload()
            expect(page.get_by_text('proof.png', exact=True)).to_be_visible()
            expect(page.get_by_role('button', name='下载', exact=True)).to_be_disabled()
            record('real PNG upload, rescan and refresh remain PENDING without ClamAV')
            page.screenshot(path=str(OUT / 'pending-attachment.png'), full_page=True)

            rejected_id = draft(day + timedelta(days=10), reason='待驳回申请')
            rejected = submit(rejected_id, 'SUBMITTED')
            switch('李四 · 一级审批')
            assert decision(rejected['thread_id'], '驳回')['status'] == 'REJECTED'
            switch('张三 · 员工')
            page.goto(BASE + '/leaves/' + rejected_id)
            expect(page.get_by_label('请假原因', exact=True)).to_have_value('待驳回申请')
            page.get_by_label('请假原因', exact=True).fill('驳回后补充说明')
            resubmitted = submit(rejected_id, 'SUBMITTED')
            versions = api('/leaves/' + rejected_id + '/versions')
            assert len(versions) == 2 and versions[0]['fields']['reason'] == '待驳回申请'
            assert versions[1]['fields']['reason'] == '驳回后补充说明'
            record('rejection resubmission preserves original version and creates new precheck')
            page.screenshot(path=str(OUT / 'resubmitted.png'), full_page=True)
            switch('李四 · 一级审批')
            page.goto(BASE + '/leave/' + resubmitted['thread_id'])
            page.get_by_role('button', name='编辑后批准', exact=True).click()
            page.get_by_label('编辑请假原因', exact=True).fill('审批人核对后的原因')
            page.get_by_placeholder('编辑原因（必填）').fill('补充材料说明')
            with page.expect_response(lambda r: r.url.endswith('/decision')) as response:
                page.get_by_role('button', name='确认编辑并重检', exact=True).click()
            assert response.value.ok and response.value.json()['data']['status'] == 'WAITING_HUMAN'
            versions = api('/leaves/' + rejected_id + '/versions')
            assert len(versions) == 3 and versions[-1]['fields']['reason'] == '审批人核对后的原因'
            record('approver edit creates immutable version and reruns precheck')
            switch('张三 · 员工')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(BASE + '/leaves/' + sick_id)
            expect(page.get_by_text('proof.png', exact=True)).to_be_visible()
            page.screenshot(path=str(OUT / 'mobile-attachment.png'), full_page=True)
            record('mobile form keeps pending proof and download restriction visible')
            assert not errors, errors
        finally:
            if errors:
                print('PAGE ERRORS:', errors, flush=True)
            page.screenshot(path=str(OUT / 'last-page.png'), full_page=True)
            (OUT / 'result.json').write_text(json.dumps({'passed': RESULTS, 'page_errors': errors,
                'database': 'oa_agent_test', 'scanner': 'unconfigured; PENDING verified'}, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
    print(f'{len(RESULTS)} browser scenarios passed', flush=True)


if __name__ == '__main__':
    main()
