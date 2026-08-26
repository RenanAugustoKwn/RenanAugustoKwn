"""Demonstração determinística do loop, sem rede nem chamadas reais de LLM."""

from __future__ import annotations

import json
from typing import Mapping

from .contracts import VerificationReport
from .orchestrator import AutonomousReviewLoop


class ScriptedClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses

    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        del system_prompt, user_prompt
        return json.dumps(self.responses.pop(0))


class DemoVerifier:
    """Simula ferramentas confiáveis; em produção, substitua por sandbox real."""

    def verify(self, files: Mapping[str, str]) -> VerificationReport:
        secure = "validate_user_id" in files["src/service.py"]
        return VerificationReport.from_mapping(
            {
                "build_passed": True,
                "tests_total": 4,
                "tests_passed": 4 if secure else 2,
                "changed_line_coverage": 1.0,
                "changed_branch_coverage": 1.0,
                "required_edge_cases": ["NULO", "LIMITE", "INVALIDO", "FALHA_IO"],
                "passed_edge_cases": ["NULO", "LIMITE", "INVALIDO", "FALHA_IO"] if secure else ["NULO"],
                "max_changed_function_complexity": 4,
                "duplicate_lines": 0,
                "total_lines": 20,
                "solid_violations": 0,
                "lint_errors": 0,
                "type_errors": 0,
                "code_smells": 0,
                "error_handling_gaps": 0,
                "critical_vulnerabilities": 0,
                "high_vulnerabilities": 0 if secure else 1,
                "secrets_found": 0,
                "protected_files_changed": False,
                "quality_gates_weakened": False,
                "owasp_checks": {f"A{i:02d}": secure for i in range(1, 11)},
                "evidence": ["simulação: testes e scanners em sandbox"],
            }
        )


def main() -> None:
    initial_files = {
        "src/service.py": "def lookup(user_id):\n    return repository.get(user_id)\n",
        "tests/test_service.py": "def test_lookup():\n    assert True\n",
    }
    fixed_files = {
        "src/service.py": (
            "def validate_user_id(user_id):\n"
            "    if not isinstance(user_id, str) or not user_id.isdecimal():\n"
            "        raise ValueError('invalid user id')\n"
            "    return user_id\n\n"
            "def lookup(user_id):\n"
            "    return repository.get(validate_user_id(user_id))\n"
        ),
        "tests/test_service.py": "def test_lookup_rejects_invalid_id():\n    assert True\n",
    }
    reviewer = ScriptedClient(
        [
            {
                "status": "REPROVADO",
                "findings": [
                    {
                        "id": "INPUT-001",
                        "severity": "ALTO",
                        "category": "OWASP-A03",
                        "file": "src/service.py",
                        "line": 1,
                        "rule": "CWE-20",
                        "description": "user_id não é validado",
                        "remediation": "validar tipo e formato antes do acesso ao repositório",
                    }
                ],
                "evidence": ["SAST simulou CWE-20"],
                "claimed_metrics": {"test_pass_rate": 0.5},
            },
            {
                "status": "APROVADO",
                "findings": [],
                "evidence": ["revisão e SAST simulados"],
                "claimed_metrics": {"test_pass_rate": 1.0},
            },
        ]
    )
    developer = ScriptedClient(
        [
            {
                "summary": "valida o identificador antes do acesso",
                "files": fixed_files,
                "changed_files": ["src/service.py", "tests/test_service.py"],
                "test_plan": ["identificador inválido lança ValueError"],
                "assumptions": [],
                "sensitive_files_changed": [],
            }
        ]
    )
    judge = ScriptedClient(
        [
            {"status": "CONTINUAR", "motivo": "CWE-20 e testes pendentes"},
            {"status": "APROVADO", "motivo": "todos os gates verificáveis passaram"},
        ]
    )
    result = AutonomousReviewLoop(developer, reviewer, judge, DemoVerifier()).run(
        initial_files, "proteger lookup contra entrada inválida"
    )
    print(result.approval_json or result.failure_reason)


if __name__ == "__main__":
    main()
