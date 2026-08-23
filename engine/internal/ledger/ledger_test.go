package ledger_test

import (
	"strings"
	"testing"
	"time"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/ledger"
	"skillbrew/engine/internal/ports"
)

var t0 = time.Date(2026, 8, 25, 12, 0, 0, 0, time.UTC)

func seeded() *ledger.Ledger {
	return ledger.New([]contract.PrecompiledBelief{
		{ClaimID: "b1", Skill: "Redis", Statement: "Redis is single-threaded"},
		{ClaimID: "b2", Skill: "Go", Statement: "goroutines are OS threads"},
	}, t0)
}

func TestTheLedgerIsSeededBeforeTheFirstQuestion(t *testing.T) {
	// The persona's false beliefs exist at turn 0. Inventing them mid-
	// interview instead would mean two sessions on the same contract held
	// different beliefs, which is exactly what seed_fingerprint promises
	// cannot happen.
	l := seeded()
	live := l.Live()
	if len(live) != 2 {
		t.Fatalf("got %d seeded claims, want 2", len(live))
	}
	for _, e := range live {
		if e.Turn != 0 {
			t.Errorf("%s seeded at turn %d, want 0", e.ClaimID, e.Turn)
		}
		if e.Origin != ports.OriginPrecompiled {
			t.Errorf("%s origin = %q, want %q", e.ClaimID, e.Origin, ports.OriginPrecompiled)
		}
	}
}

func TestPrecompiledAndRuntimeClaimsAreTellableApart(t *testing.T) {
	// "Was this persona designed to believe it, or did it say it on the
	// day" is a question the grader asks, so the id answers it.
	l := seeded()
	e := l.Append("Redis", "we used it for sessions too", ports.StanceAsserted,
		ports.OriginSpoken, 3, t0)
	if !strings.HasPrefix(e.ClaimID, "r") {
		t.Fatalf("runtime claim id = %q, want an r* id", e.ClaimID)
	}
}

// ---------------------------------------------------------------------------
// Task 34's done-when: "offline tests show the guard averting a planted
// contradiction."
// ---------------------------------------------------------------------------

func TestAPlantedContradictionIsCaught(t *testing.T) {
	l := seeded()
	// Turn 19 reverses what turn 0 established. This is the exact failure
	// the ledger exists for: without it the persona asserts both, and the
	// report cannot tell whether the interviewer missed a contradiction or
	// there never was one.
	existing, reason, found := l.FindContradiction("Redis", "Redis is not single-threaded")
	if !found {
		t.Fatal("a direct negation of a seeded belief must be caught")
	}
	if existing.ClaimID != "b1" || reason != "negation_flip" {
		t.Fatalf("caught %s via %q, want b1 via negation_flip", existing.ClaimID, reason)
	}
}

func TestRestatingAClaimIsNotAContradiction(t *testing.T) {
	// A persona repeating itself is normal, and downgrading that note to
	// "restate what you said before" would be a no-op that reads as a bug.
	l := seeded()
	if _, _, found := l.FindContradiction("Redis", "Redis is single-threaded"); found {
		t.Fatal("restating an existing claim must not count as contradiction")
	}
}

func TestContradictionLookupIsScopedToTheSkill(t *testing.T) {
	l := seeded()
	if _, _, found := l.FindContradiction("Go", "Redis is not single-threaded"); found {
		t.Fatal("a claim about Go must not collide with a Redis belief")
	}
}

func TestSkillMatchingSurvivesCasingAndSpacing(t *testing.T) {
	// The skill name comes from the job spec on one side and a model on the
	// other; "System Design" and "system  design" are the same bucket.
	l := ledger.New([]contract.PrecompiledBelief{
		{ClaimID: "b1", Skill: "System Design", Statement: "sharding fixes every scale problem"},
	}, t0)
	if _, _, found := l.FindContradiction("system  design", "sharding does not fix every scale problem"); !found {
		t.Fatal("skill matching must normalize case and whitespace")
	}
}

