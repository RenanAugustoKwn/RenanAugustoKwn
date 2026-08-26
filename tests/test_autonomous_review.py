from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Mapping

from autonomous_code_review.contracts import AcceptancePolicy, VerificationReport
from autonomous_code_review.orchestrator import AutonomousReviewLoop


class QueueClient:
    """Agente roteirizado: testes não usam rede, relógio ou LLM real."""

    def __init__(self, responses: list[dict | str]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        if not self.responses:
            raise AssertionError("chamada inesperada ao agente")
        response = self.responses.pop(0)
        return response if isinstance(response, str) else json.dumps(response)


@dataclass
class QueueVerifier:
    reports: list[VerificationReport]

    def verify(self, files: Mapping[str, str]) -> VerificationReport:
        del files
        if not self.reports:
            raise AssertionError("chamada inesperada ao verifier")
        return self.reports.pop(0)


def valid_verification(**changes: object) -> VerificationReport:
    payload: dict[str, object] = {
        "build_passed": True,
        "tests_total": 4,
        "tests_passed": 4,
        "changed_line_coverage": 1.0,
        "changed_branch_coverage": 1.0,
        "required_edge_cases": ["NULO", "LIMITE", "ENTRADA_INVALIDA", "FALHA_IO"],
        "passed_edge_cases": ["NULO", "LIMITE", "ENTRADA_INVALIDA", "FALHA_IO"],
        "max_changed_function_complexity": 4,
        "duplicate_lines": 0,
        "total_lines": 40,
        "solid_violations": 0,
        "lint_errors": 0,
        "type_errors": 0,
        "code_smells": 0,
        "error_handling_gaps": 0,
        "critical_vulnerabilities": 0,
        "high_vulnerabilities": 0,
        "secrets_found": 0,
        "protected_files_changed": False,
        "quality_gates_weakened": False,
        "owasp_checks": {f"A{i:02d}": True for i in range(1, 11)},
        "evidence": ["testes, lint, SAST, SCA e secret scan executados em sandbox"],
    }
    payload.update(changes)
    return VerificationReport.from_mapping(payload)


def full_snapshot(code: str) -> dict[str, str]:
    return {"src/app.py": code, "tests/test_app.py": "def test_placeholder():\n    assert True\n"}


def developer_response(code: str) -> dict:
    return {
        "summary": "corrige a implementação",
        "files": full_snapshot(code),
        "changed_files": ["src/app.py"],
        "test_plan": ["entrada inválida produz erro controlado"],
        "assumptions": [],
        "sensitive_files_changed": [],
    }


def approved_review() -> dict:
    return {
        "status": "APROVADO",
        "findings": [],
        "evidence": ["revisão manual e análise estática concluídas"],
        "claimed_metrics": {"max_cyclomatic_complexity": 4, "test_pass_rate": 1.0},
    }


def rejected_review(identifier: str = "INPUT-001") -> dict:
    return {
        "status": "REPROVADO",
        "findings": [
            {
                "id": identifier,
                "severity": "ALTO",
                "category": "OWASP-A03",
                "file": "src/app.py",
                "line": 1,
                "rule": "CWE-20",
                "description": "entrada não validada",
                "remediation": "validar entrada antes do processamento",
            }
        ],
        "evidence": ["scanner detectou entrada não validada"],
        "claimed_metrics": {"max_cyclomatic_complexity": 4, "test_pass_rate": 0.5},
    }


class AutonomousReviewLoopTests(unittest.TestCase):
    def test_approves_only_after_judge_and_policy_pass(self) -> None:
        developer = QueueClient([])
        reviewer = QueueClient([approved_review()])
        judge = QueueClient([{"status": "APROVADO", "motivo": "todos os gates verificáveis passaram"}])
        loop = AutonomousReviewLoop(
            developer=developer,
            reviewer=reviewer,
            judge=judge,
            verifier=QueueVerifier([valid_verification()]),
        )

        result = loop.run(full_snapshot("SAFE = True"), "corrigir segurança")

        self.assertEqual(result.terminal_status, "APROVADO")
        self.assertEqual(result.approval_json, '{"status":"APROVADO","motivo":"todos os gates verificáveis passaram"}')
        self.assertEqual(len(result.iterations), 1)
        self.assertEqual(len(developer.calls), 0)

    def test_judge_cannot_override_failed_verification(self) -> None:
        loop = AutonomousReviewLoop(
            developer=QueueClient([]),
            reviewer=QueueClient([approved_review()]),
            judge=QueueClient([{"status": "APROVADO", "motivo": "ignorar evidência"}]),
            verifier=QueueVerifier([valid_verification(tests_passed=3)]),
            policy=AcceptancePolicy(max_iterations=1),
        )

        result = loop.run(full_snapshot("INSECURE = True"), "corrigir segurança")

        self.assertEqual(result.terminal_status, "FALHA_CONTRATO")
        self.assertIn("não satisfaz", result.failure_reason or "")

    def test_max_iterations_returns_best_candidate_without_extra_edit(self) -> None:
        developer = QueueClient([developer_response("V2")])
        loop = AutonomousReviewLoop(
            developer=developer,
            reviewer=QueueClient([rejected_review("A"), rejected_review("B")]),
            judge=QueueClient([
                {"status": "CONTINUAR", "motivo": "vulnerabilidade ainda existe"},
                {"status": "CONTINUAR", "motivo": "vulnerabilidade ainda existe"},
            ]),
            verifier=QueueVerifier([
                valid_verification(tests_passed=1),
                valid_verification(tests_passed=3),
            ]),
            policy=AcceptancePolicy(max_iterations=2),
        )

        result = loop.run(full_snapshot("V1"), "corrigir segurança")

        self.assertEqual(result.terminal_status, "ABORTADO_MAX_ITERACOES")
        self.assertEqual(result.best_files["src/app.py"], "V2")
        self.assertEqual(len(result.iterations), 2)
        self.assertEqual(len(developer.calls), 1)

    def test_repeated_snapshot_aborts_before_limit(self) -> None:
        repeated = developer_response("REPEATED")
        loop = AutonomousReviewLoop(
            developer=QueueClient([repeated]),
            reviewer=QueueClient([rejected_review("A"), rejected_review("B")]),
            judge=QueueClient([
                {"status": "CONTINUAR", "motivo": "corrija"},
                {"status": "CONTINUAR", "motivo": "corrija"},
            ]),
            verifier=QueueVerifier([valid_verification(tests_passed=1), valid_verification(tests_passed=1)]),
        )

        result = loop.run(full_snapshot("REPEATED"), "corrigir segurança")

        self.assertEqual(result.terminal_status, "ABORTADO_SEM_PROGRESSO")
        self.assertEqual(len(result.iterations), 2)
        self.assertIn("repetido", result.failure_reason or "")

    def test_invalid_agent_json_is_contract_failure(self) -> None:
        loop = AutonomousReviewLoop(
            developer=QueueClient([]),
            reviewer=QueueClient(["```json\n{}\n```"]),
            judge=QueueClient([]),
            verifier=QueueVerifier([]),
        )

        result = loop.run(full_snapshot("BASE"), "corrigir segurança")

        self.assertEqual(result.terminal_status, "FALHA_CONTRATO")
        self.assertIn("JSON", result.failure_reason or "")

    def test_policy_rejects_more_than_seven_iterations(self) -> None:
        with self.assertRaises(ValueError):
            AcceptancePolicy(max_iterations=8)

    def test_rejects_unsafe_initial_snapshot_before_verifier_runs(self) -> None:
        loop = AutonomousReviewLoop(
            developer=QueueClient([]),
            reviewer=QueueClient([]),
            judge=QueueClient([]),
            verifier=QueueVerifier([]),
        )

        with self.assertRaises(ValueError):
            loop.run({"../outside.py": "unsafe"}, "corrigir segurança")


if __name__ == "__main__":
    unittest.main()
