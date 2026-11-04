import assert from "node:assert/strict";
import { solution } from "./solution.ts";

type R = Record<string, unknown>;
const trace = ["normalised", "validated", "holiday-filter", "hours-and-lunch", "notice", "doctor-availability", "daily-cap", "booking-conflicts", "urgent-priority", "earliest-grid-slot"];
const doctor = (name: unknown = "Ada", windows: R[] = [0, 1, 2, 3, 4].map((weekday) => ({ weekday, open: 540, close: 1020 }))) => ({ name, windows });
const base = (updates: R = {}): R => ({ now_day: 100, now_minute: 480, requested_day: 100, horizon_days: 2, kind: "checkup", urgent: false, preferred_doctor: "", holidays: [], doctors: [doctor()], bookings: [], ...updates });
const success = (day: number, start: number, end: number, name = "Ada") => ({ day, start, end, doctor: name, trace });
const failure = (error: string, index: number | null = null) => ({ error, index });

// Independent validation and exhaustive day/doctor/grid enumeration.
function oracle(input: R): R {
  const kind = typeof input.kind === "string" ? input.kind.trim().toLowerCase() : input.kind;
  const pref = typeof input.preferred_doctor === "string" ? input.preferred_doctor.trim() : input.preferred_doctor;
  const names = (input.doctors as R[]).map((d) => typeof d.name === "string" ? d.name.trim() : d.name);
  const key = (v: unknown) => typeof v === "string" ? v.trim().toLowerCase() : "";
  const integer = (v: unknown, low: number, high: number) => typeof v === "number" && Number.isInteger(v) && v >= low && v <= high;
  if (!integer(input.now_day,0,1_000_000) || !integer(input.now_minute,0,1439) || !integer(input.requested_day,0,1_000_000) || !integer(input.horizon_days,0,14) || typeof input.urgent !== "boolean" || !(kind === "checkup" || kind === "consultation" || kind === "procedure") || typeof pref !== "string") return failure("BAD_REQUEST");
  const ds = input.doctors as R[];
  if (ds.length < 1 || ds.length > 12) return failure("BAD_DOCTORS");
  const seen = new Set<string>();
  for (let i = 0; i < ds.length; i++) { const n = names[i]; if (typeof n !== "string" || !/^[A-Za-z0-9 -]+$/.test(n) || !n || seen.has(key(n))) return failure("BAD_DOCTORS",i); seen.add(key(n)); }
  for (let i = 0; i < ds.length; i++) { const ws = ds[i].windows as R[]; if (ws.length > 8 || ws.some((w) => !integer(w.weekday,0,6) || !integer(w.open,0,1440) || !integer(w.close,0,1440) || (w.open as number) >= (w.close as number))) return failure("BAD_WINDOW",i); }
  const holidays = input.holidays as unknown[]; if (holidays.length > 60) return failure("BAD_HOLIDAY");
  const holidaySet = new Set<number>(); for (let i=0;i<holidays.length;i++) { const d=holidays[i]; if (!integer(d,0,1_000_000) || holidaySet.has(d as number)) return failure("BAD_HOLIDAY",i); holidaySet.add(d as number); }
  const bs = input.bookings as R[]; if (bs.length > 200) return failure("BAD_BOOKING");
  for (let i=0;i<bs.length;i++) { const b=bs[i]; if (!integer(b.day,0,1_000_000) || !integer(b.start,0,1440) || !integer(b.end,0,1440) || (b.start as number) >= (b.end as number) || typeof b.doctor !== "string" || !seen.has(key(b.doctor))) return failure("BAD_BOOKING",i); }
  if (pref && !seen.has(key(pref))) return failure("UNKNOWN_DOCTOR");
  if ((input.requested_day as number) < (input.now_day as number) || (input.requested_day as number) > (input.now_day as number) + 8) return failure("BAD_DAY_ORDER");
  const sizes: Record<string, [number,number]> = { checkup:[20,5], consultation:[30,10], procedure:[60,15] };
  const [duration, buffer] = sizes[kind as string]; const last=Math.min((input.requested_day as number)+(input.horizon_days as number),(input.requested_day as number)+14,1_000_000);
  const choices: {day:number;start:number;end:number;name:string;key:string}[]=[];
  for(let day=input.requested_day as number;day<=last;day++) for(let di=0;di<ds.length;di++) for(let start=0;start<=1435;start+=5) {
    if(holidaySet.has(day)) continue;
    const name=names[di] as string, doctorKey=key(name);
    if(input.urgent===false && pref && doctorKey!==key(pref)) continue;
    const weekday=day%7, open=weekday===5?600:weekday===6?0:540, close=weekday===5?840:weekday===6?0:1020, occupied=start+duration+buffer;
    if(start<open || occupied>close || (start<780 && occupied>720)) continue;
    if(day===input.now_day && start<(input.now_minute as number)+60) continue;
    const windows=ds[di].windows as R[];
    if(!windows.some((w)=>w.weekday===weekday && (w.open as number)<=start && occupied<=(w.close as number))) continue;
    const daily=bs.filter((b)=>b.day===day && key(b.doctor)===doctorKey);
    if(daily.length>=4 || daily.some((b)=>start<(b.end as number) && (b.start as number)<occupied)) continue;
    choices.push({day,start,end:start+duration,name,key:doctorKey});
  }
  choices.sort((a,b)=>a.day-b.day || a.start-b.start || (a.key<b.key?-1:a.key>b.key?1:0));
  const first=choices[0]; return first ? success(first.day,first.start,first.end,first.name) : failure("NO_SLOT");
}
function check(input: R, expected: R = oracle(input)): void { assert.deepStrictEqual(solution(input), expected, JSON.stringify(input)); }

