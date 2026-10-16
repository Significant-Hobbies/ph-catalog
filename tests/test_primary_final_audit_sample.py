"""Fresh audit random denominator stays disjoint from biased route strata."""

import hashlib
import json

import duckdb
import pytest

from ph_catalog import primary_final_audit_sample as audit


def test_confidence_bands_and_strata_are_deterministic():
    rows = [
        {
            "slug": f"item-{index}",
            "candidate_category": "developer_tools",
            "confidence": confidence,
            "next_step": path,
        }
        for index, (confidence, path) in enumerate(
            [
                (0.3, "non_web_review"),
                (0.6, "website_evidence_candidate"),
                (0.8, "candidate_accept"),
                (0.9, "candidate_accept"),
                (0.95, "candidate_accept"),
                (0.99, "candidate_accept"),
            ]
        )
    ]
    selected, support = audit._select_strata(rows, {"item-0"})
    assert len(selected) == 4
    assert "item-0" not in {row["slug"] for row in selected}
    assert support["developer_tools|high|candidate_accept"] == {"screened": 4, "selected": 3}
    assert audit._select_strata(list(reversed(rows)), {"item-0"}) == (selected, support)
    abstained, abstain_support = audit._select_strata(
        [
            {
                "slug": "no-class",
                "candidate_category": None,
                "confidence": 0.4,
                "next_step": "website_evidence_candidate",
            }
        ],
        set(),
    )
    assert [row["slug"] for row in abstained] == ["no-class"]
    assert abstain_support["abstained|low|website_evidence_candidate"]["selected"] == 1
    with pytest.raises(ValueError, match="confidence"):
        audit._band(float("nan"))


def test_sample_blinds_text_and_preserves_random_denominator(tmp_path, monkeypatch):
    data_root = tmp_path / "data"
    for index, name in enumerate((*audit.OLD_BUNDLES, *audit.FROZEN_BUNDLES.values())):
        directory = data_root / name
        directory.mkdir(parents=True)
        (directory / "source-key.json").write_text(json.dumps([{"slug": f"slug-{index:05d}"}]))
    pilot = tmp_path / "pilot.jsonl"
    pilot.write_text(json.dumps({"slug": "slug-00008"}) + "\n")
    source_path = tmp_path / "source.duckdb"
    connection = duckdb.connect(str(source_path))
    connection.execute(
        "CREATE TABLE product_facts (slug VARCHAR, name VARCHAR, tagline VARCHAR, "
        "description VARCHAR, website_url VARCHAR, has_external_website BOOLEAN, "
        "entity_count INTEGER, trusted_label_count INTEGER)"
    )
    connection.executemany(
        "INSERT INTO product_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                f"slug-{index:05d}",
                f"Name {index}",
                "Study tools",
                "Learn with short lessons",
                "https://example.com",
                True,
                0,
                0,
            )
            for index in range(5_210)
        ],
    )
    connection.execute("CHECKPOINT")
    connection.close()

    def fake_route_mart(screen_mart, _taxonomy, _candidate, output, *, reservation_bundles):
        assert len(reservation_bundles) == 4
        local = duckdb.connect(str(screen_mart), read_only=True)
        slugs = [
            row[0]
            for row in local.execute("SELECT slug FROM product_facts ORDER BY slug").fetchall()
        ]
        local.close()
        rows = [
            {
                "slug": slug,
                "candidate_category": "developer_tools" if index % 2 else "education_learning",
                "confidence": (0.4, 0.6, 0.9)[index % 3],
                "next_step": ("candidate_accept", "website_evidence_candidate", "non_web_review")[
                    index % 3
                ],
                "evidence_hash": hashlib.sha256(slug.encode()).hexdigest(),
            }
            for index, slug in enumerate(slugs)
        ]
        output.write_text("".join(json.dumps(row) + "\n" for row in rows))
        output.with_suffix(".jsonl.manifest.json").write_text("{}\n")
        return {"output_sha256": hashlib.sha256(output.read_bytes()).hexdigest()}

    monkeypatch.setattr(audit, "route_mart", fake_route_mart)
    output = tmp_path / "audit"
    report = audit.sample(
        source_path, tmp_path / "taxonomy", tmp_path / "model", data_root, pilot, output
    )
    blind = json.loads((output / "blind-review.json").read_text())
    key = json.loads((output / "source-key.json").read_text())
    assert report["population_count"] == 5_210
    assert report["excluded_distinct_slugs"] == 9
    assert report["excluded_in_mart"] == 9
    assert report["eligible_random_denominator"] == 5_201
    assert report["random_count"] == 200
    assert report["screening_count"] == 5_000
    assert len(blind) == len(key) == 200 + report["model_stratified_count"]
    assert all(set(row) == {"review_id", "name", "tagline", "description"} for row in blind)
    assert len({row["slug"] for row in key}) == len(key)
    assert {row["slug"] for row in key}.isdisjoint({f"slug-{index:05d}" for index in range(9)})
    assert sum(row["split"] == "random" for row in key) == 200
    monkeypatch.setattr(
        audit,
        "load_routes",
        lambda *_args: ([], {"source_mart_sha256": report["screen_mart_sha256"]}),
    )
    checked = audit.check(source_path, data_root, pilot, output)
    assert checked["status"].startswith("verified fresh")
    report_path = output / "manifest.json"
    altered = dict(report)
    altered["file_sha256"] = {"source-key.json": report["file_sha256"]["source-key.json"]}
    report_path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="provenance"):
        audit.check(source_path, data_root, pilot, output)
    report_path.write_text(json.dumps(report))
    blind_path = output / "blind-review.json"
    blind_path.write_text(blind_path.read_text().replace("Study tools", "Changed text", 1))
    with pytest.raises(ValueError, match="provenance"):
        audit.check(source_path, data_root, pilot, output)
    with pytest.raises(FileExistsError):
        audit.sample(
            source_path, tmp_path / "taxonomy", tmp_path / "model", data_root, pilot, output
        )
