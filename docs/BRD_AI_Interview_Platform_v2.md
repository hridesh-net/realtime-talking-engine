# Business Requirements Document (BRD)
## AI Interview Platform — Interviewer Training Module

**Version:** 2.0  
**Date:** 2026-08-21  
**Status:** Draft  
**Language:** Go (Golang)  
**Architecture:** Dual-Model AI with Context Harness

---

## 1. Executive Summary

### 1.1 Purpose
This document defines the requirements for evolving an existing dual-model AI interviewer platform to support **interviewer training scenarios**. The platform currently conducts live technical interviews where a human candidate is interviewed by an AI agent. The new requirement introduces a **training mode** where AI-generated candidate personas act as interviewees, enabling scalable interviewer evaluation and calibration.

### 1.2 Current State (As-Is)
- **Working system** in production
- Dual-model architecture: Realtime model (conversation) + Reasoning model (deep thinking)
- Context harness managing conversations up to 1 hour
- Human candidate ↔ AI Interviewer flow
- Interview recording and basic reporting

### 1.3 Future State (To-Be)
- **Live Interview Mode** (existing): Human candidate, AI interviewer
- **Training Mode** (new): AI persona candidate, AI interviewer
- Dynamic persona generation (non-hardcoded, seed-based deterministic)
- Batch interview scheduling (N candidates × M interviewers)
- Standardized evaluation criteria across all interview modes
- Comprehensive reporting with persona audit trails

### 1.4 Build Decision Matrix

| Component | Decision | Rationale |
|-----------|----------|-----------|
| Dual-model client layer | **Revamp** | Add role-aware prompt routing; core client stays |
| Context harness | **Revamp** | Add speaker-agnostic turn abstraction |
| Session orchestrator | **Rebuild** | Needs pluggable turn engines for role reversal |
| Persona generation | **Build new** | Entirely new capability |
| Interview aggregate | **Revamp** | Add `SessionMode` and `AIPersona` fields |
| Recording system | **Revamp** | Add persona metadata; core logic unchanged |
| Report compiler | **Revamp** | Add persona snapshot; criteria unchanged |
| Requirement aggregate | **Keep** | No changes needed |

---

## 2. Business Context

### 2.1 Problem Statement
Organizations need to train and calibrate human interviewers at scale. Current approaches:
- Require real candidates (expensive, inconsistent)
- Use static role-play scripts (unrealistic)
- Lack standardized evaluation rubrics (subjective)

### 2.2 Solution
A deterministic, AI-driven training platform that:
1. Generates diverse, realistic candidate personas
2. Conducts parallel interview sessions (AI interviewer ↔ AI persona)
3. Records and evaluates against fixed criteria
4. Produces comparable reports for interviewer calibration

### 2.3 Success Metrics
- **Determinism:** Same seed → same persona (for reproducibility)
- **Scalability:** Support 4+ parallel training sessions per requirement
- **Consistency:** All reports use identical criteria rubric
- **Auditability:** Full persona snapshot embedded in every report

---

## 3. Detailed Requirements

### 3.1 Functional Requirements

#### FR-001: Session Mode Support
The system MUST support two distinct session modes:
- **LIVE_INTERVIEW:** Human candidate, AI interviewer (existing)
- **TRAINING_INTERVIEWER:** AI persona candidate, AI interviewer (new)

**Acceptance Criteria:**
- Mode is set at interview creation time and immutable
- Mode determines which turn engine is used
- Mode is persisted and visible in all reports

#### FR-002: Dynamic Persona Generation
The system MUST generate candidate personas dynamically using a seed-based deterministic algorithm.

**Acceptance Criteria:**
- Personas are generated from `SHA256(RequirementID + InterviewID + Index)`
- Each persona includes: name, background, communication style, technical depth, confidence level, nervousness level, problem approach
- Persona attributes are scored 1-10 with variance descriptors
- Persona template bounds are code-defined (not configurable at runtime)
- Generation uses the Reasoning model (temperature ≤ 0.2)
- Persona fingerprint is computed for integrity verification

