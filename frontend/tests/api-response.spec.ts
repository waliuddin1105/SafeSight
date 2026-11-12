import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

function client(fetcher:typeof fetch){
 const exports:Record<string,unknown>={};let expired=0;
 const source=ts.transpileModule(readFileSync(new URL('../src/api.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(source,{exports,fetch:fetcher,Headers,Event,window:{dispatchEvent:()=>{expired++}}});
 return {api:exports.api as (path:string,options?:RequestInit)=>Promise<unknown>,expired:()=>expired};
}

test('empty proxy failure produces a backend diagnostic',async()=>{
 const {api}=client(async()=>new Response(null,{status:500}));
 await expect(api('/auth/me')).rejects.toThrow('backend is unavailable');
});
test('HTML gateway errors do not expose parser errors',async()=>{
 const {api}=client(async()=>new Response('<html>Bad Gateway</html>',{status:502}));
 await expect(api('/auth/me')).rejects.toThrow('HTTP 502');
});
test('structured API errors retain the server message',async()=>{
 const {api}=client(async()=>new Response(JSON.stringify({error:{message:'Sign in to continue'}}),{status:401}));
 await expect(api('/incidents')).rejects.toThrow('Sign in to continue');
});
test('empty unauthorized responses still expire the session',async()=>{
 const value=client(async()=>new Response(null,{status:401}));
 await expect(value.api('/incidents')).rejects.toThrow('HTTP 401');
 expect(value.expired()).toBe(1);
});
test('no-content responses are accepted while empty success JSON is rejected',async()=>{
 await expect(client(async()=>new Response(null,{status:204})).api('/auth/logout',{method:'POST'})).resolves.toBeUndefined();
 await expect(client(async()=>new Response(null,{status:200})).api('/auth/me')).rejects.toThrow('invalid or empty JSON');
});
test('network failures are actionable and aborts stay aborts',async()=>{
 await expect(client(async()=>{throw new TypeError('fetch failed')}).api('/auth/me')).rejects.toThrow('Cannot reach');
 await expect(client(async()=>{throw new DOMException('Cancelled','AbortError')}).api('/auth/me')).rejects.toMatchObject({name:'AbortError'});
});
