'use client';

import {FormEvent,useEffect,useState} from 'react';
import DocumentStatus from '@/components/DocumentStatus';
import {api} from '@/lib/api';

export default function Documents(){
  const [kbs,setKbs]=useState<any[]>([]);const [kb,setKb]=useState('');const [docs,setDocs]=useState<any[]>([]);const [selected,setSelected]=useState<any|null>(null);
  const load=()=>kb&&api(`knowledge-bases/${kb}/documents`).then(setDocs);
  useEffect(()=>{api('knowledge-bases').then((x:any[])=>{setKbs(x);if(x[0])setKb(x[0].id)})},[]);
  useEffect(()=>{load()},[kb]);
  async function upload(e:FormEvent<HTMLFormElement>){e.preventDefault();const form=new FormData(e.currentTarget);await fetch(`/frontend-api/backend/knowledge-bases/${kb}/documents/upload`,{method:'POST',body:form});load()}
  async function reprocess(id:string){await api(`knowledge-bases/${kb}/documents/${id}/reprocess`,{method:'POST'});load()}
  return <><h1 className="page-title">Documents</h1><p className="muted">External MinIO storage with asynchronous parsing and Qdrant indexing.</p><form className="card" onSubmit={upload} style={{display:'flex',gap:12,padding:16,margin:'22px 0'}}><select className="input" value={kb} onChange={e=>setKb(e.target.value)}>{kbs.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select><input className="input" name="file" type="file" required/><button className="button">Upload</button></form><div className="card"><table className="table"><thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Chunks</th><th>Status</th><th>Actions</th></tr></thead><tbody>{docs.map(x=><tr key={x.id}><td onClick={()=>setSelected(x)} style={{cursor:'pointer'}}>{x.original_filename}</td><td className="muted">{x.file_type}</td><td>{Math.ceil(x.file_size/1024)} KB</td><td>{x.chunk_count}</td><td><DocumentStatus status={x.status}/></td><td><a className="button" href={`/frontend-api/backend/knowledge-bases/${kb}/documents/${x.id}/download`} target="_blank" rel="noreferrer" style={{textDecoration:'none',marginRight:8}}>Download</a>{x.status==='failed'&&<button className="button" onClick={()=>reprocess(x.id)}>Reprocess</button>}</td></tr>)}</tbody></table></div>{selected&&<div className="card" style={{padding:18,marginTop:18}}><b>MinIO object key</b><p className="muted" style={{wordBreak:'break-all'}}>{selected.file_path}</p></div>}</>
}
