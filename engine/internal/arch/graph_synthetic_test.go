package arch_test

// Proof that the dependency-graph checkers (CheckVendorLeakage,
// CheckPortsIsolation, CheckRestrictedImports) actually detect a violation,
// rather than passing only because the current tree happens to be clean.
// Each test builds a small, fabricated []arch.Package graph — the "in-test
// fixture" — under a fake module path, so it exercises the same checker
// function the real assertions in arch_test.go use, with no dependency on
// what other packages in this repo currently look like.

import (
	"testing"

	"skillbrew/engine/internal/arch"
)

const syntheticModule = "example.com/engine"

func TestCheckVendorLeakageDetectsInjectedViolation(t *testing.T) {
	compliant := []arch.Package{
		{
			ImportPath: syntheticModule + "/cmd/engined",
			Imports:    []string{"net/http", syntheticModule + "/internal/vendors/gemini", syntheticModule + "/internal/session"},
		},
		{
			ImportPath: syntheticModule + "/internal/session",
			Imports:    []string{"context", syntheticModule + "/internal/ports"},
		},
	}
	if violations := arch.CheckVendorLeakage(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("compliant fixture flagged: %s", joinViolations(violations))
	}

	// Inject the violation the real rule exists to catch: a non-cmd/engined
	// package reaching directly into a vendor adapter.
	dirty := append([]arch.Package{}, compliant...)
	dirty[1] = arch.Package{
		ImportPath: syntheticModule + "/internal/session",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/vendors/gemini"},
	}
	violations := arch.CheckVendorLeakage(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected vendor import, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/session" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}

	// A test-only import of a vendor package must be caught too — fakes
	// exist precisely so tests never need this.
	viaTest := []arch.Package{{
		ImportPath:  syntheticModule + "/internal/gate",
		Imports:     []string{"context"},
		TestImports: []string{"testing", syntheticModule + "/internal/vendors/openaitx"},
	}}
	if violations := arch.CheckVendorLeakage(viaTest, syntheticModule); len(violations) != 1 {
		t.Fatalf("expected the test-only vendor import to be flagged, got %d violations", len(violations))
	}
}

func TestCheckPortsIsolationDetectsInjectedViolation(t *testing.T) {
	compliant := []arch.Package{{
		ImportPath: syntheticModule + "/internal/ports",
		Imports:    []string{"context", "io", "time"},
	}}
	if violations := arch.CheckPortsIsolation(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("compliant fixture flagged: %s", joinViolations(violations))
	}

	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/ports",
		Imports:    []string{"context", syntheticModule + "/internal/contract"},
	}}
	violations := arch.CheckPortsIsolation(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected internal import, got %d: %s", len(violations), joinViolations(violations))
	}
}

