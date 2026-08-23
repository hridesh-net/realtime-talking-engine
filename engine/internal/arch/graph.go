package arch

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// Package is one Go package as reported by `go list -json`, trimmed to the
// fields the dependency-graph checks need: its import path and the packages
// it imports directly. Imports and TestImports are kept apart so a check can
// decide whether test-only dependencies are in its scope — internal/fakes,
// for example, is meant to be imported by tests in restricted packages, so
// CheckRestrictedImports deliberately looks only at Imports.
type Package struct {
	// ImportPath is the package's fully qualified import path, e.g.
	// "skillbrew/engine/internal/session".
	ImportPath string
	// Imports lists the packages imported by the package's non-test .go
	// files (go list's "Imports" field).
	Imports []string
	// TestImports lists the packages imported by the package's test files,
	// both the in-package tests (go list's "TestImports") and the external
	// test package (go list's "XTestImports").
	TestImports []string
}

// rawListPackage mirrors the subset of `go list -json` output this package
// reads. go list streams one JSON object per package (not a JSON array), so
// LoadPackages decodes them one at a time with a json.Decoder.
type rawListPackage struct {
	ImportPath   string
	Imports      []string
	TestImports  []string
	XTestImports []string
}

// LoadPackages runs `go list -json ./...` from moduleDir and returns the
// module's packages with their direct (non-transitive) imports. The rules in
// ENGINE_IMPLEMENTATION_PLAN.md §10 are stated in terms of what a package
// imports, not its full transitive closure — if a forbidden import is only
// reachable indirectly, the intermediate package that imports it directly is
// itself a violation, so checking direct imports of every package is
// sufficient.
// The call is bounded by a context rather than left open-ended. `go list` can
// block indefinitely — on a module fetch against an unreachable proxy, most
// obviously — and this function is the first thing the layering gate does, so
// an unbounded call turns a network problem into a CI run that hangs rather
// than fails. Two minutes is far beyond a warm local run and still finite.
func LoadPackages(moduleDir string) ([]Package, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	cmd := exec.CommandContext(ctx, "go", "list", "-json", "./...")
	cmd.Dir = moduleDir
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return nil, fmt.Errorf("arch: go list -json ./... in %s timed out after 2m: %w", moduleDir, ctx.Err())
		}
		return nil, fmt.Errorf("arch: go list -json ./... in %s: %w (stderr: %s)", moduleDir, err, stderr.String())
	}

	dec := json.NewDecoder(&stdout)
	var pkgs []Package
	for dec.More() {
		var raw rawListPackage
		if err := dec.Decode(&raw); err != nil {
			return nil, fmt.Errorf("arch: decode go list output: %w", err)
		}
		testImports := make([]string, 0, len(raw.TestImports)+len(raw.XTestImports))
		testImports = append(testImports, raw.TestImports...)
		testImports = append(testImports, raw.XTestImports...)
		pkgs = append(pkgs, Package{
			ImportPath:  raw.ImportPath,
			Imports:     raw.Imports,
			TestImports: testImports,
		})
	}
	return pkgs, nil
}

// ModulePath reads the `module` directive from moduleDir/go.mod. Checks use
// it to turn a package's absolute import path into a path relative to this
// module (e.g. "internal/session"), so the layering rules are expressed
// against the package tree in ENGINE_IMPLEMENTATION_PLAN.md §3 rather than a
// hardcoded module name.
func ModulePath(moduleDir string) (string, error) {
	path := filepath.Join(moduleDir, "go.mod")
	// #nosec G304 -- moduleDir is resolved from this package's own source
	// location via runtime.Caller, never from external or caller-supplied
	// input, and the filename is a constant.
	data, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("arch: read %s: %w", path, err)
	}
	for _, line := range strings.Split(string(data), "\n") {
		if rest, ok := strings.CutPrefix(strings.TrimSpace(line), "module "); ok {
			return strings.TrimSpace(rest), nil
		}
	}
	return "", fmt.Errorf("arch: no module directive found in %s", path)
}

// Violation is one architecture-rule breach: the offending package or
// location, and what to do instead.
type Violation struct {
	// Subject names the offending package import path, or a "file:line" for
	// a source-level (AST) finding.
	Subject string
	// Detail explains the breach and names the fix.
	Detail string
}

// String renders the violation for test failure output.
func (v Violation) String() string {
	return fmt.Sprintf("%s: %s", v.Subject, v.Detail)
}

// isModuleInternal reports whether imp is a package of this module (as
// opposed to a stdlib or third-party import).
func isModuleInternal(imp, modulePath string) bool {
	return imp == modulePath || strings.HasPrefix(imp, modulePath+"/")
}

