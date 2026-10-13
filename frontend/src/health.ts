import type {InsurerGuidance} from './types';

export function findGuidance(items:InsurerGuidance[],insurer:string){
 const normalize=(value:string)=>value.toLowerCase().replace(/[^a-z0-9]/g,'');
 return items.find(item=>item.aliases.some(alias=>normalize(alias)===normalize(insurer)));
}
