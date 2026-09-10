from zipfile import ZipFile, ZIP_DEFLATED
from pathlib import Path
from io import BytesIO
from copy import deepcopy
from lxml import etree
import openpyxl
import sys
source,candidate,output=map(Path,sys.argv[1:])
N={'c':'http://schemas.openxmlformats.org/drawingml/2006/chart'}
labels={'실패 후 상담 유입':'그 뒤 상담한 고객','반복 검색 실패':'반복 검색 ‘실패’','검색 고객':'검색한 고객','메뉴 도달':'메뉴 기록 있음','도달 미관측':'메뉴 기록 없음','반복 검색 failed':'반복 검색 ‘실패’','검색 completed':'검색 ‘완료’','Category':'고객 구분'}
with ZipFile(source) as zs, ZipFile(candidate) as zc:
 parts={n:zc.read(n) for n in zc.namelist()}
 for i in range(1,4):
  chart=f'ppt/slides/charts/chart{i}.xml'
  src=etree.fromstring(zs.read(chart)); dst=etree.fromstring(parts[chart])
  assert src.xpath('//c:numCache//c:v/text()',namespaces=N)==dst.xpath('//c:numCache//c:v/text()',namespaces=N),'Chart values changed'
  assert src.xpath('//c:f/text()',namespaces=N)==dst.xpath('//c:f/text()',namespaces=N),'Chart ranges changed'
  dst.append(deepcopy(src.find('c:externalData',N)))
  parts[chart]=etree.tostring(dst,xml_declaration=True,encoding='UTF-8',standalone=True)
  rel=f'ppt/slides/charts/_rels/chart{i}.xml.rels'
  parts[rel]=zs.read(rel)
 for name in [n for n in zs.namelist() if n.endswith('.xlsx')]:
  wb=openpyxl.load_workbook(BytesIO(zs.read(name)))
  original={(ws.title,c.coordinate):c.value for ws in wb for row in ws for c in row if c.value is not None and not isinstance(c.value,str)}
  formulas={(ws.title,c.coordinate):c.value for ws in wb for row in ws for c in row if c.data_type=='f'}
  for ws in wb:
   for row in ws:
    for c in row:
     if isinstance(c.value,str) and c.value in labels:c.value=labels[c.value]
  assert original=={(ws.title,c.coordinate):c.value for ws in wb for row in ws for c in row if c.value is not None and not isinstance(c.value,str)}
  assert formulas=={(ws.title,c.coordinate):c.value for ws in wb for row in ws for c in row if c.data_type=='f'}
  out=BytesIO();wb.save(out);parts[name]=out.getvalue()
 ct=etree.fromstring(parts['[Content_Types].xml']);ctsrc=etree.fromstring(zs.read('[Content_Types].xml'))
 for el in ctsrc:
  if el.get('Extension')=='xlsx' or el.get('PartName','').endswith('.xlsx'):
   if not any(dict(x.attrib)==dict(el.attrib) for x in ct):ct.append(deepcopy(el))
 parts['[Content_Types].xml']=etree.tostring(ct,xml_declaration=True,encoding='UTF-8',standalone=True)
 with ZipFile(output,'w',ZIP_DEFLATED) as zo:
  for name,data in parts.items():zo.writestr(name,data)
print('Preserved 3 source chart workbooks and every numeric value. Updated text labels only.')