#### FR-003: Batch Interview Scheduling
The system MUST support scheduling N training interviews for a single requirement.

**Acceptance Criteria:**
- API accepts `candidate_count` (e.g., 4)
- System generates exactly N unique personas
- Each persona is assigned to one interview session
- One or more interviewers can be assigned to each session
- All interviews are persisted before execution begins

#### FR-004: Role-Reversible Turn Engine
The system MUST support pluggable turn generation based on session mode.

**Acceptance Criteria:**
- `TurnEngine` interface abstracts candidate response source
- Live mode: candidate turn comes from human audio input
- Training mode: candidate turn comes from Realtime model with persona prompt
- Interviewer turn always uses Realtime model (unchanged)
- Turn engine selection is mode-driven, not hardcoded

#### FR-005: Fixed Evaluation Criteria
The system MUST evaluate all interviews against a fixed, versioned criteria set.

**Acceptance Criteria:**
- Criteria are defined in `pkg/criteria/` as constants
- Criteria list: Communication, Problem Solving, Technical Depth, System Design, Cultural Fit, Code Quality
- Criteria cannot be added/removed at runtime
- Scoring uses 0-100 scale with evidence strings
- Criteria version is embedded in every report

#### FR-006: Persona-Aware Reporting
The system MUST embed the candidate persona snapshot in training mode reports.

**Acceptance Criteria:**
- Report includes `PersonaSnapshot` field (null for live mode)
- Persona attributes are visible in report output
- Report includes overall rating (weighted composite)
- Report includes per-criterion scores with evidence
- Report includes transcript reference

#### FR-007: Interview Recording
The system MUST record all interview turns with metadata.

**Acceptance Criteria:**
- Every turn is logged with speaker, content, timestamp
- Training mode turns include persona identifier
- Recording is finalized on session completion
- Recording data is stored with interview ID reference
- Recording supports transcript and optional audio

### 3.2 Non-Functional Requirements

#### NFR-001: Determinism
- Persona generation with identical seed MUST produce identical output
- Evaluation criteria MUST be immutable at runtime
- Report structure MUST be versioned and backward-compatible

#### NFR-002: Scalability
- Support at least 4 concurrent training sessions per requirement
- Context harness MUST handle 1+ hour conversations without token overflow
- Persona generation batch MUST complete within 30 seconds for 4 personas

#### NFR-003: Maintainability (SOLID Compliance)
- **Single Responsibility:** No service handles both persona generation AND interview conduction
- **Open/Closed:** New session modes addable without modifying existing mode logic
- **Liskov Substitution:** All `TurnEngine` implementations interchangeable
- **Interface Segregation:** Repository interfaces focused (no god interfaces)
- **Dependency Inversion:** Application layer depends on ports, not adapters

#### NFR-004: Observability
- Every model call is logged with role, latency, token usage
- Session state transitions are traceable
- Persona generation is auditable via seed fingerprint

#### NFR-005: Testability
- Persona generation is unit-testable (deterministic seeds)
- Turn engines are mockable via interface
- Report compilation is testable with fixture transcripts

---

## 4. Domain Model

### 4.1 Core Entities

```go
// Requirement — the job specification being interviewed for
type Requirement struct {
    ID        RequirementID
    Title     string
    Skills    []Skill
    Seniority Level
    CreatedAt time.Time
}

type Skill struct {
    Name     string
    Category SkillCategory
    Weight   float64
}

type Level int
const (
    Junior Level = iota
    Mid
    Senior
    Staff
)
```

### 4.2 Interview Aggregate

```go
type InterviewID string
type CandidateID string

type Interview struct {
    ID            InterviewID
    RequirementID RequirementID
    Mode          SessionMode           // LIVE_INTERVIEW or TRAINING_INTERVIEWER
    Config        InterviewConfig
    Status        InterviewStatus
    Candidate     *CandidateInfo        // Human candidate (nil in training mode)
    AIPersona     *CandidatePersona     // AI persona (nil in live mode)
    InterviewerIDs []string
    ScheduledAt   time.Time
    CompletedAt   *time.Time
    RecordingID   *string
}

type SessionMode int
const (
    ModeLiveInterview SessionMode = iota
    ModeTrainingInterviewer
)

type InterviewConfig struct {
    CandidateCount int
    Duration       time.Duration
}

type InterviewStatus int
const (
    StatusScheduled InterviewStatus = iota
    StatusInProgress
    StatusCompleted
    StatusFailed
)
```

