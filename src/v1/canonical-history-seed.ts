import { isFrozenSelectedRace } from "./frozen-public-data.js";
import { ensurePublicHistory } from "./public-history-db.js";

const ALLOWED_CHUNK_HASHES = new Set([
"0fd44374718201a499e351138af326994b06189cd63016516a4231f8e331403e","f9e99ab9ac0a690febda1f4f4e85952a083f6574218c9b202572475a64cbbe66","986913b055ddc9024ab130e43b93c1aca12dd88683a5762f2fbea56377e94df4","e8f2ce409c2e110b526ebcd93a2932aeb74dbaf762e32eae7ce44578b8f20dc1","2ceb0af89c76416c8e5655991d9701dd70166c4bcb4a36169e4618054e588856","40437e668c17a973c6cf2d7a691f7b3870a1678ca7cfb857d4948515257b565c","f8d9199ff4d50bb1c8ac20b1765245530d88f993e3936bd6c7492553e07776a6","104c5c9d189a3011202f865d92848b014eb30c813303fa24a211bbe47f132e98","8c6cc6a595fefd134fe1d285be74d13227a5adbb7a7aeee260a4d16e9899cbe3","21d3521956a5ba934288a51a8f225a0de4a5d5ad85890521c13abbbffaafd2d1","6f9974ab6403c03806bd066e2c2a2dd140a38647e41e48e7d5b47047dc06227f","99ea8ff6475df1b574c77f3af5873e0e654b874041636cbad5887f061744cff6","e1ed52d85110d5d0a22a230a9fda3a0c315ee3cb589cea3260797076fc717bea","1470e24128929f5d7ec197f52dd3e5c71f69db6272c471ce37b9cbeb731351b2","863335cae65258329f534e0ba681d484b7b3b15e6d5ccf56f8165b87cc7e0b9d","aa196147bba2ce036a9d50575d81c9e1880c14e6ff8e74ec2153a5fc1c367dd0","6be7eaade36fad0e75ea9f01b9b6fcfbfc25aa536fd48414a9a4e48e788acf5c","2de25724a5f33ab243a554d2b27824f21c8a2e57f59e69dd90ecb77d317bfb3d","e8697224d20f0bf57bc0ed19c851f2363c26e7681a1982005873b57139f0e73c","8329d8680ef4396ba3d4926d0dbd28aafdeddda02ce578b95f84eb41e28e181d","037c2b228bce1336e733d6142ac22c44914753ab9545dcb4e8a9bafaa9e89f1a","81f5bd9c4b1534d7f1bc22bceb94b3cd95f4e7b5990e87974504e4e26e6ce86d","84ba5082ef100a4ecd15c307db4184145501555436bb4f00dddb37ffb8ea8a19","bad7ad8ff0a2a36f2f37d10217d4752ee0643ccd1040aabadd30863bc8b59ac7","dad720cb5134d609dc3c124489c94e39d49ba86b329fba1993b8ee5563d802ef","4d3d5720d8665033f6d79fe6bc1d11aa439e48667206cff9b33de4a75004515d","d417a9b8a0a5b4936006072d399d0ff12b179cc400edbb11241cadeb4428a5db","5d797f6b7f801db1b83a2a836558e97c1576d144159c9d2686cec9930db1f4e9","d018e9c7093b620dbe23faf477341d7f5dd35da58b2c514cbb77bdf0dfbdd4a6","e7a95877fb1e9bd54c27099033aebe3055e2f45720269f2abf264751f82cc652","67723b8436548a3f42c2872c2d7657a78abbeb1937b768a6ac157e41abcca4af","52e52399357eb52128292515df5a307bab39d4e83dca43a04ab3dcea32f1233b","ea1dc66eac74d3690e610e4151c11299aca5bff1bcab39466d8b105c4624cc19","e1290ad263e9220464e135461d60e68635a1d2e915de26989d5123534ce17784","4b1c1c28f5a388e1b0e79d719c02236a739c20ebf00682af990f9da8c8085764","9a1dc20eac61d22e661599f9d7bbeeb634f738ddbfdec0a72b2818040169e8c6","c83d306dbaa1cfbae3a137357d47b70d28503f466d6cad65c615805c191021c9","64aa61edcf9167115d0491c2e3938af460f38c2a000e3ab52dcf6a2babacc1bb","7eab0358eab12582fbb7438437dddf1e15f0b029b786f2401a394356bd0be3a9","6f38276e2a991020c75ef7fc4e0132f6a4a3b3120a90eff7563b61e5729aca84","d6c9dacb5bf962cfdf05e77e4e179199320a42264b4e5d8128a2430b50a46c24","5d925d29d67edf265c1b13c614ade34128f2c3ef57ae25c31df228fde2d3e76f","2147bd1900ff711246bee2ca3c345a28b8f37b9be3c32b3ca2f0fc972426556e","d9af343f4780b3e9423ac8497b452a3c7a595cddb7ca32f4526242bf53c72fba","cc86cabc3d18e1359e73b64ca40683afeaaac1e852eaf5fa80c80ad7611feab9","8b28bdf6131b57e483bab12c8a87a50f04bf2fb36166dfee425c8e58f4bc395e","dce5e8defd46e96bc7b5e860883947362f656d9751c82580e1191f5606f0580a","32bce4a77ea75adc688fdb2a877cb4b4e8d76868e5cc6d1baefc91cb211b85d2","49009ab211f022998450129f662285338f1f0cb8a9fb16a17f1bf17cbed283a8","32212747e98a89b1f6cef1685c5505890cc1284a18f0106ad271dfbd85258c1a","0c0808447de17aaa1db4e0fa6d9f488f9c15c4761b2f27d922c5eaf310c611ca","62bcf0071ab7f4c441b56ad0361b315663547c1b58ad90d739b510d0b8a2c5dc","e3f9a85ece1f1196ae3ae7da881aa943166d1e709c85da0532829d088233f8a4","a9acf0ceaf92336f298f7f98726648465eaf743be2955df212f7187f51bec52e","547a1beaade27c65b63d4f2aad119cfe1b9ed54a00a51dff1de84be6ae774a8a","483f59d0cfa7f65c731c0397cbfc0e6211f5953fa08ad415a808db2de41da518","b6229b1148e364f0143778e960ccc85cfb7c2eb6dab7da1780d608a336e8f264","2bd208384e11b5acc5f1ee6b3c6218c0ee2716c1cd374b9b67b53d3f112460f4","581d48bd75e7e5e02ccf11cae348ee3acb59e811968bdb4cc5874e41d2b4ca5d","d083c0a176eb434b4acfacf72001a9605a8164ce95ce480b68846a7a1d0cd126","990819f9ea9375723b7e20f71ed4a5d13dcecac3fcc12c1f2ad7c96225e1da1d","870e4c256ea8d66cd82905fabed0a579d91e9bef629a211a96a1d69674309d50","b7992ea42ac37666b0c81cefa119797c44c6885643d72efccb30f232337a8a54","f340e95dc9140de5c05d2116d5909af930b25e2deb95d4c2cb7dc6cd1ab22cc0","c53e0a804ccf1b8688158aa7c7ba8bf40c24d04d6d7f4d6b78f000acc75ccce4"
]);
const RESET_HASH="3cb1525bdd7132ece2b84b128004c9970a031d29a2d19cdbfcab2e1635631c61";
const FINAL_HASH="462c9f55462cb6cc93a53deef04b00cda4e16a9b5c4fbc8fa45f664b3b711b20";
const ODDS_LABELS=["1-2","2-3","3-5","5-7","7-10","10-15","15-20","20-30","30-50","50-75","75-100","100-150","150-300","300-500","500-800","800-1200","1200-2000","2000+"];
const ODDS_MID=[1.4,2.45,3.9,5.9,8.4,12.2,17.3,24.5,38.7,61.2,86.6,122.5,212.1,387.3,632.5,979.8,1549.2,2500.0];
const COURSES=[["ライト",20],["スタンダード",50],["プレミアム",100]] as const;

