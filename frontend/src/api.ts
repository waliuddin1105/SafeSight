let csrf='';
export function setCsrf(value:string){csrf=value}
export async function api<T=Record<string,unknown>>(path:string,options:RequestInit={}):Promise<T>{
 const headers=new Headers(options.headers);
 if(typeof options.body==='string')headers.set('Content-Type','application/json');
 if(options.method&&options.method!=='GET')headers.set('X-CSRF-Token',csrf);
 const response=await fetch('/api/v1'+path,{...options,headers,credentials:'same-origin'});
 const data:unknown=await response.json();
 if(response.status===401)window.dispatchEvent(new Event('auth-expired'));
 if(!response.ok){const problem=data as {error?:{message?:string}};throw Object.assign(new Error(problem.error?.message||'Request failed'),{status:response.status})}
 return data as T;
}