### 4.3 Persona Value Object

```go
type CandidatePersona struct {
    CandidateID CandidateID
    Name        string
    Background  string
    Attributes  []PersonaAttribute
    Fingerprint string  // SHA256 of serialized attributes
}

type PersonaAttribute struct {
    Name     string  // e.g., "communication_style"
    Score    int     // 1-10
    Variance string  // e.g., "verbose", "concise"
}
```

### 4.4 Report Aggregate

```go
type Report struct {
    InterviewID     string
    CandidateID     string
    Mode            SessionMode
    PersonaSnapshot *CandidatePersona  // nil for live mode
    CriteriaVersion string
    Scores          []CriterionScore
    OverallRating   float64
    Summary         string
    GeneratedAt     int64
}

type CriterionScore struct {
    Criterion EvaluationCriterion
    Value     int
    Evidence  string
    Timestamp int64
}
```

---

## 5. Architecture Design

### 5.1 Layered Architecture (Clean/Hexagonal)

```
┌─────────────────────────────────────────────┐
│              Presentation Layer              │
│         (HTTP/gRPC handlers — cmd/)         │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│            Application Layer               │
│  (Use cases: scheduler, conductor, report) │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│              Domain Layer                  │
│     (Entities, value objects, services)    │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│               Ports Layer                 │
│    (Interfaces: inbound & outbound)        │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│             Adapters Layer                 │
│  (AI clients, DB repos, recorders, etc.)   │
└─────────────────────────────────────────────┘
```

### 5.2 Component Responsibilities

| Component | Layer | Responsibility |
|-----------|-------|---------------|
| `InterviewScheduler` | Application | Creates interview batches, triggers persona generation |
| `PersonaGenerator` | Application | Generates N personas deterministically from seed |
| `SessionOrchestrator` | Application | Runs interview loop, delegates to TurnEngine |
| `ContextHarness` | Domain | Manages conversation state, summarization, token budgets |
| `TurnEngine` | Domain (interface) | Abstraction over candidate response source |
| `ReportCompiler` | Application | Evaluates transcript against fixed criteria |
| `ModelClient` | Port (outbound) | Unified LLM client with role-aware routing |
| `InterviewRepository` | Port (outbound) | Persistence for interview aggregates |
| `RecordingRepository` | Port (outbound) | Persistence for session recordings |
| `SessionRecorder` | Port (outbound) | Real-time turn logging during session |

### 5.3 Dual-Model Integration

```
┌─────────────────┐     ┌──────────────────┐
│  Realtime Model │     │  Reasoning Model │
│  (temperature   │     │  (temperature    │
│   0.7, fast)    │     │   0.1, deep)     │
└────────┬────────┘     └────────┬─────────┘
         │                       │
         └───────────┬───────────┘
                     │
            ┌────────▼────────┐
            │   ModelClient   │  ← Port interface
            │  (role-aware)   │
            └────────┬────────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
    ┌────▼────┐ ┌───▼────┐ ┌───▼────┐
    │Interviewer│ │Persona │ │Report  │
    │  Prompt │ │ Prompt │ │Eval    │
    └─────────┘ └────────┘ └────────┘
```

**ModelRole enum:**
```go
type ModelRole int
const (
    RoleRealtime  ModelRole = iota  // Conversational, low latency
    RoleReasoning ModelRole = iota  // Analytical, high accuracy
)
```

### 5.4 Turn Engine Strategy

