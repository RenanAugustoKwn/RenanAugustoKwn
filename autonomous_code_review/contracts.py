"""Contratos de agentes e predicado determinístico de aprovação."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ContractViolation(ValueError):
    """Uma saída de agente ou ferramenta não respeitou o protocolo."""


class Severity(str, Enum):
    CRITICO = "CRITICO"
    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BAIXO = "BAIXO"


SEVERITY_WEIGHT = {
    Severity.CRITICO: 10_000,
    Severity.ALTO: 1_000,
    Severity.MEDIO: 100,
    Severity.BAIXO: 10,
}
REQUIRED_OWASP_CHECKS = frozenset(f"A{i:02d}" for i in range(1, 11))
MAX_SNAPSHOT_FILES = 500
MAX_FILE_CHARACTERS = 1_000_000


def _mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractViolation(f"{field_name} deve ser um objeto JSON")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractViolation(f"{field_name} deve ser uma string não vazia")
    return value


def _integer(value: Any, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractViolation(f"{field_name} deve ser inteiro >= {minimum}")
    return value


def _ratio(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ContractViolation(f"{field_name} deve estar entre 0 e 1")
    return float(value)


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ContractViolation(f"{field_name} deve ser booleano")
    return value


def _string_list(value: Any, field_name: str, *, non_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (non_empty and not value):
        raise ContractViolation(f"{field_name} deve ser uma lista")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise ContractViolation(f"{field_name} deve conter strings não vazias")
    return tuple(value)


def _safe_relative_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ContractViolation(f"caminho inseguro: {path}")
    return normalized


def validate_snapshot(value: Any, field_name: str = "files") -> dict[str, str]:
    """Valida snapshots antes de qualquer Verifier materializá-los em um worktree."""
    raw_files = _mapping(value, field_name)
    if not raw_files:
        raise ContractViolation(f"{field_name} não pode ser vazio")
    if len(raw_files) > MAX_SNAPSHOT_FILES:
        raise ContractViolation(f"{field_name} excede o máximo de {MAX_SNAPSHOT_FILES} arquivos")
    files: dict[str, str] = {}
    for raw_path, content in raw_files.items():
        path = _safe_relative_path(_string(raw_path, f"{field_name}.<path>"))
        text = _string(content, f"{field_name}.{path}")
        if len(text) > MAX_FILE_CHARACTERS:
            raise ContractViolation(f"{field_name}.{path} excede o limite de tamanho")
        files[path] = text
    return files


@dataclass(frozen=True)
class Finding:
    identifier: str
    severity: Severity
    category: str
    file: str
    line: int
    rule: str
    description: str
    remediation: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Finding":
        try:
            severity = Severity(_string(raw.get("severity"), "finding.severity"))
        except ValueError as exc:
            raise ContractViolation("finding.severity inválida") from exc
        return cls(
            identifier=_string(raw.get("id"), "finding.id"),
            severity=severity,
            category=_string(raw.get("category"), "finding.category"),
            file=_safe_relative_path(_string(raw.get("file"), "finding.file")),
            line=_integer(raw.get("line"), "finding.line", 1),
            rule=_string(raw.get("rule"), "finding.rule"),
            description=_string(raw.get("description"), "finding.description"),
            remediation=_string(raw.get("remediation"), "finding.remediation"),
        )

    @property
    def fingerprint(self) -> str:
        return f"{self.identifier}|{self.severity.value}|{self.file}|{self.line}|{self.rule}"


@dataclass(frozen=True)
class DeveloperRevision:
    summary: str
    files: Mapping[str, str]
    changed_files: tuple[str, ...]
    test_plan: tuple[str, ...]
    assumptions: tuple[str, ...]
    sensitive_files_changed: tuple[str, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DeveloperRevision":
        expected = {
            "summary",
            "files",
            "changed_files",
            "test_plan",
            "assumptions",
            "sensitive_files_changed",
        }
        if set(raw) != expected:
            raise ContractViolation("resposta do Desenvolvedor deve conter exatamente as chaves do contrato")
        files = validate_snapshot(raw["files"])
        changed_files = tuple(_safe_relative_path(item) for item in _string_list(raw["changed_files"], "changed_files"))
        if not set(changed_files).issubset(files):
            raise ContractViolation("changed_files deve referenciar apenas files")
        sensitive = tuple(
            _safe_relative_path(item)
            for item in _string_list(raw["sensitive_files_changed"], "sensitive_files_changed")
        )
        if not set(sensitive).issubset(files):
            raise ContractViolation("sensitive_files_changed deve referenciar apenas files")
        return cls(
            summary=_string(raw["summary"], "summary"),
            files=files,
            changed_files=changed_files,
            test_plan=_string_list(raw["test_plan"], "test_plan", non_empty=True),
            assumptions=_string_list(raw["assumptions"], "assumptions"),
            sensitive_files_changed=sensitive,
        )


@dataclass(frozen=True)
class ReviewReport:
    status: str
    findings: tuple[Finding, ...]
    evidence: tuple[str, ...]
    claimed_metrics: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "ReviewReport":
        expected = {"status", "findings", "evidence", "claimed_metrics"}
        if set(raw) != expected:
            raise ContractViolation("resposta do Revisor deve conter exatamente as chaves do contrato")
        status = _string(raw["status"], "status")
        if status not in {"APROVADO", "REPROVADO"}:
            raise ContractViolation("status do Revisor inválido")
        findings_raw = raw["findings"]
        if not isinstance(findings_raw, list):
            raise ContractViolation("findings deve ser uma lista")
        findings = tuple(Finding.from_mapping(_mapping(item, "finding")) for item in findings_raw)
        if status == "APROVADO" and findings:
            raise ContractViolation("Revisor não pode aprovar código com findings")
        if status == "REPROVADO" and not findings:
            raise ContractViolation("Revisor reprovado precisa informar ao menos um finding")
        return cls(
            status=status,
            findings=findings,
            evidence=_string_list(raw["evidence"], "evidence", non_empty=True),
            claimed_metrics=_mapping(raw["claimed_metrics"], "claimed_metrics"),
        )

    @property
    def fingerprint(self) -> tuple[str, ...]:
        return tuple(sorted(finding.fingerprint for finding in self.findings))


@dataclass(frozen=True)
class JudgeDecision:
    status: str
    motivo: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "JudgeDecision":
        if set(raw) != {"status", "motivo"}:
            raise ContractViolation("resposta do Juiz deve conter exatamente status e motivo")
        status = _string(raw["status"], "status")
        if status not in {"APROVADO", "CONTINUAR"}:
            raise ContractViolation("status do Juiz inválido")
        return cls(status=status, motivo=_string(raw["motivo"], "motivo"))


@dataclass(frozen=True)
class VerificationReport:
    """Dados gerados por testes e scanners independentes em ambiente isolado."""

    build_passed: bool
    tests_total: int
    tests_passed: int
    changed_line_coverage: float
    changed_branch_coverage: float
    required_edge_cases: frozenset[str]
    passed_edge_cases: frozenset[str]
    max_changed_function_complexity: int
    duplicate_lines: int
    total_lines: int
    solid_violations: int
    lint_errors: int
    type_errors: int
    code_smells: int
    error_handling_gaps: int
    critical_vulnerabilities: int
    high_vulnerabilities: int
    secrets_found: int
    protected_files_changed: bool
    quality_gates_weakened: bool
    owasp_checks: Mapping[str, bool] = field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "VerificationReport":
        checks_raw = _mapping(raw.get("owasp_checks"), "owasp_checks")
        checks: dict[str, bool] = {}
        for name, passed in checks_raw.items():
            if name not in REQUIRED_OWASP_CHECKS:
                raise ContractViolation(f"check OWASP desconhecido: {name}")
            checks[name] = _boolean(passed, f"owasp_checks.{name}")
        required_edges = frozenset(_string_list(raw.get("required_edge_cases"), "required_edge_cases", non_empty=True))
        passed_edges = frozenset(_string_list(raw.get("passed_edge_cases"), "passed_edge_cases"))
        if not passed_edges.issubset(required_edges):
            raise ContractViolation("passed_edge_cases contém caso não declarado")
        return cls(
            build_passed=_boolean(raw.get("build_passed"), "build_passed"),
            tests_total=_integer(raw.get("tests_total"), "tests_total", 1),
            tests_passed=_integer(raw.get("tests_passed"), "tests_passed"),
            changed_line_coverage=_ratio(raw.get("changed_line_coverage"), "changed_line_coverage"),
            changed_branch_coverage=_ratio(raw.get("changed_branch_coverage"), "changed_branch_coverage"),
            required_edge_cases=required_edges,
            passed_edge_cases=passed_edges,
            max_changed_function_complexity=_integer(
                raw.get("max_changed_function_complexity"), "max_changed_function_complexity"
            ),
            duplicate_lines=_integer(raw.get("duplicate_lines"), "duplicate_lines"),
            total_lines=_integer(raw.get("total_lines"), "total_lines", 1),
            solid_violations=_integer(raw.get("solid_violations"), "solid_violations"),
            lint_errors=_integer(raw.get("lint_errors"), "lint_errors"),
            type_errors=_integer(raw.get("type_errors"), "type_errors"),
            code_smells=_integer(raw.get("code_smells"), "code_smells"),
            error_handling_gaps=_integer(raw.get("error_handling_gaps"), "error_handling_gaps"),
            critical_vulnerabilities=_integer(raw.get("critical_vulnerabilities"), "critical_vulnerabilities"),
            high_vulnerabilities=_integer(raw.get("high_vulnerabilities"), "high_vulnerabilities"),
            secrets_found=_integer(raw.get("secrets_found"), "secrets_found"),
            protected_files_changed=_boolean(raw.get("protected_files_changed"), "protected_files_changed"),
            quality_gates_weakened=_boolean(raw.get("quality_gates_weakened"), "quality_gates_weakened"),
            owasp_checks=checks,
            evidence=_string_list(raw.get("evidence"), "evidence", non_empty=True),
        )

    @property
    def duplication_ratio(self) -> float:
        return self.duplicate_lines / self.total_lines


@dataclass(frozen=True)
class AcceptancePolicy:
    """Definição operacional, rígida e auditável de pronto para aprovação."""

    max_iterations: int = 7
    max_changed_function_complexity: int = 10
    max_duplication_ratio: float = 0.03
    min_score_improvement: int = 1

    def __post_init__(self) -> None:
        if not 1 <= self.max_iterations <= 7:
            raise ValueError("max_iterations deve estar entre 1 e 7")
        if self.max_changed_function_complexity < 1:
            raise ValueError("max_changed_function_complexity deve ser positivo")
        if not 0 <= self.max_duplication_ratio <= 1:
            raise ValueError("max_duplication_ratio deve estar entre 0 e 1")

    def failures(self, review: ReviewReport, verification: VerificationReport) -> tuple[str, ...]:
        failures: list[str] = []
        if review.status != "APROVADO":
            failures.append("revisor não aprovou")
        if review.findings:
            failures.append("existem findings não resolvidos")
        if not verification.build_passed:
            failures.append("build falhou")
        if verification.tests_passed != verification.tests_total:
            failures.append("nem todos os testes passam")
        if verification.changed_line_coverage != 1.0:
            failures.append("cobertura de linhas alteradas não é 100%")
        if verification.changed_branch_coverage != 1.0:
            failures.append("cobertura de ramos alterados não é 100%")
        if verification.passed_edge_cases != verification.required_edge_cases:
            failures.append("matriz de edge cases incompleta")
        if verification.max_changed_function_complexity > self.max_changed_function_complexity:
            failures.append("complexidade ciclomática acima do limite")
        if verification.duplication_ratio > self.max_duplication_ratio:
            failures.append("duplicação acima do limite")
        for label, value in {
            "violação SOLID": verification.solid_violations,
            "erro de lint": verification.lint_errors,
            "erro de tipos": verification.type_errors,
            "code smell": verification.code_smells,
            "lacuna de tratamento de erro": verification.error_handling_gaps,
            "vulnerabilidade crítica": verification.critical_vulnerabilities,
            "vulnerabilidade alta": verification.high_vulnerabilities,
            "segredo exposto": verification.secrets_found,
        }.items():
            if value:
                failures.append(f"{label}: {value}")
        if verification.protected_files_changed:
            failures.append("arquivo de política sensível alterado")
        if verification.quality_gates_weakened:
            failures.append("gate de qualidade enfraquecido")
        missing_owasp = REQUIRED_OWASP_CHECKS - {
            name for name, passed in verification.owasp_checks.items() if passed
        }
        if missing_owasp:
            failures.append("OWASP sem validação completa: " + ", ".join(sorted(missing_owasp)))
        if not review.evidence or not verification.evidence:
            failures.append("evidência insuficiente")
        return tuple(failures)

    def is_approved(self, review: ReviewReport, verification: VerificationReport) -> bool:
        return not self.failures(review, verification)

    def score(self, review: ReviewReport, verification: VerificationReport) -> int:
        """Score de risco: menor é melhor e zero atende todos os gates objetivos."""
        finding_score = sum(SEVERITY_WEIGHT[finding.severity] for finding in review.findings)
        verification_score = (
            int(not verification.build_passed) * 10_000
            + (verification.tests_total - verification.tests_passed) * 5_000
            + int((1 - verification.changed_line_coverage) * 10_000)
            + int((1 - verification.changed_branch_coverage) * 10_000)
            + len(verification.required_edge_cases - verification.passed_edge_cases) * 2_000
            + max(0, verification.max_changed_function_complexity - self.max_changed_function_complexity) * 100
            + max(0, verification.duplicate_lines - int(verification.total_lines * self.max_duplication_ratio)) * 10
            + (verification.solid_violations + verification.lint_errors + verification.type_errors) * 500
            + (verification.code_smells + verification.error_handling_gaps) * 100
            + verification.critical_vulnerabilities * 10_000
            + verification.high_vulnerabilities * 1_000
            + verification.secrets_found * 10_000
            + int(verification.protected_files_changed) * 10_000
            + int(verification.quality_gates_weakened) * 10_000
            + len(REQUIRED_OWASP_CHECKS - {name for name, passed in verification.owasp_checks.items() if passed}) * 1_000
        )
        return finding_score + verification_score
