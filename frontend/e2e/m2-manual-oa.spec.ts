import { test, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'

const accounts = JSON.parse(readFileSync('../data/verification/m2/preview-credentials.json', 'utf8'))

async function login(page: import('@playwright/test').Page) {
  await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill('m2_admin')
  await page.getByLabel('密码', { exact: true }).fill(accounts.m2_admin.password)
  const response=page.waitForResponse(r=>r.url().endsWith('/api/auth/login')&&r.request().method()==='POST')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  expect((await response).status()).toBe(200)
  await expect(page).toHaveURL(/\/oa\/leaves$/)
}

type Page=import('@playwright/test').Page
const tokens=new WeakMap<Page,Promise<string>>()
async function signIn(page:Page,username:string){
  page.on('response',response=>{
    if(response.ok()&&/\/api\/auth\/(login|refresh)$/.test(response.url()))tokens.set(page,response.json().then(body=>body.data.access_token))
  })
  await page.goto('/login')
  await page.getByLabel('账号',{exact:true}).fill(username)
  await page.getByLabel('密码',{exact:true}).fill(accounts[username].password)
  const pending=page.waitForResponse(r=>r.url().endsWith('/api/auth/login')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'登录',exact:true}).click()
  const response=await pending;expect(response.status()).toBe(200)
  tokens.set(page,Promise.resolve((await response.json()).data.access_token))
  await expect(page).toHaveURL(/\/oa\/leaves$/)
}
async function api(page:Page,path:string,data?:unknown){
  const response=await page.request.fetch('/api/oa/'+path,{method:data===undefined?'GET':'POST',headers:{Authorization:'Bearer '+await tokens.get(page)},...(data===undefined?{}:{data})})
  expect(response.status(),path+': '+(response.ok()?'':await response.text())).toBe(200)
  return (await response.json()).data
}
async function createAndSubmit(page:Page,name:string){
  const workflow=(await api(page,'workflows?available=true')).find((w:any)=>w.name===name);expect(workflow).toBeTruthy()
  const used=new Set((await api(page,'leaves')).flatMap((r:any)=>[r.fields.start_date,r.fields.end_date]))
  let date=''
  for(let i=0;i<350;i++){const next=new Date(Date.UTC(2027,0,1+i)).toISOString().slice(0,10);if(!used.has(next)){date=next;break}}
  expect(date).toBeTruthy();await page.goto('/oa/leaves/new')
  await page.getByLabel('请假流程',{exact:true}).selectOption(workflow.id)
  await page.getByLabel('开始日期',{exact:true}).fill(date);await page.getByLabel('结束日期',{exact:true}).fill(date)
  await page.getByLabel('请假事由',{exact:true}).fill('浏览器人工流程验收')
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/oa/leaves')&&r.request().method()==='POST')
  await page.getByTestId('save-leave').click()
  const response=await saved;expect(response.status(),await response.text()).toBe(200)
  const leave=(await response.json()).data.result
  await expect(page).toHaveURL(new RegExp('/oa/leaves/'+leave.id+'$'))
  await expect(page.getByTestId('submit-leave')).toBeEnabled()
  const submitted=page.waitForResponse(r=>r.url().endsWith('/submit')&&r.request().method()==='POST')
  await page.getByTestId('submit-leave').click();expect((await submitted).status()).toBe(200)
  await expect(page.getByRole('button',{name:'撤回申请',exact:true})).toBeVisible();return leave
}
async function decide(page:Page,businessNo:string,action='approve'){
  await page.goto('/oa/approvals')
  await page.getByRole('row').filter({has:page.getByRole('cell',{name:businessNo,exact:true})}).getByRole('button',{name:'办理',exact:true}).click()
  await page.getByLabel('审批决定',{exact:true}).selectOption(action)
  if(action!=='approve')await page.getByLabel('处理意见',{exact:true}).fill('请补充准确事由')
  const result=page.waitForResponse(r=>r.url().endsWith('/decisions')&&r.request().method()==='POST')
  await page.getByTestId('decide-node').click();const response=await result;expect(response.status(),await response.text()).toBe(200)
  await expect(page.getByTestId('decide-node')).toHaveCount(0)
}
async function confirmAction(page:Page,name:string,endpoint:string){
  await page.getByRole('button',{name,exact:true}).click()
  const result=page.waitForResponse(r=>r.url().endsWith('/'+endpoint)&&r.request().method()==='POST')
  await page.getByRole('button',{name:'确定',exact:true}).click()
  const response=await result;expect(response.status(),await response.text()).toBe(200)
  await expect(page.getByRole('dialog')).toBeHidden()
}