const worked: [R,R][] = [
  [base(),success(100,540,560)],
  [base({kind:"  CONSULTATION  "}),success(100,540,570)],
  [base({now_minute:500}),success(100,560,580)],
  [base({now_minute:1000}),success(101,540,560)],
  [base({kind:"consultation"}),success(100,540,570)],
  [base({kind:"procedure"}),success(100,540,600)],
  [base({doctors:[doctor("  Ada  ",[{weekday:2,open:600,close:660}])] }),success(100,600,620)],
  [base({doctors:[doctor("Ada",[{weekday:2,open:700,close:840}])] }),success(100,780,800)],
  [base({bookings:[{day:100,start:540,end:570,doctor:"  ADA  "}]}),success(100,570,590)],
  [base({bookings:[{day:100,start:540,end:565,doctor:"Ada"}]}),success(100,565,585)],
  [base({bookings:[540,560,580,600].map((start)=>({day:100,start,end:start+10,doctor:"Ada"}))}),success(101,540,560)],
  [base({holidays:[100]}),success(101,540,560)],
  [base({doctors:[doctor("Bo"),doctor("Ada")] }),success(100,540,560)],
  [base({kind:"checkup",now_day:-1}),failure("BAD_REQUEST")],
  [base({doctors:[]}),failure("BAD_DOCTORS")],
  [base({doctors:[doctor("Ada",[{weekday:7,open:540,close:600}]),doctor(" ada ",[])]}),failure("BAD_DOCTORS",1)],
  [base({doctors:[doctor("Ada",[]),doctor("Bo",[]),doctor("Cy",[{weekday:2,open:900,close:900}])]}),failure("BAD_WINDOW",2)],
  [base({holidays:[100,100]}),failure("BAD_HOLIDAY",1)],
  [base({bookings:[{day:100,start:540,end:550,doctor:"Ada"},{day:100,start:540,end:540,doctor:"Ada"}]}),failure("BAD_BOOKING",1)],
  [base({bookings:[{day:100,start:540,end:550,doctor:"Ada"},{day:100,start:550,end:560,doctor:"Ada"},{day:100,start:560,end:560,doctor:"Ada"}]}),failure("BAD_BOOKING",2)],
  [base({holidays:[-1],bookings:[{day:100,start:540,end:540,doctor:"Ada"}]}),failure("BAD_HOLIDAY",0)],
  [base({preferred_doctor:"Bo"}),failure("UNKNOWN_DOCTOR")],
  [base({requested_day:99}),failure("BAD_DAY_ORDER")],
  [base({requested_day:109}),failure("BAD_DAY_ORDER")],
  [base({preferred_doctor:"Bo",requested_day:109}),failure("UNKNOWN_DOCTOR")],
  [base({kind:"other",doctors:[]}),failure("BAD_REQUEST")],
  [base({holidays:[-1],bookings:[{day:100,start:540,end:540,doctor:"Ada"}]}),failure("BAD_HOLIDAY",0)],
  [base({bookings:[{day:100,start:540,end:550,doctor:null}]}),failure("BAD_BOOKING",0)],
  [base({bookings:[{day:100,start:540,end:550,doctor:"Unknown"}]}),failure("BAD_BOOKING",0)],
  [base({bookings:[{day:100,start:540,end:550,doctor:"Ada"},{day:100,start:550,end:560,doctor:"Ada"},{day:100,start:560,end:560,doctor:"Ada"}]}),failure("BAD_BOOKING",2)],
  [base({doctors:[doctor("Ada",[]),doctor("ada",[])],holidays:[-1]}),failure("BAD_DOCTORS",1)],
  [base({holidays:[-1],doctors:[doctor("Ada",[{weekday:7,open:540,close:600}])]}),failure("BAD_WINDOW",0)],
  [base({bookings:[{day:100,start:1,end:1,doctor:"Ada"}],preferred_doctor:"Bo"}),failure("BAD_BOOKING",0)],
  [base({doctors:[doctor("Ada",[{weekday:1,open:540,close:1020}])] }),failure("NO_SLOT")],
  [base({now_day:100,now_minute:1000,requested_day:100}),success(101,540,560)],
  [base({now_minute:481}),success(100,545,565)],
  [base({horizon_days:0,holidays:[100]}),failure("NO_SLOT")],
  [base({now_day:0,now_minute:0,requested_day:0,horizon_days:0}),success(0,540,560)],
  [base({doctors:[doctor("Ada",[])]}),failure("NO_SLOT")],
  [base({now_day:100,requested_day:108,horizon_days:0}),success(108,540,560)],
  [base({requested_day:103,horizon_days:0,doctors:[doctor("Ada",[{weekday:5,open:600,close:840}])] }),success(103,600,620)],
  [base({doctors:[doctor("Ada",[{weekday:2,open:540,close:565}])] }),success(100,540,560)],
  [base({horizon_days:0,doctors:[doctor("Ada",[{weekday:2,open:540,close:564}])] }),failure("NO_SLOT")],
  [base({horizon_days:0,doctors:[doctor("Ada",[{weekday:2,open:800,close:900}])],bookings:[540,560,580,600].map((start)=>({day:100,start,end:start+10,doctor:"Ada"}))}),failure("NO_SLOT")],
  [base({doctors:[doctor("Ada",[{weekday:2,open:995,close:1020}])] }),success(100,995,1015)],
  [base({bookings:[{day:100,start:540,end:695,doctor:"Ada"}]}),success(100,695,715)],
  [base({doctors:[doctor("zoe"),doctor("ada")] }),success(100,540,560,"ada")],
  [base({preferred_doctor:"Bo",urgent:true,doctors:[doctor("Bo"),doctor("Ada")] }),success(100,540,560,"Ada")],
];
for (const [input, expected] of worked) check(input,expected);

