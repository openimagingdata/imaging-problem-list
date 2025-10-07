from src.schemas import ExtractionResult, Finding

def test_schema_roundtrip():
    obj = ExtractionResult(report_id="x", findings=[Finding(name="pleural effusion", present=True)])
    assert obj.model_dump()["findings"][0]["name"] == "pleural effusion"
