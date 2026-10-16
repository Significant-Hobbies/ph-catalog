"""Selected Stage 7 path replay cannot substitute other products or routes."""

import hashlib
import json

import duckdb
import pytest

from ph_catalog import primary_final_audit_paths as paths


def test_selected_replay_matches_only_sealed_screening(tmp_path, monkeypatch):
    audit = tmp_path / "audit"
    audit.mkdir()
    key = [{"slug": f"slug-{index:03d}"} for index in range(320)]
    (audit / "source-key.json").write_text(json.dumps(key))
    screening = [
        {"slug": row["slug"], "next_step": "candidate_accept", "primary_category": "finance"}
        for row in key
    ]
    (audit / "screen-routes.jsonl").write_text("".join(json.dumps(row) + "\n" for row in screening))
    (audit / "manifest.json").write_text("{}\n")
    source_path = tmp_path / "source.duckdb"
    source = duckdb.connect(str(source_path))
    source.execute(
        "CREATE TABLE product_facts (slug VARCHAR, name VARCHAR, tagline VARCHAR, "
        "description VARCHAR, website_url VARCHAR, has_external_website BOOLEAN, "
        "entity_count INTEGER, trusted_label_count INTEGER)"
    )
    source.executemany(
        "INSERT INTO product_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(row["slug"], "Name", "Tagline", "Description", None, False, 0, 0) for row in key],
    )
    source.close()
    calls = []

    def fake_check(*args):
        calls.append(args)
        return {"blind_sha256": "blind"}

    monkeypatch.setattr(paths, "check", fake_check)
    altered = False

    def fake_route_mart(_mart, _taxonomy, _candidate, output, *, reservation_bundles):
        assert len(reservation_bundles) == 4
        rows = list(screening)
        if altered:
            rows[0] = {**rows[0], "primary_category": "home_lifestyle"}
        output.write_text("".join(json.dumps(row) + "\n" for row in rows))
        output.with_suffix(".jsonl.manifest.json").write_text("{}\n")
        return {"output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}

    monkeypatch.setattr(paths, "route_mart", fake_route_mart)
    output = tmp_path / "paths"
    report = paths.prepare(
        source_path,
        tmp_path / "taxonomy",
        tmp_path / "candidate",
        tmp_path,
        tmp_path / "pilot",
        audit,
        output,
    )
    assert report["selected_count"] == 320
    assert len(calls) == 1
    assert not (audit / "annotations-template.json").exists()
    assert not (audit / "annotations.json").exists()
    altered = True
    with pytest.raises(ValueError, match="differs from frozen screening"):
        paths.prepare(
            source_path,
            tmp_path / "taxonomy",
            tmp_path / "candidate",
            tmp_path,
            tmp_path / "pilot",
            audit,
            tmp_path / "tampered",
        )