type SeedTicket=[string,string,number|[number,number],string,number,number];
type SeedChunk=Record<string,SeedTicket[]>;

async function sha256(text:string):Promise<string>{
  const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,"0")).join("");
}

function allocation(oddsBins:string[],unitsTotal:number):number[]{
  const binCodes=oddsBins.map(label=>ODDS_LABELS.indexOf(label));
  if(binCodes.some(code=>code<0)) throw new Error("UNKNOWN_ODDS_BIN");
  const n=binCodes.length,cap=Math.max(1,Math.floor(unitsTotal*0.35+1e-12));
  if(n*cap<unitsTotal) throw new Error("CAP_INFEASIBLE");
  const units=Array(n).fill(1);let remaining=unitsTotal-n;
  const weights=binCodes.map(code=>Math.min(1,Math.pow(100/ODDS_MID[code],1.5)));
  const totalWeight=weights.reduce((a,b)=>a+b,0);
  const targets=weights.map(w=>unitsTotal*w/totalWeight);
  while(remaining>0){
    const eligible=units.map((_,i)=>i).filter(i=>units[i]<cap);
    eligible.sort((a,b)=>{
      const da=targets[a]-units[a],db=targets[b]-units[b];
      if(Math.abs(db-da)>1e-12)return db-da;
      if(Math.abs(weights[b]-weights[a])>1e-12)return weights[b]-weights[a];
      const oa=ODDS_MID[binCodes[a]],ob=ODDS_MID[binCodes[b]];
      if(oa!==ob)return oa-ob;
      return a-b;
    });
    units[eligible[0]]+=1;remaining-=1;
  }
  return units;
}

