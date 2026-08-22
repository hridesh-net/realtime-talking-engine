package arch

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
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
func LoadPackages(moduleDir string) ([]Package, error) {
	cmd := exec.Command("go", "list", "-json", "./...")
	cmd.Dir = moduleDir
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil {
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

// forbiddenPackagePrefixes are the internal package trees only cmd/engined
// may reach, per plan §3/§10: vendor SDKs, wire transports, and the S3 store
// are adapters wired once at the process edge, mirroring this repo's Python
// rule that vendor SDKs live only inside llm/.
var forbiddenPackagePrefixes = []string{
	"internal/vendor",
	"internal/transport",
	"internal/store",
}

// CheckVendorLeakage enforces plan §10 rule 1: no package outside
// cmd/engined imports internal/vendor/…, internal/transport/…, or
// internal/store/…. Both production imports and test imports are in scope —
// a test that reaches around internal/fakes to call a vendor SDK directly
// defeats the point of having fakes just as much as production code would.
func CheckVendorLeakage(pkgs []Package, modulePath string) []Violation {
	var violations []Violation
	for _, pkg := range pkgs {
		rel := relativeImport(pkg.ImportPath, modulePath)
		if under(rel, cmdEnginedPrefix) {
			continue
		}
		for _, imp := range allImports(pkg) {
			if !isModuleInternal(imp, modulePath) {
				continue
			}
			impRel := relativeImport(imp, modulePath)
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
			if rel == p {
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
