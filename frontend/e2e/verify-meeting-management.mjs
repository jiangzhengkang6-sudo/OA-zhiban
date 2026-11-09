// Run against the isolated, paused backend on 8016 and frontend on 5183.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root=fileURLToPath(new URL('../../',import.meta.url)),backend=path.join(root,'backend')
const output=path.join(root,'output/business-acceptance-private/meeting-management')
const stamp=new Date().toISOString().replace(/[:.]/g,'-')
const testEnv={...process.env,DATABASE_URL:'postgresql+asyncpg://oa:oa@localhost:5433/oa_business_m3_test',
  DATABASE_SYNC_URL:'postgresql+psycopg://oa:oa@localhost:5433/oa_business_m3_test',
  CHECKPOINTER_URL:'postgresql://oa:oa@localhost:5433/oa_business_m3_test',AUTH_PROVIDER:'builtin',OA_PROVIDER:'builtin',
  SMTP_ENABLED:'false',WECOM_ENABLED:'false',LLM_PROVIDER:'mock',EMBEDDING_PROVIDER:'mock',EMBEDDING_DIM:'1536'}
const seed=`
import asyncio,json
from datetime import timedelta
from sqlalchemy import make_url
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser
from app.services.identity_service import issue,utcnow
from tests.oa_support import seed
async def main():
    assert make_url(get_settings().database_url).database=='oa_business_m3_test'
    async with async_session_factory() as db:
        owner=await seed(db,resources=['meeting','notification','work_task'],scope='self')
        guest=await seed(db,tenant=owner.tenant_id,resources=['meeting','notification'],scope='self')
        a,b=await db.get(OAUser,owner.user_id),await db.get(OAUser,guest.user_id)
        a.display_name,b.display_name='会议发起人','跨部门参会人'
        result=[]
        for user in (a,b):
            issued=await issue(db,user,get_settings(),expires=utcnow()+timedelta(minutes=20))
            result.append(dict(id=user.id,refresh=issued.refresh))
        await db.commit()
        print(json.dumps(result))
    await engine.dispose()
asyncio.run(main())
`
await mkdir(output,{recursive:true})
const identities=JSON.parse(execFileSync(path.join(backend,'.venv/Scripts/python.exe'),['-c',seed],{cwd:backend,env:testEnv,encoding:'utf8',stdio:['ignore','pipe','pipe']}))
const receipt={checked_at:new Date().toISOString(),database:'oa_business_m3_test',external_delivery:false,model:'mock',checks:[],screenshots:[]}
const browser=await chromium.launch({channel:'msedge',headless:true}),contexts=[],errors=[]
let page
async function actor(index,viewport={width:1440,height:960}){
  const context=await browser.newContext({viewport});contexts.push(context)
  await context.addCookies([{name:'oa_refresh',value:identities[index].refresh,domain:'127.0.0.1',path:'/api/auth',httpOnly:true,secure:false,sameSite:'Lax'}])
  const result=await context.newPage();result.on('pageerror',e=>errors.push(e.message));return result
}
async function check(name,fn){await fn();receipt.checks.push({name,passed:true});console.log('PASS '+name)}
async function screenshot(name){const file=stamp+'-'+name+'.png';await page.screenshot({path:path.join(output,file),fullPage:true,animations:'disabled'});receipt.screenshots.push(file)}
async function fits(){expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)}
async function request(button,suffix){const [response]=await Promise.all([page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(suffix)&&r.request().method()==='POST'),button.click()]);expect(response.status(),await response.text()).toBe(200);return (await response.json()).data}
try{
  page=await actor(0)
  await page.goto('http://127.0.0.1:5183/meetings')
  await check('desktop invitation form and cross-department selection',async()=>{
    await page.getByRole('button',{name:'发起会议',exact:true}).click()
    const dialog=page.getByRole('dialog',{name:'发起会议'})
    await expect(dialog).toBeVisible()
    await dialog.getByRole('textbox',{name:'会议主题',exact:true}).fill('跨部门项目验收会议')
    await dialog.getByRole('textbox',{name:'会议议题',exact:true}).fill('核对验收范围、完成情况及后续待办')
    for(const [label,hour] of [['开始时间','10'],['结束时间','11']]){
      const input=dialog.getByRole('combobox',{name:label,exact:true})
      const day=new Date(Date.now()+86400000*3).toISOString().slice(0,10)
      await input.fill(day+' '+hour+':00');await input.press('Enter')
    }
    await dialog.locator('.el-form-item').filter({hasText:'参会人员'}).locator('.el-select__wrapper').click()
    await page.getByRole('option',{name:'跨部门参会人',exact:true}).click()
    await dialog.getByRole('textbox',{name:'会议地点',exact:true}).click()
    await dialog.getByRole('textbox',{name:'会议地点',exact:true}).fill('一号会议室')
    await fits();await screenshot('desktop-form')
    await request(dialog.getByRole('button',{name:'保存草稿',exact:true}),'/meeting-events')
    await expect(page).toHaveURL(/\/meeting-events\//)
    receipt.meeting_path=new URL(page.url()).pathname
    await expect(page.getByRole('heading',{name:'跨部门项目验收会议',exact:true})).toBeVisible()
  })
  await check('publish invitations and guest RSVP',async()=>{
    await page.getByRole('button',{name:'发送邀请',exact:true}).click()
    await request(page.getByRole('dialog',{name:'发送会议邀请'}).getByRole('button',{name:'发送邀请',exact:true}),'/publish')
    await expect(page.getByRole('button',{name:'开始会议',exact:true})).toBeVisible()
    const guest=await actor(1)
    await guest.goto('http://127.0.0.1:5183'+receipt.meeting_path)
    await guest.getByRole('radio',{name:'参加',exact:true}).check()
    const waiting=guest.waitForResponse(r=>r.url().endsWith('/reply')&&r.request().method()==='POST')
    await guest.getByRole('button',{name:'提交反馈',exact:true}).click()
    expect((await waiting).ok()).toBe(true)
    await expect(guest.getByText('1 / 2 人已确认参加',{exact:true})).toBeVisible()
    await guest.goto('http://127.0.0.1:5183/oa/notifications')
    await expect(guest.getByText('收到会议邀请',{exact:true})).toBeVisible()
    await guest.close()
    await page.reload()
    await expect(page.getByRole('heading',{name:'跨部门项目验收会议',exact:true})).toBeVisible()
    await expect(page.getByText('1 / 2 人已确认参加',{exact:true})).toBeVisible()
    await fits();await screenshot('desktop-detail')
  })
  await check('start, end, create associated minutes, generate and confirm',async()=>{
    await request(page.getByRole('button',{name:'开始会议',exact:true}),'/start')
    await page.getByRole('button',{name:'结束会议',exact:true}).click()
    await request(page.getByRole('dialog',{name:'结束会议'}).getByRole('button',{name:'结束会议',exact:true}),'/end')
    await page.getByRole('textbox',{name:'会后会议文本',exact:true}).fill('议题：跨部门项目验收。决定：本次验收通过。待办：整理测试记录，负责人会议发起人，截止下周五。')
    await request(page.getByRole('button',{name:'创建纪要',exact:true}),'/minutes')
    await page.getByRole('button',{name:'查看会议纪要',exact:true}).click()
    await request(page.getByRole('button',{name:'生成草稿',exact:true}),'/generate')
    await expect(page.getByRole('textbox',{name:'纪要摘要',exact:true})).not.toBeEmpty()
    await page.getByTestId('confirm-meeting').click()
    await request(page.getByRole('dialog',{name:'确认草稿'}).getByRole('button',{name:'确定',exact:true}),'/decisions')
    await expect(page.getByRole('button',{name:'提取业务任务',exact:true})).toBeVisible()
    await page.getByRole('button',{name:'返回会议安排',exact:true}).click()
    await expect(page).toHaveURL(new RegExp(receipt.meeting_path))
  })
  await check('mobile detail and organization dropdown remain within viewport',async()=>{
    await page.setViewportSize({width:390,height:844})
    await expect(page.getByRole('heading',{name:'跨部门项目验收会议',exact:true})).toBeVisible()
    await expect(page.getByRole('button',{name:'查看会议纪要',exact:true})).toBeVisible()
    await fits();await screenshot('mobile-detail')
    await page.getByRole('button',{name:'会议列表',exact:true}).click()
    await page.getByRole('button',{name:'发起会议',exact:true}).click()
    await page.locator('.el-form-item').filter({hasText:'参会人员'}).locator('.el-select__wrapper').click()
    await expect(page.getByRole('option',{name:'跨部门参会人',exact:true})).toBeVisible()
    await fits();await screenshot('mobile-dropdown')
    for(const el of await page.locator('.el-dialog:visible,.el-select__popper:visible').all()){
      const box=await el.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(391)
    }
  })
  expect(errors).toEqual([])
}catch(error){receipt.failure=error.message;if(page)await screenshot('failure');throw error}
finally{for(const context of contexts)await context.close();await browser.close();await writeFile(path.join(output,stamp+'-receipt.json'),JSON.stringify(receipt,null,2)+'\n')}
