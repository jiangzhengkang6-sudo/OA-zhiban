import {ref,onBeforeUnmount} from 'vue'
import {authState,can} from '@/stores/auth'
const labels:Record<string,string>={DRAFT:'草稿',IN_REVIEW:'审批中',PAUSED:'暂停待处理',APPROVED:'已批准',REJECTED:'已驳回或退回',CANCELLED:'已撤回',WAITING:'尚未轮到',ACTIVE:'正在办理',PENDING:'待处理',CC:'已抄送',COMPLETED:'已完成',CLEAN:'扫描通过',ERROR:'扫描异常',INFECTED:'材料不安全',annual:'年假',sick:'病假',single:'单人审批',all:'会签',any:'或签',approve:'批准',reject:'驳回',return_for_correction:'退回修改',materials_incomplete:'材料不完整',date_issue:'日期有误',quota_issue:'额度问题',other:'其他原因',leave_type:'假种',start_date:'开始日期',end_date:'结束日期',reason:'事由',attachment_ids:'证明材料'}
Object.assign(labels,{purpose:'报销事由',expense_date:'费用日期',category:'费用类别',amount:'报销金额',currency:'币种'})
export const oaLabel=(value:string)=>labels[value]||(/^[A-Za-z_]+$/.test(value)?'待核对':value)
export const canOA=(resource:string,action='read')=>authState.provider==='builtin'&&authState.manualOA&&can(resource,action)
export const messageOf=(e:unknown)=>(e as any)?.response?.data?.message||(e as Error)?.message||'请求失败，请重试'
export const fileId=(a:{id?:string;attachment_id?:string})=>a.id||a.attachment_id||''
export function useOACommands(){
  const busy=ref(false),error=ref('')
  const keys=new Map<string,string>()
  onBeforeUnmount(()=>keys.clear())
  async function run<T>(action:string,data:Record<string,unknown>,send:(payload:any)=>Promise<T>,preparedOperationId?:string):Promise<T|undefined>{
    if(busy.value)return
    busy.value=true;error.value=''
    const snapshot=JSON.parse(JSON.stringify(data)) as Record<string,unknown>
    delete snapshot.operation_id
    const fingerprint=action+':'+JSON.stringify(snapshot)
    if(!keys.has(fingerprint))keys.set(fingerprint,preparedOperationId||crypto.randomUUID())
    try{const result=await send({...snapshot,operation_id:keys.get(fingerprint)!});keys.delete(fingerprint);return result}
    catch(e){error.value=messageOf(e);return undefined}
    finally{busy.value=false}
  }
  return {busy,error,run}
}
export async function downloadOA(url:string,filename:string){
  const {oaApi}=await import('@/api/oa')
  const blob=await oaApi.download(url),href=URL.createObjectURL(blob),link=document.createElement('a')
  link.href=href;link.download=filename;link.click();URL.revokeObjectURL(href)
}