for (const value of [null,"a",true,5.5]) for (const field of ["now_day","now_minute","requested_day","horizon_days"]) check(base({[field]:value}),failure("BAD_REQUEST"));
for (const request of [base({kind:42}),base({urgent:1}),base({preferred_doctor:null}),base({doctors:[doctor(null,[])]}),base({doctors:[doctor("Ada@")] }),base({doctors:Array.from({length:13},(_,i)=>doctor(`D${i}`,[]))}),base({horizon_days:15}),base({now_minute:1440}),base({requested_day:1000001}),base({holidays:Array(61).fill(1)}),base({bookings:Array.from({length:201},(_,i)=>({day:i,start:0,end:1,doctor:"Ada"}))}),base({doctors:[doctor("Ada",Array(9).fill({weekday:2,open:540,close:600}))]})]) check(request);
for (const [minute, expected] of [[599,null],[600,success(100,600,620)],[655,success(100,655,675)]] as [number,R|null][]) {
  const input=base({doctors:[doctor("Ada",[{weekday:2,open:minute,close:685}])]}); check(input,expected ?? oracle(input));
}
for (const [field,value] of [["now_day",null],["now_day","a"],["now_day",true],["requested_day",null],["requested_day","a"],["requested_day",true]]) check(base({[field]:value}),failure("BAD_REQUEST"));
check(base({requested_day:1000000,now_day:999992,horizon_days:14}),success(1000000,540,560));
check(base({horizon_days:0}),success(100,540,560));
check(base({horizon_days:14,holidays:Array.from({length:14},(_,i)=>100+i)}),success(114,540,560));
check(base({now_minute:500}),success(100,560,580));
check(base({doctors:[doctor("Ada",[{weekday:2,open:780,close:805}])] }),success(100,780,800));
check(base({doctors:[doctor("Ada",[{weekday:2,open:815,close:840}])] }),success(100,815,835));
check(base({now_day:103,requested_day:103,horizon_days:0,doctors:[doctor("Ada",[{weekday:5,open:815,close:840}])] }),success(103,815,835));
check(base({doctors:[doctor("Ada",[{weekday:2,open:600,close:625}])] }),success(100,600,620));
check(base({doctors:[doctor("Ada",[{weekday:2,open:995,close:1020}])] }),success(100,995,1015));
check(base({doctors:[doctor("Ada",[{weekday:2,open:540,close:1441}])]}),failure("BAD_WINDOW",0));
check(base({bookings:[{day:100,start:540,end:1441,doctor:"Ada"}]}),failure("BAD_BOOKING",0));
check(base({holidays:[1000001]}),failure("BAD_HOLIDAY",0));
check(base({doctors:[doctor("Ada",Array(8).fill({weekday:2,open:540,close:1020}))]}),success(100,540,560));
check(base({doctors:Array.from({length:12},(_,i)=>doctor(`Doc ${i}`))}),success(100,540,560,"Doc 0"));
check(base({holidays:Array.from({length:60},(_,i)=>200+i)}),success(100,540,560));
check(base({bookings:Array.from({length:200},(_,i)=>({day:500+i,start:0,end:1,doctor:"Ada"}))}),success(100,540,560));
check(base({preferred_doctor:" ada "}),success(100,540,560));
check(base({preferred_doctor:"   "}),success(100,540,560));
check(base({now_minute:1439}),success(101,540,560));
check(base({horizon_days:0,doctors:[doctor("Ada",[{weekday:2,open:575,close:600}])],bookings:[{day:100,start:550,end:575,doctor:"Ada"}]}),success(100,575,595));
check(base({bookings:[{day:100,start:565,end:575,doctor:"Ada"}]}),success(100,540,560));
check(base({preferred_doctor:"Bo",urgent:false,doctors:[doctor("Bo"),doctor("Ada")]}),success(100,540,560,"Bo"));

