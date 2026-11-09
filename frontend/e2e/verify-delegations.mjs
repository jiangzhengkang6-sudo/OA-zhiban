// Local self-only verification. This script creates no users or outbound messages.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root=fileURLToPath(new URL('../../',import.meta.url))
const backend=path.join(root,'backend')
const output=path.join(root,'output/business-acceptance-private/delegations')
const stamp=new Date().toISOString().replace(/[:.]/g,'-')
const receipt={checked_at:new Date().toISOString(),scope:'existing_single_member',department_trial:false,external_delivery:false,checks:[],screenshots:[]}
const program=`
import asyncio,json,sys
from datetime import timedelta
from sqlalchemy import select,update
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser,OAAuthSession
from app.services import identity_service as identity
from scripts.import_public_company_knowledge import actor_for_import
async def main():
    async with async_session_factory() as db:
        actor=await actor_for_import(db,'oa_admin')
        user=await db.get(OAUser,actor.user_id)
        if sys.argv[1]=='issue':
            issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=20))
            row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
            identity.audit(db,user.id,'identity.acceptance_session',row.family_id)
            await db.commit()
            print(json.dumps(dict(refresh=issued.refresh,family=row.family_id)))
        else:
            family=sys.argv[2]
            await db.execute(update(OAAuthSession).where(OAAuthSession.tenant_id==actor.tenant_id,OAAuthSession.user_id==user.id,OAAuthSession.family_id==family).values(revoked_at=identity.utcnow()))
            identity.audit(db,user.id,'identity.acceptance_closed',family)
            await db.commit()
            assert await db.scalar(select(OAAuthSession.id).where(OAAuthSession.family_id==family,OAAuthSession.revoked_at.is_(None))) is None
    await engine.dispose()
asyncio.run(main())
`
function identity(action,family){
  try{return execFileSync(path.join(backend,'.venv/Scripts/python.exe'),['-c',program,action,...(family?[family]:[])],{cwd:backend,encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim()}
  catch{throw new Error('acceptance_identity_failed')}
}
await mkdir(output,{recursive:true})
let session,browser,page,failure
const errors=[],requests=[]
async function check(name,fn){await fn();receipt.checks.push({name,passed:true});console.log('PASS '+name)}
async function screenshot(name){const filename=stamp+'-'+name+'.png';await page.screenshot({path:path.join(output,filename),fullPage:true,animations:'disabled'});receipt.screenshots.push(filename)}
async function fits(){
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true)
  for(const element of await page.locator('.el-dialog').all()){
    const size=await element.evaluate(node=>({width:node.getBoundingClientRect().width,left:node.getBoundingClientRect().left,scroll:node.scrollWidth,inner:node.clientWidth}))
    expect(size.left).toBeGreaterThanOrEqual(0);expect(size.scroll).toBeLessThanOrEqual(size.inner+1)
  }
}
try{
  session=JSON.parse(identity('issue'))
  browser=await chromium.launch({channel:'msedge',headless:true})
  const context=await browser.newContext({viewport:{width:1440,height:960}})
  await context.addCookies([{name:'oa_refresh',value:session.refresh,domain:'127.0.0.1',path:'/api/auth',httpOnly:true,secure:false,sameSite:'Lax'}])
  page=await context.newPage()
  page.on('pageerror',()=>errors.push('page_error'))
  page.on('response',response=>{if(response.url().includes('/api/')&&response.status()>=400)requests.push({path:new URL(response.url()).pathname,status:response.status()})})
  await check('desktop authorized delegation page',async()=>{
    const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/oa/delegations/candidates')
    await page.goto('http://127.0.0.1:5182/oa/delegations')
    expect((await response).ok()).toBe(true)
    await expect(page.getByRole('heading',{name:'审批委托'})).toBeVisible()
    await expect(page.getByText('暂无委托记录').first()).toBeVisible()
    await fits();await screenshot('desktop')
  })
  await check('single member candidate list cannot create false delegation',async()=>{
    await page.getByRole('button',{name:'新建委托',exact:true}).click()
    await expect(page.getByText('当前没有同部门且具备审批读写资格的其他成员')).toBeVisible()
    await expect(page.getByRole('button',{name:'保存委托',exact:true})).toBeDisabled()
    await fits();await screenshot('empty-candidates')
    await page.getByRole('button',{name:'取消',exact:true}).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await page.getByText('我收到的委托',{exact:true}).click()
    await expect(page.getByRole('radio',{name:'我收到的委托'})).toBeChecked()
    await expect(page.getByText('暂无委托记录').first()).toBeVisible()
  })
  await check('mobile page and dialog fit viewport',async()=>{
    await page.setViewportSize({width:390,height:844})
    await fits();await screenshot('mobile')
    await page.getByRole('button',{name:'新建委托',exact:true}).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await fits();await screenshot('mobile-dialog')
    await page.getByRole('button',{name:'取消',exact:true}).click()
  })
  await check('approval workbench remains accessible',async()=>{
    await page.goto('http://127.0.0.1:5182/oa/approvals')
    await expect(page.getByRole('heading',{name:'审批工作台'})).toBeVisible()
    await expect(page.getByText('暂无记录').first()).toBeVisible()
    await fits()
  })
}catch(error){failure=error;receipt.error=String(error?.message||error)}
finally{
  if(browser)await browser.close()
  if(session){try{identity('revoke',session.family);receipt.acceptance_session_revoked=true}catch{receipt.acceptance_session_revoked=false;failure||=new Error('session_cleanup_failed')}}
  receipt.page_errors=errors;receipt.failed_requests=requests
  receipt.passed=!failure&&!errors.length&&!requests.length
  await writeFile(path.join(output,'browser-'+stamp+'.json'),JSON.stringify(receipt,null,2)+'\n')
}
if(!receipt.passed)throw failure||new Error('browser_errors_or_failed_requests')