```go
// Domain interface — all implementations must satisfy
type TurnEngine interface {
    GetInterviewerTurn(ctx context.Context, harness *ContextHarness) (string, error)
    GetCandidateTurn(ctx context.Context, harness *ContextHarness, lastInterviewerMsg string) (string, error)
}

// Implementation 1: Live Interview (existing)
type LiveTurnEngine struct {
    realtimeClient ModelClient
    audioCapture   AudioCapture
}

// Implementation 2: Training (new)
type TrainingTurnEngine struct {
    realtimeClient  ModelClient  // Same as interviewer — prompt differs
    persona         CandidatePersona
}
```

---

## 6. API Specification

### 6.1 Create Training Batch

```http
POST /api/v1/requirements/{requirement_id}/training-batch
Content-Type: application/json

{
  "candidate_count": 4,
  "interviewer_ids": ["ai-interviewer-1"],
  "duration_minutes": 60
}
```

**Response:**
```json
{
  "batch_id": "batch-uuid",
  "interviews": [
    {
      "interview_id": "int-1",
      "persona": {
        "name": "Alex Chen",
        "background": "5 years backend, nervous communicator",
        "attributes": [...]
      }
    }
  ]
}
```

### 6.2 Start Interview Session

```http
POST /api/v1/interviews/{interview_id}/start
```

**Behavior:**
- Loads interview configuration
- Initializes context harness
- Selects TurnEngine based on `Mode`
- Begins turn loop

### 6.3 Get Interview Report

```http
GET /api/v1/interviews/{interview_id}/report
```

**Response:**
```json
{
  "interview_id": "int-1",
  "mode": "training_interviewer",
  "persona_snapshot": { ... },
  "criteria_version": "v1.0",
  "scores": [
    {
      "criterion": "communication",
      "value": 72,
      "evidence": "Candidate explained trade-offs clearly..."
    }
  ],
  "overall_rating": 78.5,
  "summary": "Strong technical skills..."
}
```

---

## 7. Data Flow

### 7.1 Training Batch Creation Flow

```
1. Client → POST /training-batch (count=4, requirement_id=X)
2. Handler → InterviewScheduler.ScheduleTrainingBatch()
3. Scheduler → PersonaGenerator.GenerateBatch(seed_base)
4. Generator → Reasoning Model → 4 Persona JSON objects
5. Scheduler → InterviewRepository.Save() × 4
6. Handler → Return 4 Interview IDs + Persona previews
```

### 7.2 Interview Session Flow

```
1. Client → POST /interviews/{id}/start
2. Handler → SessionOrchestrator.Conduct()
3. Orchestrator → Load Interview + Persona
4. Orchestrator → Select TurnEngine (mode-driven)
5. Loop:
   a. TurnEngine.GetInterviewerTurn() → Realtime Model
   b. SessionRecorder.LogTurn("interviewer", msg)
   c. TurnEngine.GetCandidateTurn() → Human OR Realtime+Persona
   d. SessionRecorder.LogTurn("candidate", msg)
   e. ContextHarness.AddTurn() + Summarize if needed
   f. Check completion (duration, natural end, turn limit)
6. Orchestrator → SessionRecorder.Finalize()
7. Orchestrator → Interview.Complete(recording_id)
```

### 7.3 Report Generation Flow

```
1. Client → GET /interviews/{id}/report
2. Handler → ReportCompiler.Compile()
3. Compiler → Load Recording (transcript)
4. For each fixed criterion:
   a. Build evaluation prompt
   b. Call Reasoning Model (temperature 0.1)
   c. Parse score + evidence
5. Compute overall rating
6. Embed persona snapshot (if training mode)
7. Return Report
```

---

## 8. Go Implementation Guidelines

### 8.1 Module Structure

```
interview-platform/
├── cmd/
│   ├── server/          # HTTP/gRPC API entrypoint
│   └── trainer/         # CLI for batch training jobs
├── internal/
│   ├── domain/          # Entities, VO, errors (no external deps)
│   ├── application/     # Use cases (orchestration)
│   ├── service/         # Domain services (harness, turn logic)
│   ├── ports/
│   │   ├── inbound/     # API interfaces (driving adapters)
│   │   └── outbound/    # Infrastructure interfaces (driven adapters)
│   └── adapters/
│       ├── ai/          # OpenAI/Anthropic clients
│       ├── storage/     # Postgres, Redis
│       └── recorder/    # S3, transcript logger
├── pkg/
│   ├── criteria/        # Fixed evaluation criteria (constants)
│   └── seed/            # Deterministic seed utilities
└── go.mod
```