let state=731904; const random=(limit:number)=>{state=(Math.imul(state,1664525)+1013904223)>>>0;return state%limit;};
const kinds=["checkup","consultation","procedure"], people=["Ada","Bo","Cy"];
let valid=0, invalid=0;
for(let i=0;i<2000;i++){
  const now=random(900)+20, offset=random(9), horizon=random(15), names=people.slice(0,random(3)+1);
  const doctors=names.map((name)=>doctor(name,Array.from({length:7},(_,weekday)=>weekday).filter(()=>random(4)!==0).map((weekday)=>({weekday,open:weekday===5?600:540,close:weekday===5?840:1020}))));
  const bookings=Array.from({length:random(17)},()=>{const start=540+random(84)*5;return {day:now+offset+random(horizon+1),start,end:Math.min(start+[10,20,30,60][random(4)],1440),doctor:names[random(names.length)]};});
  if(random(3)===0){const cappedDay=now+offset+random(horizon+1), cappedName=names[random(names.length)];for(let index=0;index<4;index++)bookings.push({day:cappedDay,start:index,end:index+1,doctor:cappedName});}
  const input=base({now_day:now,now_minute:random(1440),requested_day:now+offset,horizon_days:horizon,kind:kinds[random(3)],urgent:random(2)===1,preferred_doctor:["","Ada","Bo"][random(3)],holidays:Array.from(new Set(Array.from({length:random(4)},()=>now+offset+random(horizon+1)))),doctors,bookings});
  check(input); if (oracle(input).error) invalid++; else valid++;
}
if (valid < 1000) throw new Error(`valid random mix too small: ${valid}`);
console.log(`clinic-booking: ${worked.length} hand cases, ${valid} valid and ${invalid} invalid seeded requests passed`);
