export interface DatasetExample {session_id?:string;capture_id?:string;evidence_level?:string;inclusion_state?:string;crc_valid?:boolean}
export const summarizeExamples=(examples:DatasetExample[])=>({
 total:examples.length,
 crcValid:examples.filter(item=>item.crc_valid).length,
 included:examples.filter(item=>item.inclusion_state?.startsWith('INCLUDED')).length,
 excluded:examples.filter(item=>item.inclusion_state?.startsWith('EXCLUDED')).length,
 sessions:new Set(examples.map(item=>item.session_id).filter(Boolean)).size,
});
export const splitHasLeakage=(split:Record<'train'|'validation'|'test',Record<string,string[]>>)=>{
 const groups=[Object.keys(split.train),Object.keys(split.validation),Object.keys(split.test)];
 return groups.some((left,index)=>groups.some((right,rightIndex)=>rightIndex>index&&left.some(key=>right.includes(key))));
};