// relativeImport strips the module prefix from a module-internal import
// path, e.g. "skillbrew/engine/internal/session" -> "internal/session". An
// import outside the module (stdlib or third-party) is returned unchanged,
// so callers that only care about module-internal packages can compare the
// result against isModuleInternal first.
func relativeImport(imp, modulePath string) string {
	if imp == modulePath {
		return ""
	}
	if rel, ok := strings.CutPrefix(imp, modulePath+"/"); ok {
		return rel
	}
	return imp
}

// under reports whether rel is pkgPrefix itself or nested under it (e.g.
// "internal/vendor/gemini" is under "internal/vendor").
func under(rel, pkgPrefix string) bool {
	return rel == pkgPrefix || strings.HasPrefix(rel, pkgPrefix+"/")
}

// allImports returns the union of a package's production and test imports.
func allImports(pkg Package) []string {
	all := make([]string, 0, len(pkg.Imports)+len(pkg.TestImports))
	all = append(all, pkg.Imports...)
	all = append(all, pkg.TestImports...)
	return all
}

// cmdEnginedPrefix is the module's sole wiring point (see
// cmd/engined/main.go's package doc): the only package tree
// CheckVendorLeakage exempts from the "no vendor/transport/store" rule.
const cmdEnginedPrefix = "cmd/engined"

// Why "internal/vendors" and not "internal/vendor": Go reserves any
// directory literally named "vendor" for its own dependency-vendoring
// mechanism, and a package that lives under one cannot be imported by its
// import path at all — confirmed against a scratch module, where
// probe/internal/vendor/foo can only be imported as "foo". The adapter
// trees originally lived under internal/vendor/ and that would have blocked
// every single adapter (Speaker, Transcriber, TTS, Judge) from ever being
// imported, staying invisible only because Phase 0 shipped them as empty
// doc.go stubs nothing imported yet. The tree was renamed to
// internal/vendors/ for that reason; this comment is what keeps it from
// being "tidied" back to the singular.
var forbiddenPackagePrefixes = []string{
	"internal/vendors",
	"internal/transport",
	"internal/store",
}

// vendorsSharedPrefix is the one package tree under internal/vendors/ that
// forbiddenPackagePrefixes' own members may import from each other. It holds
// vendor-facing plumbing (e.g. the shared Gemini JSON-mode HTTP client) that
// more than one adapter legitimately needs, and nothing else — see
// CheckVendorLeakage's carve-out.
const vendorsSharedPrefix = "internal/vendors/shared"

// CheckVendorLeakage enforces plan §10 rule 1: no package outside
// cmd/engined imports internal/vendors/…, internal/transport/…, or
// internal/store/…. Both production imports and test imports are in scope —
// a test that reaches around internal/fakes to call a vendor SDK directly
// defeats the point of having fakes just as much as production code would.
//
// The one narrow exception: a package under internal/vendors/ may import a
// package under internal/vendors/shared/, since that is where plumbing two
// or more adapters legitimately share lives (e.g. thinkerllm and judgellm
// both speaking the same JSON-mode HTTP client). This is deliberately not a
// general "same-tree siblings may import each other" rule — that would also
// legalise a Speaker adapter importing a reasoning-model adapter, which is
// precisely the coupling rule 1 exists to prevent.
func CheckVendorLeakage(pkgs []Package, modulePath string) []Violation {
	var violations []Violation
	for _, pkg := range pkgs {
		rel := relativeImport(pkg.ImportPath, modulePath)
		if under(rel, cmdEnginedPrefix) {
			continue
		}
		isVendorPkg := under(rel, "internal/vendors")
		for _, imp := range allImports(pkg) {
			if imp == pkg.ImportPath {
				// An external test package (package foo_test) importing the
				// very package under test is go list's ordinary XTestImports
				// shape, not a package reaching into a sibling adapter.
				continue
			}
			if !isModuleInternal(imp, modulePath) {
				continue
			}
			impRel := relativeImport(imp, modulePath)
			if isVendorPkg && under(impRel, vendorsSharedPrefix) {
				continue
			}
			for _, forbidden := range forbiddenPackagePrefixes {
				if under(impRel, forbidden) {
					violations = append(violations, Violation{
						Subject: pkg.ImportPath,
						Detail: fmt.Sprintf(
							"imports %s; only cmd/engined may depend on a vendor/transport/store adapter — "+
								"depend on a port from internal/ports instead and let cmd/engined wire the concrete adapter",
							imp,
						),
					})
				}
			}
		}
	}
	return violations
}

// portsPackage is internal/ports' path relative to the module root.
const portsPackage = "internal/ports"

