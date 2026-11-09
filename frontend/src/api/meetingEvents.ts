import client from './client'
export interface MeetingPerson { id:string; display_name:string; department_id:string }
export interface MeetingFields { title:string; agenda:string; starts_at:string; ends_at:string; host_id:string; recorder_id:string; attendee_ids:string[]; location:string; online_url:string; video_enabled?:boolean }
export interface MeetingVideoSession { sdkAppId:number; userId:string; userName:string; userSig:string; roomId:string; password:string; expiresAt:string }
export interface MeetingAttendee { user_id:string; display_name:string; response:string; note:string; replied_at:string|null }
export interface MeetingEvent extends Omit<MeetingFields,'attendee_ids'> {
  id:string; organizer_id:string; state:string; revision:number; invitation_version:number; minutes_id:string|null; cancel_reason:string;
  available_actions:string[]; attendees:MeetingAttendee[]; minutes_accessible:boolean; minutes_status:string|null;
  history?:{action:string;actor_id:string;created_at:string}[];
  deliveries?:{id:string;recipient_id:string;channel:string;state:string;attempt_count:number;last_code:string|null}[]
}
interface CommandResult {result:MeetingEvent; replayed:boolean}
export const meetingEventsApi = {
  list:(mode='all'):Promise<MeetingEvent[]>=>client.get('/meeting-events',{params:{mode}}),
  get:(id:string):Promise<MeetingEvent>=>client.get('/meeting-events/'+id),
  videoSession:(id:string):Promise<MeetingVideoSession>=>client.post('/meeting-events/'+id+'/video-session'),
  options:():Promise<{users:MeetingPerson[];departments:{id:string;name:string}[]}>=>client.get('/meeting-events/options'),
  conflicts:(payload:MeetingFields,exclude_id?:string):Promise<{user_id:string;display_name:string;count:number}[]>=>client.post('/meeting-events/conflicts',payload,{params:{exclude_id}}),
  save:(payload:MeetingFields & {operation_id:string;expected_revision?:number},id?:string):Promise<CommandResult>=>id?client.put('/meeting-events/'+id,payload):client.post('/meeting-events',payload),
  command:(id:string,action:string,payload:Record<string,unknown>):Promise<CommandResult>=>client.post('/meeting-events/'+id+'/'+action,payload),
}