function assumedOdds(value:number|[number,number]):number{
  return Array.isArray(value)?(Number(value[0])+Number(value[1]))/2:Number(value);
}

function raceParts(raceId:string):{date:string;venue:string;raceNo:number}|null{
  const m=raceId.match(/^(20\d{2}-\d{2}-\d{2})-(sapporo|hakodate|fukushima|niigata|tokyo|nakayama|chukyo|kyoto|hanshin|kokura)-(\d{2})$/);
  if(!m)return null;
  const venueMap:Record<string,string>={sapporo:"札幌",hakodate:"函館",fukushima:"福島",niigata:"新潟",tokyo:"東京",nakayama:"中山",chukyo:"中京",kyoto:"京都",hanshin:"阪神",kokura:"小倉"};
  return {date:m[1],venue:venueMap[m[2]],raceNo:Number(m[3])};
}

async function runReset(db:D1Database):Promise<Response>{
  await ensurePublicHistory(db);
  await db.prepare(`DELETE FROM rt_public_bets WHERE substr(race_id,1,10)<='2026-08-02'`).run();
  await db.prepare(`DELETE FROM rt_system_state WHERE state_key IN ('canonical_history_seed_complete','canonical_history_seed_count')`).run();
  return Response.json({ok:true,reset:true});
}

