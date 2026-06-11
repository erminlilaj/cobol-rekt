#!/usr/bin/env python3
"""Regression tests for scripts/rag_bundle_benchmark.py."""

from __future__ import annotations

import unittest

from scripts import rag_bundle_benchmark


class RagBundleBenchmarkTest(unittest.TestCase):
    def test_path_sensitive_facts_include_flow_sensitive_target_chunks(self) -> None:
        records = [
            {
                "chunk_id": "TARGET.CBL:flow_sensitive.target:call-node",
                "chunk_type": "flow_sensitive.target",
                "metadata": {
                    "chunk_id": "TARGET.CBL:flow_sensitive.target:call-node",
                    "call_targets": [
                        {
                            "identifier": "WS-PGM",
                            "target": "PROGA",
                            "confidence": "high",
                            "evidence": {"node_id": "call-node"},
                        },
                    ],
                    "cics_targets": [
                        {
                            "command": "LINK",
                            "identifier": "WS-CICS-PGM",
                            "target": "CICSA",
                            "confidence": "high",
                        },
                    ],
                    "cics_arguments": [
                        {
                            "name": "TRANSID",
                            "identifier": "WS-TRAN",
                            "resolved_value": "TRN1",
                            "confidence": "high",
                        },
                    ],
                },
            },
        ]

        facts = rag_bundle_benchmark.path_sensitive_facts(records)

        self.assertIn(
            "flow_sensitive.target|TARGET.CBL:FLOW_SENSITIVE.TARGET:CALL-NODE|call_targets[0].target|PROGA",
            facts,
        )
        self.assertIn(
            "flow_sensitive.target|TARGET.CBL:FLOW_SENSITIVE.TARGET:CALL-NODE|cics_targets[0].target|CICSA",
            facts,
        )
        self.assertIn(
            "flow_sensitive.target|TARGET.CBL:FLOW_SENSITIVE.TARGET:CALL-NODE|cics_arguments[0].resolved_value|TRN1",
            facts,
        )
        self.assertFalse(any("NODE_ID" in fact for fact in facts))

    def test_static_analysis_queries_skip_until_required_chunk_type_exists(self) -> None:
        query = rag_bundle_benchmark.QuerySpec(
            query_id="static_analysis_constants_present",
            category="static_analysis",
            query="Which static value propagation chunks show entry constants?",
            expected_hit=True,
            expected_types=frozenset({"static_value.propagation"}),
            all_terms=frozenset({"Entry constants"}),
            any_terms=frozenset(),
            require_terms=frozenset(),
            reject_terms=frozenset(),
            requires_any_chunk_type=frozenset({"static_value.propagation"}),
        )
        records = [
            {
                "chunk_id": "PROG:dependencies",
                "chunk_type": "dependencies",
                "file": "PROG__dependencies.json",
                "text": "External dependencies for PROG.",
                "metadata": {"chunk_type": "dependencies", "chunk_id": "PROG:dependencies"},
                "term_freq": rag_bundle_benchmark.Counter(rag_bundle_benchmark.tokenize("External dependencies for PROG.")),
                "tokens": rag_bundle_benchmark.tokenize("External dependencies for PROG."),
            },
        ]

        result = rag_bundle_benchmark.score_query(records, query, include_timings=False)

        self.assertTrue(result["skipped"])
        self.assertEqual("required chunk type absent: static_value.propagation", result["skip_reason"])

    def test_cics_comparator_treats_resolved_value_change_as_changed_not_lost(self) -> None:
        before = {
            "cics.operation|WRITEQ|QUEUE_WRITE|QUEUE|TWCOB-TS-CODA|arg|QUEUE|TWCOB-TS-CODA|IDENTIFIER": ""
        }
        after = {
            "cics.operation|WRITEQ|QUEUE_WRITE|QUEUE|TWCOB-TS-CODA|arg|QUEUE|TWCOB-TS-CODA|IDENTIFIER": "TWCOB-TS-CODA"
        }

        diff = rag_bundle_benchmark.keyed_fact_diff(before, after)

        self.assertEqual(1, diff["v0_count"])
        self.assertEqual(1, diff["current_count"])
        self.assertEqual(1, diff["retained_count"])
        self.assertEqual(100.0, diff["retention_pct"])
        self.assertEqual(1, diff["changed_count"])
        self.assertEqual(1, diff["value_improved_count"])
        self.assertEqual([], diff["missing_sample"])
        self.assertEqual([], diff["added_sample"])
        self.assertEqual(
            [
                "cics.operation|WRITEQ|QUEUE_WRITE|QUEUE|TWCOB-TS-CODA|arg|QUEUE|TWCOB-TS-CODA|IDENTIFIER|value_changed|<blank>|TWCOB-TS-CODA"
            ],
            diff["changed_sample"],
        )


if __name__ == "__main__":
    unittest.main()
