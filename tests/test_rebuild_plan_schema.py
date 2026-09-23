from __future__ import annotations

from classic_retro.rebuild.model import RebuildPlan


def test_rebuild_plan_schema_supports_pc_relative_reference_and_safe_space():
    plan = RebuildPlan.from_dict(
        {
            "schema_version": "1.0",
            "id": "fixture",
            "resources": [
                {
                    "id": "text",
                    "start": 4096,
                    "size": 32,
                    "alignment": 4,
                }
            ],
            "references": [
                {
                    "id": "ptr",
                    "offset": 512,
                    "target_resource_id": "text",
                    "integer": {
                        "size_bytes": 2,
                        "byte_order": "little",
                        "base_kind": "site",
                        "base_value": 2,
                    },
                }
            ],
            "safe_regions": [
                {
                    "id": "safe",
                    "start": 8192,
                    "size": 1024,
                    "expected_fill_byte": 255,
                }
            ],
        }
    )

    assert plan.references[0].codec.base_value == 2
    assert plan.safe_regions[0].expected_fill_byte == 255