### 8.2 Dependency Rules

```
domain → (no imports from other layers)
application → domain, ports
service → domain
ports → domain
adapters → domain, ports, external libs
```

### 8.3 Error Handling

```go
// domain/errors.go
package domain

var (
    ErrInvalidCandidateCount = errors.New("candidate count must be > 0")
    ErrInterviewNotStarted   = errors.New("interview has not started")
    ErrInvalidSessionMode    = errors.New("invalid session mode")
    ErrPersonaNotFound       = errors.New("persona not found for training mode")
)
```

### 8.4 Context Harness Design

```go
// service/context_harness.go
type ContextHarness struct {
    interviewID   domain.InterviewID
    requirement   domain.Requirement
    persona       *domain.CandidatePersona  // nil in live mode

    turns         []TurnEntry
    summary       string
    keyFacts      []string

    strategy      SummarizationStrategy
    maxTokens     int
    currentTokens int
}

type TurnEntry struct {
    Speaker   string    // "interviewer" or "candidate"
    Content   string
    Timestamp time.Time
    Tokens    int
}

// BuildPrompt constructs context-aware prompt for any speaker
func (h *ContextHarness) BuildPrompt(speaker string, history []Message) Prompt {
    // Include: system context + summary + recent turns
}

// AddTurn adds turn and triggers summarization if token threshold exceeded
func (h *ContextHarness) AddTurn(turn TurnEntry) {
    h.turns = append(h.turns, turn)
    h.currentTokens += turn.Tokens
    if h.currentTokens > h.maxTokens*3/4 {
        h.summarize()
    }
}
```

### 8.5 Persona Prompt Template

```go
// adapters/ai/persona_prompt.go
const personaSystemPrompt = `You are a candidate persona synthesizer.
Generate a realistic software engineer candidate with these constraints:
- Name: Realistic, culturally diverse
- Background: 2-8 years experience, plausible career path
- Attributes (score 1-10): communication_style, technical_depth, confidence_level, nervousness_level, problem_approach
- Variance descriptors: provided from template
- Seed: {{.Seed}} — use this for deterministic attribute derivation

Output strict JSON:
{
  "name": string,
  "background": string,
  "attributes": [
    {"name": string, "score": int, "variance": string}
  ],
  "fingerprint": string
}`
```

---

## 9. Fixed Evaluation Criteria

### 9.1 Criteria Definition (pkg/criteria/criteria.go)

```go
package criteria

const Version = "v1.0"

type EvaluationCriterion string

const (
    CriterionCommunication  EvaluationCriterion = "communication"
    CriterionProblemSolving EvaluationCriterion = "problem_solving"
    CriterionTechnicalDepth EvaluationCriterion = "technical_depth"
    CriterionSystemDesign   EvaluationCriterion = "system_design"
    CriterionCulturalFit    EvaluationCriterion = "cultural_fit"
    CriterionCodeQuality    EvaluationCriterion = "code_quality"
)

var AllCriteria = []EvaluationCriterion{
    CriterionCommunication,
    CriterionProblemSolving,
    CriterionTechnicalDepth,
    CriterionSystemDesign,
    CriterionCulturalFit,
    CriterionCodeQuality,
}

// Weights for overall rating computation
var CriteriaWeights = map[EvaluationCriterion]float64{
    CriterionCommunication:  0.15,
    CriterionProblemSolving: 0.25,
    CriterionTechnicalDepth: 0.25,
    CriterionSystemDesign:   0.15,
    CriterionCulturalFit:    0.10,
    CriterionCodeQuality:    0.10,
}
```

### 9.2 Evaluation Prompt Template