async function runChunk(db:D1Database,text:string):Promise<Response>{
  const hash=await sha256(text);if(!ALLOWED_CHUNK_HASHES.has(hash))return Response.json({ok:false,error:"UNVERIFIED_CHUNK"},{status:403});
  await ensurePublicHistory(db);
  const data=JSON.parse(text) as SeedChunk;let races=0,tickets=0;
  const statements:D1PreparedStatement[]=[];
  for(const [raceId,rows] of Object.entries(data)){
    const p=raceParts(raceId);
    if(!p||p.date>"2026-08-02"||!isFrozenSelectedRace(p.date,p.venue,p.raceNo))throw new Error(`INVALID_CANONICAL_RACE:${raceId}`);
    if(rows.length<3||rows.length>10)throw new Error(`INVALID_TICKET_COUNT:${raceId}`);
    const oddsBins=rows.map(r=>r[3]);
    const allocations=COURSES.map(([,u])=>allocation(oddsBins,u));
    const base=allocations[0];
    for(let i=0;i<rows.length;i+=1){if(base[i]*100!==Number(rows[i][4]))throw new Error(`BASE_ALLOCATION_MISMATCH:${raceId}:${i}`);}
    statements.push(db.prepare(`DELETE FROM rt_public_bets WHERE race_id=?`).bind(raceId));
    for(let c=0;c<COURSES.length;c+=1){
      const [course]=COURSES[c],units=allocations[c];
      for(let i=0;i<rows.length;i+=1){
        const [betType,combination,odds,_bin,_stake2000,payoutPer100]=rows[i];
        statements.push(db.prepare(`INSERT INTO rt_public_bets (race_id,course,bet_type,combination,stake_yen,assumed_odds,return_yen,settlement_status,locked_at,source_prediction_id) VALUES (?,?,?,?,?,?,?,'settled','canonical-frozen-history',-2)`).bind(raceId,course,betType,combination,units[i]*100,assumedOdds(odds),units[i]*Number(payoutPer100)));
      }
    }
    races+=1;tickets+=rows.length;
  }
  for(let i=0;i<statements.length;i+=40)await db.batch(statements.slice(i,i+40));
  await db.prepare(`INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES('canonical_history_seed_count',COALESCE((SELECT CAST(state_value AS INTEGER) FROM rt_system_state WHERE state_key='canonical_history_seed_count'),0)+?,CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value=CAST(CAST(state_value AS INTEGER)+? AS TEXT),updated_at=CURRENT_TIMESTAMP`).bind(races,races).run();
  return Response.json({ok:true,hash,races,tickets});
}

async function runFinalize(db:D1Database):Promise<Response>{
  await ensurePublicHistory(db);
  const rows=await db.prepare(`SELECT course,COUNT(DISTINCT race_id) AS races,SUM(stake_yen) AS stake,SUM(return_yen) AS ret FROM rt_public_bets WHERE settlement_status='settled' GROUP BY course ORDER BY CASE course WHEN 'ライト' THEN 1 WHEN 'スタンダード' THEN 2 ELSE 3 END`).all<{course:string;races:number;stake:number;ret:number}>();
  const expected=[['ライト',3225,6450000,22045350],['スタンダード',3225,16125000,55329590],['プレミアム',3225,32250000,110853150]] as const;
  const ok=expected.every((e,i)=>{const r=rows.results[i];return r&&r.course===e[0]&&Number(r.races)===e[1]&&Number(r.stake)===e[2]&&Number(r.ret)===e[3];});
  if(ok)await db.prepare(`INSERT INTO rt_system_state(state_key,state_value,updated_at) VALUES('canonical_history_seed_complete','1',CURRENT_TIMESTAMP) ON CONFLICT(state_key) DO UPDATE SET state_value='1',updated_at=CURRENT_TIMESTAMP`).run();
  return Response.json({ok,rows:rows.results,expected});
}

export async function handleCanonicalHistorySeed(request:Request,db:D1Database):Promise<Response|null>{
  const url=new URL(request.url);if(!url.pathname.startsWith('/internal/canonical-history/'))return null;
  if(request.method!=="POST")return new Response("METHOD_NOT_ALLOWED",{status:405});
  const text=await request.text();const hash=await sha256(text);
  if(url.pathname.endsWith('/reset'))return hash===RESET_HASH?runReset(db):new Response("FORBIDDEN",{status:403});
  if(url.pathname.endsWith('/chunk'))return runChunk(db,text);
  if(url.pathname.endsWith('/finalize'))return hash===FINAL_HASH?runFinalize(db):new Response("FORBIDDEN",{status:403});
  return new Response("NOT_FOUND",{status:404});
}
