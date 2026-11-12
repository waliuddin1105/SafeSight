export type Slug = 'body_state'|'phone_usage'|'cigarette_smoking'|'entrance_guard'|'fire_smoke';
export const labels: Record<Slug,string>={body_state:'Body state',phone_usage:'Phone usage',cigarette_smoking:'Smoking',entrance_guard:'Entrance check',fire_smoke:'Fire & smoke'};
export const slugs=Object.keys(labels) as Slug[];
export interface User {id:string;username:string;role:'admin'|'reviewer';active:boolean}
export interface Location {id:string;name:string;timezone:string}
export interface Source {id:string;name:string;location_id:string;kind:'browser'|'upload'|'usb'|'rtsp';enabled_models:Slug[];active:boolean;generation:number;last_sequence:number;health:{status?:string;dropped_frames?:number}}
export interface Evidence {id:string;kind:string;state:string;url:string|null;error?:string}
export interface Review {id:string;decision:string;notes:string;created_at:string}
export interface Incident {id:string;slug:Slug;subtype:string;location_id:string;score:number;review_status:string;start_at:string|null;start_offset:number;end_offset:number;uncertain:boolean;evaluation_only:boolean;evidence?:Evidence[];reviews?:Review[]}
export interface ModelStatus {ready:boolean;evaluation_only?:boolean;reason?:string}
export interface AuthResponse {user:User|null;csrf_token:string;timezone?:string}
export interface ListResponse<T> {items:T[];total:number;page:number}
export interface ModelsResponse {items:Record<string,ModelStatus>;worker_alive:boolean}
export interface ModelVersion {slug:Slug;run_id:string;quality:{status:string};synthetic:boolean}
export interface Job {id:string;state:string;cursor:number;duration:number;error?:string;created_at:string;cancel_requested:boolean;processed_frames:number;processing_seconds:number;snapshot:{evaluation:boolean;cards:Partial<Record<Slug,{run_id:string}>>}}
export interface Detection {label:string;score:number;box:[number,number,number,number];track_id?:string}
export interface JobFrame {timestamp:number;predictions:{slug:Slug;model_version:string;unknown_reason?:string;detections:Detection[];scores:Record<string,number>}[];unknown:Record<string,string>}
