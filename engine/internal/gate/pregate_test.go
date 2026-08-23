package gate_test

import (
	"testing"

	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/gate"
)

func testGate() *gate.Gate {
	return gate.New(&contract.EngineContract{
		KnowledgeCeiling: map[string]int{
			"Redis":         2, // cannot really discuss it
			"System design": 3, // at the threshold
			"Go":            7, // comfortable
		},
		PregateLexicon: map[string]contract.PregateSkill{
			"Redis": {DeferAtOrBelow: 3, Aliases: []string{
				"redis", "cache invalidation", "how did you scale redis",
			}},
			"System design": {DeferAtOrBelow: 3, Aliases: []string{
				"system design", "design", "walk me through the architecture",
			}},
			"Go": {DeferAtOrBelow: 3, Aliases: []string{"go", "goroutine"}},
		},
	})
}

func TestAProbeBelowTheCeilingDefers(t *testing.T) {
	v := testGate().Classify("So how did you handle cache invalidation there")
	if !v.Defer || v.Skill != "Redis" {
		t.Fatalf("verdict = %+v, want a Redis defer", v)
	}
}

func TestAProbeTheCandidateCanHandleDoesNotDefer(t *testing.T) {
	// Ceiling 7 against a threshold of 3: the speech model answers unaided.
	// Deferring here would cost a stall clip and a reasoning call on a
	// question the persona can simply answer.
	v := testGate().Classify("Tell me about goroutine leaks")
	if v.Skill != "Go" {
		t.Fatalf("skill = %q, want Go", v.Skill)
	}
	if v.Defer {
		t.Fatal("a skill above its threshold must not defer")
	}
}

func TestTheThresholdIsInclusive(t *testing.T) {
	// defer_at_or_below means at or below. A skill sitting exactly on the
	// threshold is one the persona cannot really discuss.
	v := testGate().Classify("Can you walk me through the architecture")
	if !v.Defer || v.Skill != "System design" {
		t.Fatalf("verdict = %+v, want a System design defer", v)
	}
}

func TestClassificationHappensFromAPartialUtterance(t *testing.T) {
	// The whole point: the decision is made from the question's first half,
	// because a stall clip has to be on the wire 50 ms after end-of-turn
	// and no reasoning model answers in 50 ms.
	g := testGate()
	if v := g.Classify("So, how did you scale red"); v.Skill != "" {
		t.Fatalf("a half-typed word must not match: %+v", v)
	}
	if v := g.Classify("So, how did you scale redis when"); !v.Defer {
		t.Fatal("the verdict should be available before the question ends")
	}
}

func TestAliasesMatchOnWordBoundariesOnly(t *testing.T) {
	// "go" inside "going" is the failure that makes a persona stall on
	// every other sentence an interviewer says.
	g := testGate()
	for _, utterance := range []string{
		"I'm going to ask about your background",
		"a long time ago",
		"we should get going",
	} {
		if v := g.Classify(utterance); v.Skill != "" {
			t.Errorf("%q matched %+v; 'go' must not fire inside another word", utterance, v)
		}
	}
	if v := g.Classify("do you write Go at work"); v.Skill != "Go" {
		t.Errorf("%+v: the standalone word should still match", v)
	}
}

func TestTheMoreSpecificAliasWins(t *testing.T) {
	// Both "design" and "system design" are in the lexicon. The longer one
	// must claim the question, or the specific skill loses to the generic.
	v := testGate().Classify("let's talk about system design for a moment")
	if v.MatchedAlias != "system design" {
		t.Fatalf("matched %q, want the longer alias", v.MatchedAlias)
	}
}

func TestNothingMatchesMeansNoVerdict(t *testing.T) {
	v := testGate().Classify("So tell me a bit about yourself")
	if v.Skill != "" || v.Defer {
		t.Fatalf("verdict = %+v, want an empty verdict on small talk", v)
	}
}

func TestAContractWithNoLexiconNeverDefers(t *testing.T) {
	// v1.0-v1.2 contracts carry no lexicon. The engine degrades to the
	// single-model path rather than refusing to run or stalling on
	// everything.
	g := gate.New(&contract.EngineContract{})
	if v := g.Classify("how did you scale redis"); v.Skill != "" || v.Defer {
		t.Fatalf("verdict = %+v, want an empty verdict with no lexicon", v)
	}
}

func TestALexiconEntryWithNoCeilingDoesNotDefer(t *testing.T) {
	// An inconsistently-compiled contract. Deferring on every mention would
	// cost a stall clip on every turn; answering is the cheaper failure.
	g := gate.New(&contract.EngineContract{
		PregateLexicon: map[string]contract.PregateSkill{
			"Kafka": {DeferAtOrBelow: 3, Aliases: []string{"kafka"}},
		},
	})
	v := g.Classify("any experience with kafka")
	if v.Skill != "Kafka" || v.Defer {
		t.Fatalf("verdict = %+v, want Kafka recognised but not deferred", v)
	}
}

func TestClassificationIsStableAcrossRuns(t *testing.T) {
	// Map iteration order is randomised in Go. Without a total ordering on
	// the lexicon, two runs of the same session could classify the same
	// sentence differently — reproducibility lost for a reason nobody can
	// see in a log.
	const utterance = "walk me through the architecture and the design"
	first := testGate().Classify(utterance)
	for i := 0; i < 50; i++ {
		if got := testGate().Classify(utterance); got != first {
			t.Fatalf("run %d classified %+v, first run %+v", i, got, first)
		}
	}
}
