import json
from pathlib import Path

import pytest

from copilot.ibm_amlsim import build_preview


def test_build_preview_preserves_synthetic_data_disclaimer(tmp_path: Path) -> None:
    source = tmp_path / "tx.csv"
    source.write_text(
        "TXN_ID,ACCOUNT_ID,COUNTER_PARTY_ACCOUNT_NUM,TXN_SOURCE_TYPE_CODE,TXN_AMOUNT_ORIG,start\n"
        "1,10,20,CREDIT,12.50,4\n"
        "2,10,21,WIRE,99.00,5\n",
        encoding="utf-8",
    )
    output = tmp_path / "preview.json"

    count = build_preview(source, output)
    preview = json.loads(output.read_text(encoding="utf-8"))

    assert count == 2
    assert "Not Australian banking data" in preview["warning"]
    assert preview["transactions"][0]["direction"] == "inbound"
    assert preview["transactions"][1]["direction"] == "outbound"


def test_build_preview_rejects_unknown_schema(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    source.write_text("id,value\n1,2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="expected IBM AMLSim"):
        build_preview(source, tmp_path / "preview.json")
