"""Controle determinístico do debate entre Desenvolvedor, Revisor e Juiz."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from .contracts import (
    AcceptancePolicy,
    ContractViolation,
    DeveloperRevision,
    JudgeDecision,
    ReviewReport,
    VerificationReport,
    validate_snapshot,
)
from .prompts import DEVELOPER_SYSTEM_PROMPT, JUDGE_SYSTEM_PROMPT, REVIEWER_SYSTEM_PROMPT


class ChatClient(Protocol):
    """Adaptador para qualquer SDK de LLM, sem acoplamento com um fornecedor."""

    def complete(self, *, system_prompt: str, user_prompt: str) -> str: ...


class Verifier(Protocol):
    """Executa a verificação em sandbox e devolve evidência estruturada."""

    def verify(self, files: Mapping[str, str]) -> VerificationReport: ...


@dataclass(frozen=True)
class IterationRecord:
    iteration: int
    candidate_hash: str
    score: int
    review: ReviewReport
    verification: VerificationReport
    judge: JudgeDecision
    failures: tuple[str, ...]


@dataclass(frozen=True)
class LoopResult:
    terminal_status: str
    best_files: Mapping[str, str]
    best_score: int
    iterations: tuple[IterationRecord, ...]
    approval_json: str | None
    failure_reason: str | None


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractViolation(f"chave JSON duplicada: {key}")
        result[key] = value
    return result


def _strict_json(raw: str, actor: str) -> Mapping[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractViolation(f"{actor} não devolveu JSON")
    try:
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (json.JSONDecodeError, ContractViolation) as exc:
        raise ContractViolation(f"{actor} não devolveu JSON válido") from exc
    if not isinstance(parsed, dict):
        raise ContractViolation(f"{actor} deve devolver um objeto JSON")
    return parsed


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _approval_json(motivo: str) -> str:
    """O único payload terminal de sucesso, com a ordem de chaves do contrato."""
    return json.dumps({"status": "APROVADO", "motivo": motivo}, ensure_ascii=False, separators=(",", ":"))


def _candidate_hash(files: Mapping[str, str]) -> str:
    return hashlib.sha256(_stable_json(dict(files)).encode("utf-8")).hexdigest()


def _review_payload(review: ReviewReport) -> dict[str, Any]:
    return {
        "status": review.status,
        "findings": [
            {
                "id": finding.identifier,
                "severity": finding.severity.value,
                "category": finding.category,
                "file": finding.file,
                "line": finding.line,
                "rule": finding.rule,
                "description": finding.description,
                "remediation": finding.remediation,
            }
            for finding in review.findings
        ],
        "evidence": list(review.evidence),
        "claimed_metrics": dict(review.claimed_metrics),
    }


def _verification_payload(verification: VerificationReport) -> dict[str, Any]:
    return {
        "build_passed": verification.build_passed,
        "tests_total": verification.tests_total,
        "tests_passed": verification.tests_passed,
        "changed_line_coverage": verification.changed_line_coverage,
        "changed_branch_coverage": verification.changed_branch_coverage,
        "required_edge_cases": sorted(verification.required_edge_cases),
        "passed_edge_cases": sorted(verification.passed_edge_cases),
        "max_changed_function_complexity": verification.max_changed_function_complexity,
        "duplication_ratio": verification.duplication_ratio,
        "solid_violations": verification.solid_violations,
        "lint_errors": verification.lint_errors,
        "type_errors": verification.type_errors,
        "code_smells": verification.code_smells,
        "error_handling_gaps": verification.error_handling_gaps,
        "critical_vulnerabilities": verification.critical_vulnerabilities,
        "high_vulnerabilities": verification.high_vulnerabilities,
        "secrets_found": verification.secrets_found,
        "protected_files_changed": verification.protected_files_changed,
        "quality_gates_weakened": verification.quality_gates_weakened,
        "owasp_checks": dict(verification.owasp_checks),
        "evidence": list(verification.evidence),
    }


@dataclass
class AutonomousReviewLoop:
    """Executa no máximo sete revisões; nunca delega o gate de aprovação ao LLM."""

    developer: ChatClient
    reviewer: ChatClient
    judge: ChatClient
    verifier: Verifier
    policy: AcceptancePolicy = field(default_factory=AcceptancePolicy)
    max_stagnant_transitions: int = 2

    def __post_init__(self) -> None:
        if self.max_stagnant_transitions < 1:
            raise ValueError("max_stagnant_transitions deve ser positivo")

    def run(self, initial_files: Mapping[str, str], task: str) -> LoopResult:
        if not initial_files:
            raise ValueError("initial_files não pode ser vazio")
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task deve ser uma string não vazia")

        try:
            current_files = validate_snapshot(initial_files, "initial_files")
        except ContractViolation as exc:
            raise ValueError("initial_files contém snapshot inválido ou inseguro") from exc
        best_files = dict(initial_files)
        best_score: int | None = None
        records: list[IterationRecord] = []
        seen_candidate_hashes: set[str] = set()
        previous_score: int | None = None
        previous_fingerprint: tuple[str, ...] | None = None
        stagnant_transitions = 0

        for iteration in range(1, self.policy.max_iterations + 1):
            try:
                candidate_hash = _candidate_hash(current_files)
                review = self._ask_reviewer(task, current_files)
                verification = self.verifier.verify(current_files)
                failures = self.policy.failures(review, verification)
                score = self.policy.score(review, verification)
                judge = self._ask_judge(review, verification, failures)
            except ContractViolation as exc:
                return self._result(
                    "FALHA_CONTRATO", best_files, best_score, records, None, str(exc)
                )
            except Exception as exc:  # O executor externo falhou: falhar fechado é mais seguro.
                return self._result(
                    "ABORTADO_FERRAMENTA", best_files, best_score, records, None,
                    f"verificação ou chamada de agente falhou: {type(exc).__name__}",
                )

            record = IterationRecord(
                iteration=iteration,
                candidate_hash=candidate_hash,
                score=score,
                review=review,
                verification=verification,
                judge=judge,
                failures=failures,
            )
            records.append(record)
            if best_score is None or score < best_score:
                best_files, best_score = dict(current_files), score

            # Única condição normal de parada: Juiz APROVADO mais todos os gates determinísticos.
            if judge.status == "APROVADO" and self.policy.is_approved(review, verification):
                approval = _approval_json(judge.motivo)
                return self._result("APROVADO", current_files, score, records, approval, None)

            # Uma aprovação contraditória é incidente de protocolo, jamais aprovação implícita.
            if judge.status == "APROVADO":
                return self._result(
                    "FALHA_CONTRATO", best_files, best_score, records, None,
                    "Juiz aprovou uma revisão que não satisfaz os gates objetivos",
                )

            # Não cria uma edição inútil depois da última revisão permitida.
            if iteration == self.policy.max_iterations:
                break

            # Anti-loop: repetição de snapshot, oscilação de achados e falta de melhoria mensurável.
            if candidate_hash in seen_candidate_hashes:
                return self._result(
                    "ABORTADO_SEM_PROGRESSO", best_files, best_score, records, None,
                    "snapshot de código repetido; possível oscilação entre agentes",
                )
            seen_candidate_hashes.add(candidate_hash)

            is_repeated_finding = bool(previous_fingerprint and review.fingerprint == previous_fingerprint)
            no_score_improvement = previous_score is not None and previous_score - score < self.policy.min_score_improvement
            stagnant_transitions = stagnant_transitions + 1 if is_repeated_finding or no_score_improvement else 0
            if stagnant_transitions >= self.max_stagnant_transitions:
                return self._result(
                    "ABORTADO_SEM_PROGRESSO", best_files, best_score, records, None,
                    "findings ou score não melhoraram por ciclos consecutivos",
                )

            try:
                revision = self._ask_developer(task, current_files, record)
            except ContractViolation as exc:
                return self._result("FALHA_CONTRATO", best_files, best_score, records, None, str(exc))
            except Exception as exc:
                return self._result(
                    "ABORTADO_FERRAMENTA", best_files, best_score, records, None,
                    f"chamada do Desenvolvedor falhou: {type(exc).__name__}",
                )
            current_files = dict(revision.files)
            previous_score = score
            previous_fingerprint = review.fingerprint

        return self._result(
            "ABORTADO_MAX_ITERACOES", best_files, best_score, records, None,
            f"limite de {self.policy.max_iterations} iterações atingido sem aprovação",
        )

    @staticmethod
    def _result(
        status: str,
        best_files: Mapping[str, str],
        best_score: int | None,
        records: list[IterationRecord],
        approval_json: str | None,
        failure_reason: str | None,
    ) -> LoopResult:
        return LoopResult(
            terminal_status=status,
            best_files=dict(best_files),
            best_score=best_score if best_score is not None else -1,
            iterations=tuple(records),
            approval_json=approval_json,
            failure_reason=failure_reason,
        )

    def _ask_reviewer(self, task: str, files: Mapping[str, str]) -> ReviewReport:
        payload = {"task": task, "candidate_files": dict(files)}
        raw = self.reviewer.complete(system_prompt=REVIEWER_SYSTEM_PROMPT, user_prompt=_stable_json(payload))
        return ReviewReport.from_mapping(_strict_json(raw, "Revisor"))

    def _ask_developer(
        self, task: str, current_files: Mapping[str, str], last_record: IterationRecord
    ) -> DeveloperRevision:
        payload = {
            "task": task,
            "current_files": dict(current_files),
            "review": _review_payload(last_record.review),
            "verification": _verification_payload(last_record.verification),
            "policy_failures": list(last_record.failures),
            "iteration": last_record.iteration + 1,
        }
        raw = self.developer.complete(system_prompt=DEVELOPER_SYSTEM_PROMPT, user_prompt=_stable_json(payload))
        return DeveloperRevision.from_mapping(_strict_json(raw, "Desenvolvedor"))

    def _ask_judge(
        self, review: ReviewReport, verification: VerificationReport, failures: tuple[str, ...]
    ) -> JudgeDecision:
        payload = {
            "policy_failures": list(failures),
            "review": _review_payload(review),
            "verification": _verification_payload(verification),
        }
        raw = self.judge.complete(system_prompt=JUDGE_SYSTEM_PROMPT, user_prompt=_stable_json(payload))
        return JudgeDecision.from_mapping(_strict_json(raw, "Juiz"))
