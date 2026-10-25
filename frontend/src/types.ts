export interface Block { id:string; text:string; location:string; source:string; original_text:string|null }
export interface Document {id:string; version:number; name:string; kind:string; blocks:Block[]; warnings:string[]; coverage:string; complete:boolean}
export interface Evidence {block_id:string; quote:string; location:string}
export interface Fact {label:string; value:string; evidence:Evidence[]}
export interface Issue {title:string; level:string; reason:string; evidence:Evidence[]; explanation:string; impact:string; status:string; question:string; negotiation:string}
export interface Result {report_id?:string;mode:string; version:number; coverage:string; warnings:string[]; scope_note:string; evidence_status:string; report:{summary:string; facts:Fact[]; issues:Issue[]; questions:string[]; amendments:string[]; message:string}}
