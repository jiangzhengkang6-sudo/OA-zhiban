import client from './client'
export interface TranscriptionStatus {
  configured:boolean; state:string; notice:string; message:string; partial:boolean; expired:boolean;
  can_start:boolean; can_stop:boolean; can_retry:boolean; minutes_id:string|null; utterance_count:number;
  utterances:{id:string;speaker:string;start_ms:number;end_ms:number;text:string;late:boolean}[]
}
export const meetingTranscriptionApi={
  get:(id:string):Promise<TranscriptionStatus>=>client.get('/meeting-transcriptions/'+id),
  command:(id:string,action:string,payload:Record<string,unknown>):Promise<unknown>=>client.post('/meeting-transcriptions/'+id+'/'+action,payload),
}