```go
const evaluationSystemPrompt = `You are an expert technical interviewer evaluator.
Evaluate the candidate STRICTLY on the criterion: {{.Criterion}}.

Rubric:
- 90-100: Exceptional — exceeds senior expectations
- 70-89: Strong — meets expectations with minor gaps
- 50-69: Adequate — meets minimum with notable gaps
- 30-49: Weak — below expectations
- 0-29: Unsatisfactory

Score 0-100. Provide 2-3 sentences of specific evidence from transcript.
Return JSON: {"score": int, "evidence": string}`
```

---

## 10. Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Add `SessionMode` to Interview aggregate
- [ ] Define `TurnEngine` interface
- [ ] Refactor existing orchestrator to use `TurnEngine`
- [ ] Implement `LiveTurnEngine` (extract from existing code)
- [ ] Unit tests for mode-specific routing

### Phase 2: Persona Generation (Week 2)
- [ ] Define `PersonaTemplate` and `CandidatePersona` structs
- [ ] Implement `PersonaGenerator` with seed-based determinism
- [ ] Create persona prompt templates
- [ ] Add `PersonaRepository` port and adapter
- [ ] Unit tests: same seed → same persona

### Phase 3: Training Mode (Week 3)
- [ ] Implement `TrainingTurnEngine`
- [ ] Build persona-aware prompt builder
- [ ] Integrate with existing context harness
- [ ] Add batch scheduling endpoint
- [ ] Integration test: full training session

### Phase 4: Reporting (Week 4)
- [ ] Define fixed criteria in `pkg/criteria/`
- [ ] Implement `ReportCompiler` with criteria evaluation
- [ ] Add persona snapshot to report
- [ ] Create report API endpoint
- [ ] End-to-end test: batch → session → report

### Phase 5: Hardening (Week 5)
- [ ] Context harness stress test (1+ hour sessions)
- [ ] Concurrent session load test
- [ ] Determinism audit: seed → persona → report consistency
- [ ] Documentation and runbooks

---

## 11. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Persona generation non-deterministic | High | Temperature 0.1-0.2, JSON schema validation, seed hashing |
| Context harness loses long-session context | High | Progressive summarization, key fact extraction, token budget alerts |
| Training mode personas feel repetitive | Medium | Template variance arrays, background randomization within bounds |
| Report criteria drift over time | High | Criteria versioned in code, not DB; change requires PR |
| Concurrent sessions overload AI provider | Medium | Rate limiting, request queuing, circuit breaker pattern |

---

## 12. Glossary

| Term | Definition |
|------|-----------|
| **Dual-Model Architecture** | Two AI models: Realtime (fast, conversational) and Reasoning (slow, analytical) |
| **Context Harness** | Domain service managing conversation history, summarization, and token budgets |
| **Turn Engine** | Pluggable abstraction for generating candidate responses (human or AI) |
| **Persona** | Synthetic candidate profile with attributes defining interview behavior |
| **Session Mode** | Enum determining interview configuration (live vs training) |
| **Fixed Criteria** | Immutable evaluation rubric applied uniformly across all interviews |

---

## 13. Appendices

### Appendix A: Existing System Assumptions
- Dual-model client already supports `ModelRole` routing
- Context harness already manages 1+ hour conversations
- Recording system already captures turns with timestamps
- Report system already exists for live interviews
- Interview repository already supports CRUD operations

### Appendix B: Migration Notes
- Add `mode` column to interviews table (default: live)
- Add `ai_persona` JSONB column (nullable)
- Existing live interviews require zero migration logic
- New training mode is additive only

### Appendix C: Testing Strategy
- **Unit:** PersonaGenerator with fixed seeds, TurnEngine mocks, ReportCompiler with fixture transcripts
- **Integration:** Full training session with mocked model client
- **E2E:** Batch creation → session execution → report generation
- **Determinism:** Regression test: same inputs → same outputs across 100 runs

---

**Document Owner:** Engineering Team  
**Reviewers:** Architecture, Product, QA  
**Next Review Date:** 2026-09-21