func TestAHedgeCommitsToNothingSoNothingContradictsIt(t *testing.T) {
	l := ledger.New(nil, t0)
	l.Append("Redis", "Redis is single-threaded", ports.StanceHedged, ports.OriginSpoken, 2, t0)
	if _, _, found := l.FindContradiction("Redis", "Redis is not single-threaded"); found {
		t.Fatal("a hedged claim is not a commitment and cannot be contradicted")
	}
}

// ---------------------------------------------------------------------------
// Walk-back — the only sanctioned reversal (plan §6 layer 7)
// ---------------------------------------------------------------------------

func TestAWalkBackSupersedesRatherThanDeletes(t *testing.T) {
	l := seeded()
	e, ok := l.WalkBack("b1", "actually I'm not sure that was right", 11, t0)
	if !ok {
		t.Fatal("walking back a known claim should succeed")
	}
	if e.Supersedes != "b1" {
		t.Fatalf("supersedes = %q, want b1", e.Supersedes)
	}

	// The retracted claim leaves the live set...
	for _, live := range l.Live() {
		if live.ClaimID == "b1" {
			t.Fatal("a walked-back claim must not stay live")
		}
	}
	// ...but stays in the timeline. A persona that said something wrong and
	// corrected it is a different session from one that never said it, and
	// the report is about the interviewer either way.
	var seen bool
	for _, all := range l.All() {
		if all.ClaimID == "b1" {
			seen = true
		}
	}
	if !seen {
		t.Fatal("the belief timeline must retain the superseded claim")
	}
}

func TestAWalkBackClearsTheWayForTheCorrectedClaim(t *testing.T) {
	l := seeded()
	l.WalkBack("b1", "actually, I've only read about it", 11, t0)
	if _, _, found := l.FindContradiction("Redis", "Redis is not single-threaded"); found {
		t.Fatal("once walked back, the old claim must stop blocking the correction")
	}
}

func TestWalkingBackAnUnknownClaimFails(t *testing.T) {
	l := seeded()
	if _, ok := l.WalkBack("b99", "never said it", 3, t0); ok {
		t.Fatal("walking back a claim that does not exist must fail loudly")
	}
}

// ---------------------------------------------------------------------------
// The two consumers (task 34)
// ---------------------------------------------------------------------------

func TestTheSpeakerSummaryIsCappedBecauseItCompetesForContext(t *testing.T) {
	l := ledger.New(nil, t0)
	for i := 0; i < 40; i++ {
		l.Append("Redis", "claim number "+string(rune('a'+i%26)), ports.StanceAsserted,
			ports.OriginSpoken, i, t0)
	}
	// One header line plus at most the cap in claim lines.
	got := strings.Count(strings.TrimSpace(l.SpeakerSummary(0)), "\n")
	if got > ledger.DefaultSpeakerSummaryLines {
		t.Fatalf("summary ran to %d lines; it is injected into a realtime context", got)
	}
}

func TestTheThinkerGetsTheWholeTimelineIncludingWalkBacks(t *testing.T) {
	// A truncated ledger makes the reasoning model produce confidently
	// contradictory notes, which is worse than no ledger at all.
	l := seeded()
	l.WalkBack("b1", "actually I misremembered", 11, t0)
	s := l.ThinkerSummary()
	for _, want := range []string{"b1", "b2", "WALKED BACK", "supersedes b1"} {
		if !strings.Contains(s, want) {
			t.Errorf("thinker summary missing %q:\n%s", want, s)
		}
	}
}

func TestTheSameInputsProduceTheSameLedger(t *testing.T) {
	// Determinism story: two sessions on one contract share identical
	// seeded claims and diverge only in phrasing.
	a, b := seeded(), seeded()
	if a.ThinkerSummary() != b.ThinkerSummary() {
		t.Fatal("identical inputs must produce an identical ledger")
	}
}
