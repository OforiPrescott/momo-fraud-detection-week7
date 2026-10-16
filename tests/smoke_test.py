"""End-to-end smoke test of the Week 8 API. Run from the project root:  python tests/smoke_test.py

Exercises: overview, sample analysis, threshold re-analysis, case drill-down, CSV export, uploads in five
formats, a database source (and a rejected SQL-injection attempt), real-time ingest and a live replay.
"""
import os, sys, io, json, sqlite3, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.getcwd())
import pandas as pd
from fastapi.testclient import TestClient
from backend.main import app
with TestClient(app) as c:
    print(c.get('/api/health').json())
    o=c.get('/api/overview'); print('overview',o.status_code, len(o.json()['insights']))
    r=c.post('/api/analyze/sample',json={'threshold':0.5,'currency':'GH₵'}); d=r.json(); print('sample',r.status_code, d['took_seconds'])
    print(d['narrative']); print([ (i['severity'],i['title']) for i in d['insights']]); print([ (x['priority'],x['title']) for x in d['recommendations']])
    print(d['evaluation']['precision'], d['evaluation']['recall'], d['evaluation']['suggested'])
    sid=d['analysis_id']
    fl=c.get(f'/api/analysis/{sid}/flagged',params={'threshold':0.5,'page_size':3}).json(); print(fl['total'], fl['rows'][0])
    cs=c.get(f"/api/analysis/{sid}/case/{fl['rows'][0]['row_id']}").json(); print(cs['action'], [w['text'] for w in cs['why'][:3]], cs['related'][:1])
    print(len(c.get(f'/api/analysis/{sid}/export.csv').text.splitlines()))
    d2=c.get(f'/api/analysis/{sid}',params={'threshold':0.9}).json(); print('t.9',d2['summary']['flagged'], d2['evaluation']['precision'])
    # raw upload without devices
    df=pd.read_csv('backend/data/scoring_sample.csv')
    raw=df[['step','type','amount','nameOrig','oldbalanceOrg','newbalanceOrig','nameDest','oldbalanceDest','newbalanceDest','isFraud']]
    b=io.BytesIO(raw.to_csv(index=False).encode())
    r=c.post('/api/analyze/upload',files={'file':('raw.csv',b,'text/csv')},data={'threshold':'0.5'}); d3=r.json(); print('upload',r.status_code,d3['data_quality']['coverage_pct'],[i['title'] for i in d3['insights']][:4])
    # xlsx, json, parquet
    for name,data in [('t.xlsx',None),('t.json',None),('t.parquet',None),('t.jsonl',None)]:
        bb=io.BytesIO()
        if name.endswith('xlsx'): raw.head(300).to_excel(bb,index=False)
        elif name.endswith('.json'): bb.write(raw.head(300).to_json(orient='records').encode())
        elif name.endswith('parquet'): raw.head(300).to_parquet(bb)
        else: bb.write(raw.head(300).to_json(orient='records',lines=True).encode())
        bb.seek(0); r=c.post('/api/analyze/upload',files={'file':(name,bb)},data={}); print(name,r.status_code, r.json().get('detail') or r.json()['summary']['rows'])
    # with events join: device_id in main file
    d4=df.head(2000)[['step','type','amount','nameOrig','nameDest','oldbalanceOrg','newbalanceOrig','any_attack_flag']].copy(); d4['device_id']='d'+(d4.index%7).astype(str)
    r=c.post('/api/analyze/upload',files={'file':('dev.csv',io.BytesIO(d4.to_csv(index=False).encode()))},data={}); j=r.json(); print('device file',r.status_code, j['data_quality']['coverage_pct'], j['data_quality']['rule_columns'])
    bad=c.post('/api/analyze/upload',files={'file':('x.csv',io.BytesIO(b'a,b\n1,2\n'))},data={}); print('bad',bad.status_code,bad.json())
    # sqlite
    con=sqlite3.connect('tests/_tmp_test.db'); df.to_sql('transactions',con,if_exists='replace',index=False); con.close()
    r=c.post('/api/analyze/database',json={'dialect':'sqlite','database':'tests/_tmp_test.db','table':'transactions'}); print('db',r.status_code, r.json().get('detail') or r.json()['summary']['rows'])
    r=c.post('/api/analyze/database',json={'dialect':'sqlite','database':'tests/_tmp_test.db','query':'SELECT * FROM transactions; DROP TABLE transactions'}); print('db inj',r.status_code,r.json())
    # ingest + stream engine
    t={'type':'CASH_OUT','amount':250000,'nameOrig':'C1','nameDest':'C9','device_id':'dev1','oldbalanceOrg':250000,'newbalanceOrig':0}
    r=c.post('/api/ingest',json=[t,{**t,'device_id':'dev2'},{**t,'device_id':'dev3','sim_change':1}]); print('ingest',r.status_code,[ (x['risk'],x['flagged']) for x in r.json()['results']])
    print(c.post('/api/ingest',json={'foo':1}).json())
    c.post('/api/stream/replay',json={'action':'start','rate':80}); time.sleep(4.5)
    la=c.get('/api/stream/analysis').json(); print('live',la.get('live'), la['narrative']['headline'] if 'narrative' in la else la)
    print(c.post('/api/stream/replay',json={'action':'stop'}).json())
