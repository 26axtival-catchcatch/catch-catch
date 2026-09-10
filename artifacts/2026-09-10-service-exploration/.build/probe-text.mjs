import {FileBlob,PresentationFile} from '@oai/artifact-tool';
const p=await PresentationFile.importPptx(await FileBlob.load('/Users/jin/hackerthon/demo-1/artifacts/2026-09-10-service-exploration/output/부가서비스_탐색_실행_비교_발표자료.pptx'));
const x=await p.inspect({kind:'textbox',maxChars:100000});
const r=x.ndjson.split('\n').filter(Boolean).map(JSON.parse).find(x=>x.slide===2&&x.text.includes('상담이 없던'));
const o=p.resolve(r.id);for(const prop of ['fontSize','bold','color','typeface','alignment','insets','autoFit']){console.log(prop,JSON.stringify(o.text[prop]));}
o.text='바꾼 첫 줄입니다.\n바꾼 둘째 줄입니다.';
for(const prop of ['fontSize','bold','color','typeface','alignment','insets','autoFit']){console.log('after',prop,JSON.stringify(o.text[prop]));}
