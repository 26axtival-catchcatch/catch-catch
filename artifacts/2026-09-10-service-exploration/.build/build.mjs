import fs from 'node:fs/promises';
import path from 'node:path';
import {Presentation, PresentationFile} from '@oai/artifact-tool';
import {applyPresentationChartFont, finalizePresentation} from '/Users/jin/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations/container_tools/artifact_tool_utils.mjs';
const ROOT='/Users/jin/hackerthon/demo-1/artifacts/2026-09-10-service-exploration';
const SKILL='/Users/jin/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
const FONT='Apple SD Gothic Neo';
const C={bg:'#F7F8FA',ink:'#102A43',muted:'#52677D',navy:'#102A43',teal:'#087F8C',mint:'#83E1D0',orange:'#B5472A',peach:'#FCEDE8',line:'#D9E1E8',pale:'#E9F3F4',white:'#FFFFFF',blue:'#336EAC'};
const p=Presentation.create({slideSize:{width:1280,height:720}});
const copy=[];
const SOURCE='출처: 사용자 제공 「부가서비스 탐색 데이터 범위별 실제 실행 비교」, 2026-09-10. 형상 5473bda. 해커톤 합성 데이터. 첨부 원문: /Users/jin/.codex/attachments/854472b4-7618-428a-a444-3438b80d359a/pasted-text.txt';
function text(s,t,x,y,w,h,size=26,color=C.ink,bold=false,align='left'){
 const o=s.shapes.add({name:t.slice(0,42),geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 o.text=t;o.text.style={typeface:FONT,fontSize:size,color,bold,alignment:align,verticalAlignment:'top',autoFit:'none',wrap:'square',insets:{left:0,right:0,top:0,bottom:0}};
 copy.push(t);return o;
}
function slide(title,sub='',dark=false){const s=p.slides.add();s.background.fill=dark?C.navy:C.bg; const i=p.slides.items.length;
 if(title)text(s,title,64,49,1152,66,42,dark?C.white:C.ink,true);
 if(sub)text(s,sub,64,126,1144,62,24,dark?C.mint:C.muted);
 text(s,String(i).padStart(2,'0'),1167,677,48,24,15,dark?'#A9BDCE':C.muted,false,'right');return s;}
function note(s,t){s.speakerNotes.textFrame.setText(SOURCE+'\n\n'+t);}
function foot(s,t,dark=false){text(s,t,64,635,1104,38,18,dark?'#C7D7E3':C.muted);}
function table(s,vals,x,y,width,height,cols,opts={}){
 const t=s.tables.add({rows:vals.length,columns:vals[0].length,left:x,top:y,width,height,columnWidths:cols,values:vals});
 t.styleOptions={headerRow:false,bandedRows:false};
 t.borders.assign({fill:C.line,width:0.7,style:'solid'});
 for(let r=0;r<vals.length;r++)for(let c=0;c<vals[0].length;c++){
  const cell=t.getCell(r,c);cell.fill=r===0?C.navy:(opts.total&&r===vals.length-1?C.pale:C.white);
  cell.text.style={typeface:FONT,fontSize:r===0?(opts.headerSize||22):(opts.size||24),color:r===0?C.white:C.ink,bold:r===0||(opts.total&&r===vals.length-1),verticalAlignment:'middle',autoFit:'none',insets:{left:18,right:18,top:10,bottom:10}};
 }
 copy.push(...vals.flat().map(String));return t;
}
function chart(s,type,conf,dark=false){const ch=s.charts.add(type,{chartFill:'none',chartLine:{fill:'none',width:0},plotAreaFill:'none',plotAreaLine:{fill:'none',width:0},...conf});applyPresentationChartFont(ch,{fontFamily:FONT});return ch;}
const ax=(max)=>({min:0,max,visible:true,numberFormatCode:'0',textStyle:{typeface:FONT,fontSize:19,fill:C.muted},majorGridlines:{fill:C.line,width:0.6},line:{fill:'none',width:0}});
// 01
{
 const s=slide('','',true);
 text(s,'부가서비스 탐색',64,146,1110,86,72,C.white,true);
 text(s,'데이터 범위별 실제 실행 비교',64,247,1120,76,51,C.white,true);
 text(s,'검색과 상담에 앱 행동, 가입 정보를 더했을 때의 변화',67,374,1050,52,28,'#C7D7E3');
 text(s,'2026.09.10',67,571,360,40,24,C.mint);
 text(s,'실행 형상 5473bda',67,613,600,35,20,'#A9BDCE');
 note(s,'현재 형상으로 Backend와 Frontend를 재기동하고 같은 질문을 두 데이터 범위로 실행했습니다. 두 실행 모두 완료했습니다. 기대 수치는 재현했으나 확장 분석의 자동 추천은 가이드와 부분적으로 달랐습니다.');
}
// 02
{
 const s=slide('확장 분석은 오해를 줄였지만 핵심 지표를 놓쳤습니다','두 실행은 완료했습니다. 자동 추천 결과와 독립 측정 결과를 구분해 읽어야 합니다.');
 text(s,'59명',64,235,340,101,76,C.teal,true);
 text(s,'잘못된 이탈 추정 기각',64,349,340,43,29,C.ink,true);
 text(s,'상담이 없던 59명 모두\n목표 메뉴 도달 기록 확인',64,410,334,90,25,C.muted);
 text(s,'28.5%',458,235,340,101,76,C.ink,true);
 text(s,'메뉴 도달 미관측률',458,349,340,43,29,C.ink,true);
 text(s,'독립 측정으로 97/340명 확인\n모델의 최종 자동 추천에서 누락',458,410,342,96,25,C.muted);
 text(s,'16명',858,235,355,101,76,C.orange,true);
 text(s,'검색과 상담에도 미관측',858,349,355,43,29,C.ink,true);
 text(s,'메뉴 도달 미관측 97명 중 16명\n실제 조회/해지 의도는 미확인',858,410,355,96,25,C.muted);
 foot(s,'기존 해커톤 합성 데이터에서 확인한 결과입니다. 실제 해지 완료나 업무 해결 여부는 별도 확인이 필요합니다.');
 note(s,'59명 기각은 확장 분석의 독립 검증 성과입니다. 97/340=28.5294%, 16/97=16.4948%는 원시 CSV 연결과 현재 측정 함수로 별도 확인한 결과입니다. 독립 측정 결과는 모델 입력에 전달하지 않았고 시그널 등록도 실행하지 않았습니다.');
}
// 03
{
 const s=slide('비교 조건','질문과 모델은 같고, 직접 조회할 수 있는 데이터 범위를 달리했습니다.');
 table(s,[['조건','제한 분석','확장 분석'],['조회 데이터','검색 이력, VOC','검색 이력, VOC\n앱 행동, 부가서비스 가입 정보'],['관측 기간','2026.09.04 00:00 이상\n2026.09.11 00:00 미만, KST','동일'],['모델','Bedrock\n조사 Sonnet 4.6\n총괄/검증/보고 Opus 4.6','동일'],['직접 조회 규모','945개 이벤트, 2개 Source','7,996개 이벤트, 4개 Source']],64,205,1152,377,[224,454,474],{size:23});
 foot(s,'이벤트 수는 다른 주제를 포함한 기간 전체입니다. 부가서비스 관련 행은 모델이 직접 질의해 선택했습니다.');
 note(s,'두 요청은 같은 질문이며 기대 수치나 추가 탐색 지시를 넣지 않았습니다. 기존 등록 시그널 3개와 그 지식은 유지했습니다. find_signals는 선택 Source와 무관하게 기존 정의를 반환하며 앱 행동과 CTA 원인 표현을 포함합니다. 따라서 기존 시그널 지식을 가진 현재 서비스 상태의 재현 결과입니다. 직접 데이터 조회 Source와 기간 제한, 정답 라벨 마스킹을 별도 검증했습니다. 검색 피드백, 빌링, 로밍은 제외했습니다. 원문 참조 파일: limited-request.json, expanded-request.json.');
}
// 04
{
 const s=slide('제한 분석은 반복 검색 실패와 상담 부담을 포착했습니다','검색 이력과 VOC만 제공한 실행 결과');
 chart(s,'bar',{position:{left:60,top:211,width:724,height:335},categories:['실패 후 상담 유입','반복 검색 실패','검색 고객'],series:[{name:'고객 수',values:[61,120,180],fill:C.blue,points:[{idx:0,fill:C.teal},{idx:1,fill:C.blue},{idx:2,fill:'#B5CBE2'}]}],barOptions:{direction:'bar',grouping:'clustered',gapWidth:70},hasLegend:false,xAxis:{visible:true,textStyle:{fontSize:23,fill:C.ink},line:{fill:'none',width:0},majorGridlines:null},yAxis:ax(200),dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:25,fill:C.ink,bold:true}}});
 text(s,'66.7%',857,215,350,97,72,C.blue,true);
 text(s,'반복 검색 실패 120/180명',857,315,350,60,24,C.ink);
 text(s,'50.8%',857,403,350,80,54,C.teal,true);
 text(s,'실패 고객의 상담 전환 61/120명\n평균 상담 시간 330초',857,492,350,80,24,C.muted);
 foot(s,'상담 61명은 검색 고객 180명에 모두 포함됩니다. 가입자 모집단과 메뉴 도달 여부는 이 데이터만으로 확정할 수 없습니다.');
 note(s,'추천 API 후보는 3개입니다. 반복 검색 실패를 가리키는 후보 2개는 실제 SQL 고객 집합이 모두 같은 120명입니다. 별도 후보인 반복 검색 실패 후 VOC 미유입은 59/120=49.2%입니다. 모델은 잠재 미해결 또는 이탈 위험으로 설명했지만 실제 해결 상태는 미확인입니다. 상담 전환율은 61/120=50.8%이며 확장 자동 추천의 61/180=33.9%와 분모가 다릅니다. 원문 참조: limited-proposals.json, limited-report.md.');
}
// 05
{
 const s=slide('확장 분석의 자동 추천은 도달 고객과 상담 고객에 집중했습니다','최종 추천 API 후보 2개. 아래 이름은 관측 행동에 맞춰 정리했습니다.');
 table(s,[['실제 자동 추천 후보','서버 측정값','해석 범위'],['여러 메뉴를 경유한 뒤\n조회/해지 메뉴 도달','243/340명\n71.5%','경유 후 도달을 관측\n243명 전원의 헤맴은 미확정'],['부가서비스 검색 고객의\nVOC 상담 유입','61/180명\n33.9%','평균 상담 330초\n61명 중 40명은 메뉴에도 도달']],64,214,1152,256,[480,212,460],{size:25});
 text(s,'264명 = 243명 + 61명 − 40명',64,515,1152,58,39,C.ink,true);
 text(s,'보고서 상단의 확정 고객 수는 두 패턴의 합집합입니다.',64,577,1152,42,25,C.muted);
 foot(s,'제한 분석의 120명과 패턴 정의가 다르므로, 120명에서 264명으로 문제 규모가 증가했다고 해석할 수 없습니다.');
 note(s,'확장 보고서의 미확정 고객 120명도 확정 고객 264명과 겹치므로 더하지 않습니다. 모델이 생성한 원래 후보 이름과 설명은 expanded-proposals.json에 보존되어 있습니다. 독립 검증의 97명과 16명은 이번 자동 추천에 포함되지 않았습니다. 원문 참조: expanded-report.md, expanded-proposals.json.');
}
// 06
{
 const s=slide('확장 검증은 잘못된 이탈 추정을 걸러냈습니다','메뉴 도달 기록을 결합해 조사 단계의 주장을 다시 확인했습니다.');
 text(s,'59명',64,222,520,90,72,C.teal,true);
 text(s,'이탈 추정 기각',64,324,518,52,34,C.ink,true);
 text(s,'반복 검색 실패 후 상담이 없던 고객\n59명 전원에게 목표 메뉴 도달 기록이\n있었습니다.',64,399,514,135,28,C.muted);
 text(s,'99명 / 120명',681,232,535,80,55,C.orange,true);
 text(s,'메뉴 미도달 주장 보류',681,324,535,52,34,C.ink,true);
 text(s,'검색 failed 120명 중 99명이\n메뉴에 도달했습니다. 검증자는\n후보를 미확정으로 남겼습니다.',681,399,535,135,28,C.muted);
 foot(s,'오른쪽 미확정 후보는 최종 추천 API에서 제외됐습니다. 메뉴 도달은 실제 해지 완료와 구분해야 합니다.');
 note(s,'제한 데이터의 59명은 반복 검색 실패 후 VOC가 없어 잠재 미해결로 설명됐습니다. 확장 데이터에서 모두 메뉴 도달 기록을 확인해 이탈 후보를 기각했습니다. 120명 메뉴 미도달 주장은 정상 비교군 설명이 실제 행동과 다르다는 이유로 미확정 처리했습니다.');
}
// 07
{
 const s=slide('활성 탐색 고객 340명 중 97명은 메뉴 도달 기록이 없습니다','독립 측정 결과. 모델의 최종 자동 추천에는 포함되지 않았습니다.',true);
 chart(s,'doughnut',{position:{left:78,top:212,width:500,height:379},categories:['메뉴 도달','도달 미관측'],series:[{name:'고객 수',values:[243,97],points:[{idx:0,fill:'#34516B'},{idx:1,fill:C.mint}],line:{fill:C.navy,width:2}}],hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:24,fill:C.white}},doughnutOptions:{holeSize:73,firstSliceAngle:270},dataLabels:{showValue:true,textStyle:{fontSize:28,bold:true,fill:C.white}}},true);
 text(s,'28.5%',685,222,510,111,88,C.mint,true);
 text(s,'97명 / 관측한 활성 탐색 고객 340명',685,346,522,60,27,C.white);
 text(s,'이 중 16명은\n검색과 VOC에도 나타나지 않습니다.',685,450,530,103,31,C.white,true);
 foot(s,'분모는 기간 내 활성 가입 기록과 앱 menu_view가 있는 고객입니다. 16명의 실제 조회/해지 의도는 미확인입니다.',true);
 note(s,'분모: 관측 기간에 부가서비스 활성 가입 기록 action=A, outcome=Y가 있고 앱 menu_view가 있는 고객 340명. 분자: 이들 중 해당 기간 부가서비스 조회/해지 메뉴 방문이 없는 고객 97명. 97/340=28.5294%. 서비스 전체 가입자 또는 조회/해지 의도가 확인된 고객 전체로 일반화하면 안 됩니다. 원시 CSV 연결과 InvestigationData.load → measure_definition 경로로 별도 확인했습니다. 이 결과는 모델 입력에 전달하지 않았고 시그널도 등록하지 않았습니다. 참조: independent-counts.json, recommended-signal.json.');
}
// 08
{
 const s=slide('메뉴 도달 미관측 고객의 16.5%는 지원 채널에도 없습니다','활성 가입과 앱 탐색 고객 340명의 채널 관측 및 메뉴 도달 교차 집계');
 table(s,[['해당 주간 지원 채널 관측','고객','메뉴 도달','도달 미관측'],['검색과 VOC 모두 관측','61','40','21'],['검색만 관측','119','59','60'],['검색과 VOC 모두 미관측','160','144','16'],['합계','340','243','97']],64,220,1152,318,[540,174,214,224],{size:26,total:true});
 text(s,'16 / 97명 = 16.5%',64,565,502,58,36,C.orange,true);
 text(s,'지원 채널 데이터만으로 이 고객군의\n탐색 상태를 파악하기 어렵습니다.',607,567,609,64,25,C.muted);
 note(s,'모든 VOC 상담 고객은 검색 고객과 겹칩니다. 검색과 상담으로 관측하는 메뉴 미도달 고객은 21+60=81명이고 16명이 빠집니다. 16/97=16.4948%입니다. 16명에게는 검색어, 상담, 목표 메뉴 방문이 모두 없어 조회나 해지가 실제 목적이었는지 확인되지 않습니다. 활성 가입과 일반 메뉴 탐색 기록만으로 전원을 조회/해지 실패 고객으로 확정할 수 없습니다. 참조: channel-navigation-comparison.json.');
}
// 09
{
 const s=slide('검색 상태는 메뉴 도달이나 해지 완료를 대신하지 못합니다','검색 completed 60명에게는 메뉴 도달 기록이 없고, failed 120명 중 99명에게는 있습니다.');
 chart(s,'bar',{position:{left:60,top:218,width:751,height:340},categories:['반복 검색 failed','검색 completed'],series:[{name:'메뉴 도달',values:[99,0],fill:C.teal,dataLabelOverrides:[{idx:0,showValue:true,position:'center',textStyle:{typeface:FONT,fontSize:25,fill:C.ink,bold:true}},{idx:1,showValue:false}]},{name:'도달 미관측',values:[21,60],fill:'#C8D4DF'}],barOptions:{direction:'bar',grouping:'stacked',gapWidth:95,overlap:100},hasLegend:true,legend:{position:'bottom',textStyle:{fontSize:23,fill:C.muted}},xAxis:{visible:true,textStyle:{fontSize:23,fill:C.ink},line:{fill:'none',width:0},majorGridlines:null},yAxis:ax(120),dataLabels:{showValue:true,position:'center',textStyle:{fontSize:25,fill:C.ink,bold:true}}});
 text(s,'99명 전원',876,250,340,65,45,C.teal,true);
 text(s,'첫 검색 이전에\n메뉴 도달 기록 확인',876,335,340,111,30,C.ink,true);
 text(s,'검색이 메뉴 도달을\n유발했다는 근거는 없습니다.',876,471,340,89,25,C.muted);
 foot(s,'검색 상태, 메뉴 도달, 최종 업무 해결은 각각 별도의 관측값입니다.');
 note(s,'원시 발생 시각으로 failed 고객 중 메뉴 도달 99명 전원이 첫 검색보다 먼저 메뉴에 도달했음을 확인했습니다. 따라서 검색이 도달을 유발했다고 설명할 근거가 없습니다. 참조: navigation-search-timing.json.');
}
// 10
{
 const s=slide('사용자에게 권고할 지표','확장 지표 2개는 원문의 별도 권고이며, 이번 모델의 자동 추천과 구분됩니다.');
 table(s,[['범위와 우선순위','권고 지표','현재 값'],['제한, 기본','부가서비스 조회/해지\n반복 검색 실패율','120/180명\n66.7%'],['제한, 보조','반복 검색 실패 고객의\n상담 전환율','61/120명\n50.8%'],['확장, 우선','활성 부가서비스 탐색 고객의\n조회/해지 메뉴 도달 미관측률','97/340명\n28.53%'],['확장, 보조','메뉴 도달 미관측 고객 중\n검색과 VOC에도 없는 고객 수','16명\n97명 중 16.5%']],64,210,1152,402,[238,637,277],{size:24});
 foot(s,'상담 전환은 상담 부담을, 메뉴 도달 미관측은 관측 공백을 나타냅니다. 실제 해결 여부는 별도 확인이 필요합니다.');
 note(s,'제한 기본 지표는 검색 단계에서 동일 의도를 다시 시도하는 고객 규모입니다. 보조 지표의 평균 상담 시간은 330초입니다. 확장 우선 지표의 정확한 분모는 기간 내 action=A, outcome=Y의 활성 가입 기록과 menu_view가 있는 고객입니다. 분자는 목표 부가서비스 조회/해지 메뉴 방문이 없는 고객입니다. 16명은 지원 채널 지표에 나타나지 않는 고객군이며 실제 목적은 추가 확인이 필요합니다. 권고 시그널은 독립 정의와 측정 결과이며 등록하지 않았습니다. 참조: recommended-signal.json, measure_recommended.py.');
}
// 11
{
 const s=slide('자동 추천 품질의 보완 과제','수치 재현과 후보의 이름, 비교군, 원인 설명은 별도로 검증해야 합니다.');
 const rows=[
 ['01','핵심 발견 누락','97/340명과 16명을 자동 추천에서 놓쳤습니다.\n활성 탐색 모집단에서 미도달 고객을 찾는 탐색이 필요합니다.'],
 ['02','정상 비교군 오류','미도달 97명 중 81명은 검색했고, 21명은 해지 상담을 했습니다.\n다른 목적의 정상 고객이라는 설명을 다시 검증해야 합니다.'],
 ['03','CTA 원인 단정','화면, CTA 노출과 클릭, 실험 근거가 없습니다.\n관측 행동과 원인 가설을 구분해야 합니다.'],
 ['04','중복 및 정의 불일치','제한 후보 2개의 고객 집합이 같습니다. 확장 후보 SQL은\n제목의 세션 내 순서와 반복 횟수를 직접 고정하지 않습니다.']];
 rows.forEach((r,i)=>{const y=212+i*98;text(s,r[0],64,y,70,48,31,C.teal,true);text(s,r[1],159,y,295,55,29,C.ink,true);text(s,r[2],465,y,749,77,24,C.muted);});
 note(s,'정상군으로 둔 다른 144명도 같은 반복 메뉴 경로를 거쳤습니다. 243명 전원의 경유 행동을 확정적 헤맴으로 표시할 근거가 부족합니다. 확장 메뉴 후보 SQL은 기간 내 메뉴 존재 여부 조합이며 세션 내 순서와 반복 횟수를 직접 조건으로 고정하지 않습니다. 두 보고서 제목과 일부 후보 이름은 CTA 부재를 원인으로 표현하지만 화면 증거와 실험 근거가 없고 같은 템플릿에서 검색 상태도 다릅니다. 장기 모니터링 전 후보 제목과 SQL 조건을 맞춰야 합니다.');
}
// 12
{
 const s=slide('사용자에게 전달할 인사이트','',true);
 text(s,'관측한 활성 부가서비스 고객 340명 중\n97명은 앱 메뉴를 탐색했지만\n조회/해지 메뉴 도달 기록이 없습니다.',64,189,1152,210,44,C.white,true);
 text(s,'이 중 16명은 검색과 상담에도 나타나지 않아\n지원 채널 데이터만으로 탐색 상태를 파악하기 어렵습니다.',64,447,1152,100,30,C.mint);
 foot(s,'16명의 실제 조회/해지 의도와 최종 업무 해결 여부는 추가 확인이 필요합니다.',true);
 note(s,'원문에서 권고한 사용자 설명을 발표용으로 재구성했습니다. 이는 독립 검증 결과를 바탕으로 한 적절한 설명 수준이며 이번 모델이 자동 생성한 최종 추천으로 소개하면 안 됩니다. 이번 확장 실행은 잘못된 이탈 추정을 기각하는 데 성공했지만 핵심 미도달 지표 발견과 최종 표현 검증에는 보완이 필요합니다.');
}
// 13
{
 const s=slide('부록 1. 고객 수와 비율의 분모','같은 숫자라도 집합과 분모를 먼저 확인해야 합니다.');
 table(s,[['구분','계산','해석'],['상담 전환율, 제한 보조','61/120명 = 50.8%','반복 검색 실패 고객이 분모'],['상담 유입률, 확장 자동 추천','61/180명 = 33.9%','전체 검색 고객이 분모'],['확장 보고 확정 고객','243 + 61 − 40 = 264명','메뉴 경유 도달과 상담 고객의 합집합'],['지원 채널에 없는 고객 비중','16/97명 = 16.5%','메뉴 도달 미관측 고객이 분모']],64,215,1152,319,[410,340,402],{size:23});
 text(s,'제한 120명과 확장 264명은 서로 다른 패턴의 고객 집합입니다.',64,568,1152,47,28,C.ink,true);
 foot(s,'검색 180명과 상담 61명은 더하지 않습니다. 확장 미확정 120명도 확정 264명과 겹치므로 더하지 않습니다.');
 note(s,'59/120=49.1667%는 반복 검색 실패 후 VOC 미유입률입니다. 120/180=66.6667%, 243/340=71.4706%, 61/180=33.8889%, 61/120=50.8333%, 97/340=28.5294%, 16/97=16.4948%. 표시 정밀도는 원문에 맞췄습니다.');
}
// 14
{
 const s=slide('부록 2. 실행 규모와 소요 시간','동일 모델로 성공한 순차 재시도를 비교했습니다.');
 table(s,[['항목','제한 분석','확장 분석'],['완료 시간','약 5분 44초','약 11분 24초'],['실제 조회','945개 이벤트, 2개 Source','7,996개 이벤트, 4개 Source'],['역할 실행 횟수','총괄 1, 조사 3\n검증 3, 보고 1','총괄 1, 조사 3\n검증 4, 보고 1'],['SQL 질의','116개','177개'],['추천 API 후보','3개\n그중 2개의 고객 집합 동일','2개']],64,201,1152,394,[292,430,430],{size:24});
 foot(s,'초기 동시 실행 2건은 일부 응답이 10분 이상 대기해 중단했습니다. 코드, 데이터 시딩, 모델 설정은 비교 중 유지했습니다.');
 note(s,'초기 동시 실행 두 건의 기록을 보존하고 중단했습니다. 같은 모델의 짧은 확인 호출은 2~3초에 성공했고 서버 재시작 후 순차 실행한 두 건은 완료했습니다. 시간은 성공한 재시도 기준이므로 보편적인 지연시간 기준으로 해석하지 않습니다.');
}
// 15
{
 const s=slide('부록 3. 검증 범위와 재현 근거','실행과 측정 검증을 마쳤으며, 서술상의 오류는 별도로 평가했습니다.');
 text(s,'검증한 항목',64,211,510,49,31,C.ink,true);
 text(s,'완료 상태와 요청 동일성\nSource 및 기간 제한, 정답 라벨 마스킹\nSSE 완료와 재연결, 다운로드\n추천 SQL의 고객 수',64,278,564,161,25,C.muted);
 text(s,'해석할 때의 조건',685,211,530,49,31,C.ink,true);
 text(s,'기존 등록 시그널 3개의 지식 유지\n독립 측정값은 모델 입력에 미전달\n권고 시그널 등록은 미실행\n기존 해커톤 합성 데이터로 실행',685,278,530,161,25,C.muted);
 text(s,'제한 Run ID',64,505,170,37,20,C.muted,true);
 text(s,'cd9ec858-c7b7-4bcd-8143-d69398fc7111',256,505,936,39,23,C.ink);
 text(s,'확장 Run ID',64,554,170,37,20,C.muted,true);
 text(s,'0eb99d5a-b720-42d5-a46a-add08e0363a6',256,554,936,39,23,C.ink);
 foot(s,'근거 파일명과 세부 조건은 발표자 노트에 정리했습니다.');
 note(s,'원문에서 제시한 근거와 재현 파일 목록입니다. 이 프레젠테이션은 제공된 보고서 내용을 요약합니다.\n제한: limited-request.json, limited-report.md, limited-proposals.json, limited-validation.json.\n확장: expanded-request.json, expanded-report.md, expanded-proposals.json, expanded-validation.json.\n독립 집계: independent-counts.json, channel-navigation-comparison.json, navigation-search-timing.json.\n권고 정의와 측정: recommended-signal.json.\n재현 스크립트: run_comparison.py, validate_run.py, measure_recommended.py.\n기존 등록 시그널 3개를 유지했으며 find_signals는 Source 선택과 무관하게 정의를 반환합니다. 기존 정의에는 앱 행동과 CTA 원인 표현이 있습니다. 직접 조회의 Source와 기간 제한 및 평가용 정답 라벨 마스킹은 별도 확인했습니다.');
}
await fs.writeFile(path.join(ROOT,'.build','slide-copy.txt'),copy.join('\n'));
await fs.writeFile(path.join(ROOT,'.build','presentation.json'),JSON.stringify(p.toProto()));
const candidate=path.join(ROOT,'.build','candidate.pptx');
await (await PresentationFile.exportPptx(p)).save(candidate);
console.log('DRAFT_EXPORTED',candidate);
const previews=path.join(ROOT,'.build','draft-previews');await fs.mkdir(previews,{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i]; const b=await p.export({slide:s,format:'png',scale:1});
 await fs.writeFile(path.join(previews,`slide-${i+1}.png`),new Uint8Array(await b.arrayBuffer()));
 console.log('RENDERED',i+1);
}
const finalPath=path.join(ROOT,'output','부가서비스_탐색_실행_비교_발표자료.pptx');
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath,pythonExecutable:'/Users/jin/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',integrityValidatorPath:path.join(SKILL,'container_tools','inspect_presentation_package_integrity.py'),layoutValidatorPath:path.join(SKILL,'container_tools','inspect_presentation_layout_geometry.py'),layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...[3,5,8,10,13,14].flatMap(n=>['--require-native-table-slide',String(n)])],tableArithmeticContracts:[{slide:8,table:1,label_column:0,total_row:4,value_columns:[1,2,3],component_rows:[1,2,3]}],requiredNativeTableOwnerSlides:[3,5,8,10,13,14],requiredNativeChartOwnerSlides:[4,7,9],materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[FONT]},verifyArtifactToolImport:true,receiptPath:path.join(ROOT,'.build','validation-v2.json')});
console.log(JSON.stringify(result,null,2));