// CheckPortsIsolation enforces plan §10 rule 2: internal/ports imports no
// other internal package. Ports declares interfaces and shared types only,
// so it must sit at the bottom of the dependency graph — every other package
// can then depend on it without risk of an import cycle.
func CheckPortsIsolation(pkgs []Package, modulePath string) []Violation {
	var violations []Violation
	for _, pkg := range pkgs {
		if relativeImport(pkg.ImportPath, modulePath) != portsPackage {
			continue
		}
		for _, imp := range allImports(pkg) {
			if imp == pkg.ImportPath {
				continue
			}
			if isModuleInternal(imp, modulePath) {
				violations = append(violations, Violation{
					Subject: pkg.ImportPath,
					Detail: fmt.Sprintf(
						"imports %s; internal/ports must import no other internal package so every package can depend on it without a cycle",
						imp,
					),
				})
			}
		}
	}
	return violations
}

// restrictedPackages are the deterministic-core package trees plan §10 rule
// 3 confines to a small allowlist of internal dependencies: session, ledger,
// gate, and stall must stay reachable without pulling in a vendor SDK, a
// transport, or the store.
var restrictedPackages = []string{
	"internal/session",
	"internal/ledger",
	"internal/gate",
	"internal/stall",
}

// restrictedPackageAllowedImports are the only module-internal packages a
// restricted package (see restrictedPackages) may import, besides stdlib and
// third-party packages.
var restrictedPackageAllowedImports = map[string]bool{
	"internal/ports":    true,
	"internal/contract": true,
	"internal/obs":      true,
}

// CheckRestrictedImports enforces plan §10 rule 3: internal/session,
// internal/ledger, internal/gate, and internal/stall import only ports,
// contract, obs, and stdlib. Only production imports (pkg.Imports) are
// checked: tests for these packages are expected to import internal/fakes —
// that is what fakes exists for, per plan task 6 — so applying this rule to
// test files would forbid the intended testing pattern rather than catch a
// real layering violation.
func CheckRestrictedImports(pkgs []Package, modulePath string) []Violation {
	var violations []Violation
	for _, pkg := range pkgs {
		rel := relativeImport(pkg.ImportPath, modulePath)
		isRestricted := false
		for _, p := range restrictedPackages {
			if under(rel, p) {
				isRestricted = true
				break
			}
		}
		if !isRestricted {
			continue
		}
		for _, imp := range pkg.Imports {
			if !isModuleInternal(imp, modulePath) {
				continue // stdlib or third-party: allowed
			}
			impRel := relativeImport(imp, modulePath)
			if !restrictedPackageAllowedImports[impRel] {
				violations = append(violations, Violation{
					Subject: pkg.ImportPath,
					Detail: fmt.Sprintf(
						"imports %s; %s may only import internal/ports, internal/contract, internal/obs, and stdlib — move this dependency behind a port",
						imp, rel,
					),
				})
			}
		}
	}
	return violations
}

// adapterAllowedPrefixes are the module-internal package trees a package
// under a forbiddenPackagePrefixes tree (internal/vendors, internal/transport,
// internal/store) may import. These are the process-edge adapters — the plan
// states they may depend on ports, config, obs, the audio helpers, and the
// vendor plumbing shared under internal/vendors/shared, and nothing else
// module-internal: an adapter is wired once at cmd/engined and must not reach
// sideways into the session's deterministic core or into another adapter.
var adapterAllowedPrefixes = []string{
	"internal/ports",
	"internal/config",
	"internal/obs",
	"internal/audio",
	vendorsSharedPrefix,
}

// CheckAdapterImports enforces the plan's adapter-layering rule, stated in
// ENGINE_IMPLEMENTATION_PLAN.md §10 but never wired into this package until
// now: a package under internal/vendors/, internal/transport/, or
// internal/store/ may import, among this module's own packages, only
// internal/ports, internal/config, internal/obs, internal/audio, and
// internal/vendors/shared/….
//
// The restriction applies only to module-internal imports. Third-party and
// stdlib imports are always allowed and outside this rule's concern — an
// adapter's entire job is to speak a vendor's or a transport's wire protocol,
// so github.com/hraban/opus and the Pion WebRTC stack must remain legal.
// Only production imports (pkg.Imports) are checked, matching
// CheckRestrictedImports' precedent: a test importing internal/fakes is the
// intended testing pattern, not a layering violation.
func CheckAdapterImports(pkgs []Package, modulePath string) []Violation {
	var violations []Violation
	for _, pkg := range pkgs {
		rel := relativeImport(pkg.ImportPath, modulePath)
		if !underAny(rel, forbiddenPackagePrefixes) {
			continue
		}
		for _, imp := range pkg.Imports {
			if !isModuleInternal(imp, modulePath) {
				continue // stdlib or third-party: always allowed
			}
			impRel := relativeImport(imp, modulePath)
			if !underAny(impRel, adapterAllowedPrefixes) {
				violations = append(violations, Violation{
					Subject: pkg.ImportPath,
					Detail: fmt.Sprintf(
						"imports %s; an adapter under internal/vendors, internal/transport, or internal/store may only depend on internal/ports, internal/config, internal/obs, internal/audio, or internal/vendors/shared — move this dependency behind a port",
						imp,
					),
				})
			}
		}
	}
	return violations
}