func TestCheckRestrictedImportsDetectsInjectedViolation(t *testing.T) {
	compliant := []arch.Package{{
		ImportPath:  syntheticModule + "/internal/ledger",
		Imports:     []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/contract", syntheticModule + "/internal/obs"},
		TestImports: []string{"testing", syntheticModule + "/internal/fakes"}, // allowed in tests
	}}
	if violations := arch.CheckRestrictedImports(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("compliant fixture flagged: %s", joinViolations(violations))
	}

	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/ledger",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/controlplane"},
	}}
	violations := arch.CheckRestrictedImports(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected controlplane import, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/ledger" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}

// TestSessionImportingAVendorsPackageIsAViolation is the fixture that proves
// bug 1 existed: forbiddenPackagePrefixes used to list the singular
// "internal/vendor", but the on-disk tree is "internal/vendors/" (Go
// reserves any directory literally named "vendor"), so under() never
// matched anything under it and CheckVendorLeakage guarded nothing there.
// Run against the pre-fix prefix list this fixture passes silently — see
// the re-introduction proof recorded for M1.1 — which is exactly the bug.
func TestSessionImportingAVendorsPackageIsAViolation(t *testing.T) {
	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/session",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/vendors/gemini"},
	}}
	violations := arch.CheckVendorLeakage(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the injected internal/vendors import, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/session" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}

// TestAVendorMayImportTheSharedVendorHelper guards the fix required to make
// rule 1 apply to the whole internal/vendors/ tree without breaking the
// legitimate case: thinkerllm and judgellm both speak the same JSON-mode
// vendor client, which lives at internal/vendors/shared/geminijson.
func TestAVendorMayImportTheSharedVendorHelper(t *testing.T) {
	compliant := []arch.Package{{
		ImportPath: syntheticModule + "/internal/vendors/thinkerllm",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/vendors/shared/geminijson"},
	}}
	if violations := arch.CheckVendorLeakage(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("a vendor package importing the shared vendor helper must not be flagged: %s", joinViolations(violations))
	}
}

// TestAVendorImportingAnotherVendorAdapterIsAViolation guards the narrow
// scope of the internal/vendors/shared carve-out: it must not widen into a
// general "same-tree siblings may import each other" rule, which would
// legalise a Speaker adapter importing a reasoning-model adapter — exactly
// the coupling rule 1 exists to prevent.
func TestAVendorImportingAnotherVendorAdapterIsAViolation(t *testing.T) {
	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/vendors/thinkerllm",
		Imports:    []string{"context", syntheticModule + "/internal/vendors/judgellm"},
	}}
	violations := arch.CheckVendorLeakage(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from one adapter importing a sibling adapter, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/vendors/thinkerllm" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}

// TestATransportImportingAVendorsPackageIsAViolation proves rule 1 also
// catches the reverse direction: a transport adapter reaching into a vendor
// adapter is just as much a forbidden cross-adapter dependency as a vendor
// package reaching into another one.
func TestATransportImportingAVendorsPackageIsAViolation(t *testing.T) {
	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/transport/webrtc",
		Imports:    []string{"context", syntheticModule + "/internal/vendors/gemini"},
	}}
	violations := arch.CheckVendorLeakage(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from transport importing a vendor package, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/transport/webrtc" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}

// TestAnAdapterImportingSessionIsAViolation is CheckAdapterImports' core
// case: the design doc's adapter-layering rule exists precisely so an
// adapter cannot reach sideways into the session's deterministic core
// instead of going through a port.
func TestAnAdapterImportingSessionIsAViolation(t *testing.T) {
	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/vendors/thinkerllm",
		Imports:    []string{"context", syntheticModule + "/internal/session"},
	}}
	violations := arch.CheckAdapterImports(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the adapter importing internal/session, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/vendors/thinkerllm" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}

// TestAdaptersMayStillImportThirdPartyPackages guards the wording trap in
// CheckAdapterImports: the rule restricts module-internal imports only, so
// a vendor SDK or transport library (e.g. github.com/hraban/opus, the Pion
// WebRTC stack) — the entire reason an adapter package exists — must remain
// legal, alongside stdlib.
func TestAdaptersMayStillImportThirdPartyPackages(t *testing.T) {
	compliant := []arch.Package{{
		ImportPath: syntheticModule + "/internal/vendors/thinkerllm",
		Imports:    []string{"context", "net/http", "github.com/hraban/opus", syntheticModule + "/internal/ports"},
	}}
	if violations := arch.CheckAdapterImports(compliant, syntheticModule); len(violations) != 0 {
		t.Fatalf("stdlib and third-party imports must not be flagged: %s", joinViolations(violations))
	}
}

// TestARestrictedSubpackageIsAlsoRestricted is the fixture that proves bug
// 2 existed: CheckRestrictedImports used to compare a package's relative
// import path to restrictedPackages with plain equality, so the moment a
// subpackage like internal/session/foo appeared, rule 3 would silently stop
// protecting it. under() (already used by CheckVendorLeakage) fixes this.
func TestARestrictedSubpackageIsAlsoRestricted(t *testing.T) {
	dirty := []arch.Package{{
		ImportPath: syntheticModule + "/internal/session/foo",
		Imports:    []string{"context", syntheticModule + "/internal/ports", syntheticModule + "/internal/controlplane"},
	}}
	violations := arch.CheckRestrictedImports(dirty, syntheticModule)
	if len(violations) != 1 {
		t.Fatalf("expected exactly 1 violation from the restricted subpackage's disallowed import, got %d: %s", len(violations), joinViolations(violations))
	}
	if violations[0].Subject != syntheticModule+"/internal/session/foo" {
		t.Fatalf("violation names the wrong package: %+v", violations[0])
	}
}
