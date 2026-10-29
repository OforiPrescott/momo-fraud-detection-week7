"""End-to-end API tests: analysis, interpretation output, live ingest, account lifecycle."""
import io

import pandas as pd


def test_health_is_public(client):
    assert client.get("/api/health").json()["model_loaded"] is True


def test_sample_analysis_has_interpretation(signed_in):
    d = signed_in.post("/api/analyze/sample", json={"threshold": 0.5}).json()
    assert d["narrative"]["headline"] and d["insights"] and d["tiers"]
    assert d["evaluation"]["recall"] > 0.95
    assert d["data_quality"]["drift"]["overall"] == "stable"


def test_threshold_changes_results(signed_in):
    sid = signed_in.post("/api/analyze/sample", json={"threshold": 0.5}).json()["analysis_id"]
    low = signed_in.get(f"/api/analysis/{sid}", params={"threshold": 0.1}).json()["summary"]["flagged"]
    high = signed_in.get(f"/api/analysis/{sid}", params={"threshold": 0.95}).json()["summary"]["flagged"]
    assert low >= high


def test_case_drilldown_explains(signed_in):
    sid = signed_in.post("/api/analyze/sample", json={"threshold": 0.5}).json()["analysis_id"]
    row = signed_in.get(f"/api/analysis/{sid}/flagged", params={"page_size": 1}).json()["rows"][0]
    case = signed_in.get(f"/api/analysis/{sid}/case/{row['row_id']}").json()
    assert case["action"] and case["why"]


def test_upload_formats(signed_in):
    df = pd.read_csv("backend/data/scoring_sample.csv").head(300)[["type", "amount", "nameOrig", "nameDest"]]
    for name, data in (("t.csv", df.to_csv(index=False).encode()), ("t.json", df.to_json(orient="records").encode())):
        r = signed_in.post("/api/analyze/upload", files={"file": (name, io.BytesIO(data))})
        assert r.status_code == 200 and r.json()["summary"]["rows"] == 300


def test_ingest_scores_live(signed_in):
    t = {"type": "CASH_OUT", "amount": 250000, "nameOrig": "C1", "nameDest": "C9", "device_id": "d1",
         "oldbalanceOrg": 250000, "newbalanceOrig": 0}
    r = signed_in.post("/api/ingest", json=[t, {**t, "device_id": "d2"}]).json()
    assert r["scored"] == 2 and all(0 <= x["risk"] <= 1 for x in r["results"])


def test_account_lifecycle(signed_in):
    assert signed_in.post("/api/auth/profile", json={"name": "Kwame B.", "organization": "Test"}).json()["name"] == "Kwame B."
    assert signed_in.post("/api/auth/password", json={"current_password": "wrong-1x", "new_password": "Another-pass-77"}).status_code == 403
    assert signed_in.post("/api/auth/password", json={"current_password": "Ledger-check-42", "new_password": "Another-pass-77"}).status_code == 200
    assert signed_in.post("/api/auth/delete", json={"password": "Another-pass-77"}).status_code == 200
    assert signed_in.get("/api/auth/me").status_code == 401