test('桌面保存发布含抄送和分支的流程与显式调整额度',async({page})=>{
  await signIn(page,'m2_admin');await page.goto('/oa/workflows');await page.getByTestId('new-workflow').click()
  await page.getByLabel('流程名称',{exact:true}).fill('浏览器流程 '+Date.now())
  await page.getByTestId('add-cc').click();await page.getByTestId('add-branch').click()
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/oa/workflows')&&r.request().method()==='POST')
  await page.getByTestId('save-workflow').click();const response=await saved;expect(response.status(),await response.text()).toBe(200)
  const id=(await response.json()).data.id
  const published=page.waitForResponse(r=>r.url().endsWith('/publish')&&r.request().method()==='POST')
  await page.getByRole('button',{name:'发布当前版本',exact:true}).click();expect((await published).status()).toBe(200)
  const workflow=(await api(page,'workflows')).find((w:any)=>w.id===id)
  expect(workflow.published_version).toBe(1);expect(workflow.definition.nodes.map((n:any)=>n.kind)).toEqual(['approval','cc','branch','end'])
  await page.screenshot({path:'../data/verification/m2/workflow-editor-desktop.png',fullPage:true})
  await page.goto('/oa/balances');await page.getByRole('button',{name:'调整额度',exact:true}).click()
  await page.getByLabel('调整原因',{exact:true}).fill('浏览器额度核验')
  const adjusted=page.waitForResponse(r=>r.url().endsWith('/balances/adjust')&&r.request().method()==='POST')
  await page.getByTestId('save-balance').click();expect((await adjusted).status()).toBe(200)
  await expect(page.getByRole('dialog')).toBeHidden()
})
test('员工驳回重提、批准与归档，直连管理接口拒绝',async({browser})=>{
  const employee=await browser.newPage(),manager=await browser.newPage()
  try{
    await signIn(employee,'m2_employee');await signIn(manager,'m2_manager')
    await expect(employee.getByRole('menuitem',{name:'流程配置'})).toHaveCount(0)
    expect((await employee.request.get('/api/oa/administration/instances',{headers:{Authorization:'Bearer '+await tokens.get(employee)}})).status()).toBe(403)
    const leave=await createAndSubmit(employee,'普通请假');await decide(manager,leave.business_no,'reject')
    await employee.reload();await employee.getByLabel('请假事由',{exact:true}).fill('按审批意见修订事由')
    const changed=employee.waitForResponse(r=>r.url().endsWith('/'+leave.id)&&r.request().method()==='PUT')
    await employee.getByTestId('save-leave').click();expect((await changed).status()).toBe(200)
    await expect(employee.getByTestId('submit-leave')).toBeEnabled()
    const submitted=employee.waitForResponse(r=>r.url().endsWith('/submit')&&r.request().method()==='POST')
    await employee.getByTestId('submit-leave').click();expect((await submitted).status()).toBe(200)
    await decide(manager,leave.business_no);await employee.reload()
    await expect(employee.getByRole('button',{name:'归档',exact:true})).toBeVisible();await confirmAction(employee,'归档','archive')
    await expect(employee.getByRole('button',{name:'归档',exact:true})).toHaveCount(0)
    const result=await api(employee,'leaves/'+leave.id)
    expect(result.state).toBe('APPROVED');expect(result.versions).toHaveLength(2);expect(result.archived_at).toBeTruthy()
    await employee.screenshot({path:'../data/verification/m2/leave-history-desktop.png',fullPage:true})
  }finally{await employee.close();await manager.close()}
})
test('会签需两人、或签一人结束，转交后旧人不能办理',async({browser})=>{
  const employee=await browser.newPage(),manager=await browser.newPage(),reviewer=await browser.newPage(),admin=await browser.newPage()
  try{
    for(const [page,name] of [[employee,'m2_employee'],[manager,'m2_manager'],[reviewer,'m2_reviewer'],[admin,'m2_admin']] as [Page,string][])await signIn(page,name)
    const all=await createAndSubmit(employee,'会签请假');await decide(manager,all.business_no)
    expect((await api(employee,'leaves/'+all.id)).state).toBe('IN_REVIEW');await decide(reviewer,all.business_no)
    expect((await api(employee,'leaves/'+all.id)).state).toBe('APPROVED')
    const any=await createAndSubmit(employee,'或签请假');await decide(manager,any.business_no)
    expect((await api(employee,'leaves/'+any.id)).state).toBe('APPROVED')
    expect((await api(reviewer,'approvals?kind=pending')).some((n:any)=>n.business_no===any.business_no)).toBe(false)
    const transfer=await createAndSubmit(employee,'普通请假')
    const stale=(await api(manager,'approvals?kind=pending')).find((n:any)=>n.business_no===transfer.business_no)
    const staleNode=await api(manager,'approvals/nodes/'+stale.node_id)
    await admin.goto('/oa/administration');await admin.getByRole('row').filter({has:admin.getByRole('cell',{name:transfer.business_no,exact:true})}).click()
    await admin.locator('.el-select').filter({has:admin.getByRole('combobox',{name:'替代人员 1',exact:true})}).click();await admin.getByRole('option',{name:'复核专员',exact:true}).click()
    await admin.getByLabel('操作理由',{exact:true}).fill('人工转交验收')
    const moved=admin.waitForResponse(r=>r.url().endsWith('/transfer')&&r.request().method()==='POST')
    await admin.getByRole('button',{name:'转交',exact:true}).click();expect((await moved).status()).toBe(200)
    const old=await manager.request.post('/api/oa/approvals/nodes/'+stale.node_id+'/decisions',{headers:{Authorization:'Bearer '+await tokens.get(manager)},data:{operation_id:crypto.randomUUID(),expected_revision:staleNode.revision,action:'approve'}})
    expect([403,409]).toContain(old.status());await decide(reviewer,transfer.business_no)
    expect((await api(employee,'leaves/'+transfer.id)).state).toBe('APPROVED');expect((await api(admin,'administration/reconciliation')).ok).toBe(true)
  }finally{for(const page of [employee,manager,reviewer,admin])await page.close()}
})
test('手机员工提交、撤回、归档与额度弹窗边界',async({page})=>{
  await page.setViewportSize({width:390,height:844});await signIn(page,'m2_employee')
  const leave=await createAndSubmit(page,'普通请假');await confirmAction(page,'撤回申请','withdraw')
  await expect(page.getByRole('button',{name:'归档',exact:true})).toBeVisible();await confirmAction(page,'归档','archive')
  expect((await api(page,'leaves/'+leave.id)).state).toBe('CANCELLED')
  expect(await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
  await page.locator('main.manual-oa > section.oa-section').screenshot({path:'../data/verification/m2/leave-mobile.png'})
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await signIn(page,'m2_admin');await page.goto('/oa/balances')
  await page.getByRole('button',{name:'调整额度',exact:true}).click()
  await expect(page.getByTestId('save-balance')).toBeVisible()
  await page.screenshot({path:'../data/verification/m2/balance-dialog-mobile.png',fullPage:true,animations:'disabled'})
  const bounds=await page.getByRole('dialog').boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(391)
})

test('桌面人工 OA 入口和结构化管理页面', async ({ page }) => {
  await login(page)
  await expect(page.getByText('OA 工作平台', { exact: true })).toBeVisible()
  await page.goto('/oa/leaves')
  await expect(page.getByRole('heading', { name: '我的申请', exact: true })).toBeVisible()
  await page.goto('/oa/workflows')
  await expect(page.getByRole('heading', { name: '流程配置', exact: true })).toBeVisible()
  await expect(page.locator('textarea')).toHaveCount(0)
  await page.screenshot({ path: '../data/verification/m2/manual-oa-desktop.png', fullPage: true })
})

test('手机人工 OA 页面不横向溢出并可显示额度管理', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await login(page)
  await page.goto('/oa/balances')
  await expect(page.getByRole('heading', { name: '请假额度', exact: true })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await page.screenshot({ path: '../data/verification/m2/manual-oa-mobile.png', fullPage: true })
})
