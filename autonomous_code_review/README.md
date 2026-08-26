# Loop autônomo de Code Review

Este módulo usa três agentes, mas mantém a decisão de segurança no Python e em ferramentas
independentes. Um LLM pode sugerir, revisar e julgar; ele não consegue aprovar sozinho.

```text
snapshot inicial
      │
      ▼
 Revisor ───────► Verifier em sandbox ───────► Política determinística
      │                                                   │
      │ REPROVADO                                        │ APROVADO
      ▼                                                   ▼
 Desenvolvedor ◄──── feedback estruturado              Juiz
      │                                                   │
      └──────────────────────── novo snapshot ───────────┘
```

## Papéis e prompts

Os prompts prontos para cópia estão em [prompts.py](prompts.py):

- `DEVELOPER_SYSTEM_PROMPT`: corrige somente com base em findings estruturados;
- `REVIEWER_SYSTEM_PROMPT`: aplica OWASP, qualidade, SOLID e cobertura de edge cases;
- `JUDGE_SYSTEM_PROMPT`: formaliza a decisão, sem poder sobrepor os gates objetivos.

Todos instruem o modelo a tratar o próprio repositório como dado não confiável, reduzindo a
superfície de prompt injection via comentários, testes ou documentação.

## Definição operacional de “perfeito e seguro”

Para uma revisão `R` e uma verificação independente `V`, o orquestrador aprova somente se:

```text
R.status = APROVADO
∧ findings(R) = ∅
∧ V.build_passed
∧ V.tests_passed = V.tests_total
∧ V.changed_line_coverage = 1
∧ V.changed_branch_coverage = 1
∧ V.passed_edge_cases = V.required_edge_cases
∧ V.max_changed_function_complexity ≤ 10
∧ V.duplicate_lines / V.total_lines ≤ 0,03
∧ V.solid_violations = V.lint_errors = V.type_errors = 0
∧ V.code_smells = V.error_handling_gaps = 0
∧ V.critical_vulnerabilities = V.high_vulnerabilities = V.secrets_found = 0
∧ ∀c ∈ {A01…A10}, V.owasp_checks[c] = true
∧ V.protected_files_changed = false
∧ V.quality_gates_weakened = false
∧ Juiz.status = APROVADO
```

“Cobertura total” não é uma porcentagem vaga: `required_edge_cases` representa uma matriz explícita
de cenários do domínio. Ela deve incluir, quando aplicável, autorização negada, nulos, limites,
entradas malformadas, duplicidade, falhas de rede/IO, timeout e recuperação.

## Contrato de parada

O único término normal é a string JSON, sem Markdown e sem chaves extras:

```json
{"status":"APROVADO","motivo":"..."}
```

Se esse payload vier do Juiz mas a política falhar, o resultado é `FALHA_CONTRATO`, nunca
`APROVADO`.

## Anti-loop e retorno seguro

`AcceptancePolicy` limita `max_iterations` a sete. Antes disso, o loop aborta se detectar snapshot
repetido, oscilação de findings ou score sem melhoria por transições consecutivas. Os estados de
falha (`ABORTADO_MAX_ITERACOES`, `ABORTADO_SEM_PROGRESSO`, `ABORTADO_FERRAMENTA` e
`FALHA_CONTRATO`) devolvem sempre `best_files`, o candidato de menor score de risco, junto de um
motivo auditável. Ele não é apresentado como código seguro.

O score é determinístico e menor é melhor:

```text
10000·findings_críticos + 1000·altos + 100·médios + 10·baixos
+ penalidades de testes, cobertura, OWASP, complexidade, segredos e gates enfraquecidos
```

## Integração

Implemente duas interfaces pequenas:

```python
class MeuClienteLLM:
    def complete(self, *, system_prompt: str, user_prompt: str) -> str:
        # Chame seu SDK, exigindo resposta JSON estrita.
        ...

class MeuVerifier:
    def verify(self, files: dict[str, str]) -> VerificationReport:
        # Crie worktree efêmero/container sem rede/segredos; execute allowlist fixa:
        # testes, lint, type checking, SAST, SCA, secret scan e medição de cobertura.
        ...
```

Depois injete as implementações em `AutonomousReviewLoop`. Não execute código candidato no
processo do orquestrador; não use `shell=True`; não transforme texto do LLM em comandos. Para
mudanças em autenticação, autorização, criptografia, pagamentos, infraestrutura ou CI, acrescente
aprovação humana obrigatória no `Verifier` ou na política.
