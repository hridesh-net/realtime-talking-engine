// Command engined is the interview engine's process entrypoint. It wires
// concrete adapters into the session core and serves the HTTP control
// surface. This is the ONLY wiring point in the module: nothing outside
// cmd/engined may import a vendor/, transport/, or store/ package.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"skillbrew/engine/internal/config"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/session"
)

// shutdownTimeout bounds how long engined waits, on SIGINT/SIGTERM, for the
// HTTP server to drain in-flight requests and for live sessions to stop
// before exiting anyway.
const shutdownTimeout = 30 * time.Second

// readHeaderTimeout bounds how long the HTTP server waits to read a
// request's headers, closing slow-header connections rather than holding a
// goroutine open indefinitely (gosec G112 / slowloris).
const readHeaderTimeout = 10 * time.Second

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("engined: fatal", "err", err)
		os.Exit(1)
	}
}

// run wires config, adapters, the session manager, and HTTP together, then
// serves until a shutdown signal arrives or the server fails, draining
// gracefully either way.
func run(logger *slog.Logger) error {
	addr := flag.String("addr", ":8080", "address the engine's HTTP server listens on")
	sampleContract := flag.Bool("dev-sample-contract", false,
		"serve the checked-in sample persona to every session instead of fetching "+
			"from the control plane; development only")
	flag.Parse()

	cfg, err := config.LoadFromEnv()
	if err != nil {
		return fmt.Errorf("engined: load config: %w", err)
	}
	logger.Info("config loaded",
		"control_plane_base_url", cfg.ControlPlaneBaseURL,
		"session_cost_cap_usd", cfg.SessionCostCapUSD,
		"session_duration_cap", cfg.SessionDurationCap,
	)

	// internal/controlplane's HTTP ContractSource (plan §14 task 46) does not
	// exist yet, so the only source available is the checked-in sample
	// persona. Serving that is correct for the walking skeleton and wrong for
	// anything else: it hands every candidate_id the same person, which would
	// invalidate every training session while looking perfectly healthy.
	// Refusing to start without an explicit opt-in keeps that failure loud —
	// a placeholder that boots silently is one nobody removes.
	if !*sampleContract {
		return errors.New(
			"engined: no control-plane ContractSource yet (plan task 46); " +
				"pass -dev-sample-contract to run against the checked-in sample persona")
	}
	logger.Warn("serving the checked-in sample persona to every session — development only")
	contractSource, err := fakes.NewSampleContractSource()
	if err != nil {
		return fmt.Errorf("engined: load sample contract source: %w", err)
	}

	manager := session.NewManager(realClock{}, contractSource, logger)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	session.NewHandler(manager, logger).Register(mux)

	server := &http.Server{
		Addr:              *addr,
		Handler:           mux,
		ReadHeaderTimeout: readHeaderTimeout,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	serveErr := make(chan error, 1)
	go func() {
		logger.Info("engined listening", "addr", *addr)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serveErr <- fmt.Errorf("engined: serve: %w", err)
			return
		}
		serveErr <- nil
	}()

	select {
	case <-ctx.Done():
		logger.Info("engined: shutdown signal received")
	case err := <-serveErr:
		return err
	}

	return shutdown(logger, server, manager)
}

// shutdown drains the HTTP server and stops every live session, bounded by
// shutdownTimeout. Both are attempted even if one fails, so a slow or
// wedged HTTP drain never prevents live sessions from being stopped (and
// their goroutines released) or vice versa.
func shutdown(logger *slog.Logger, server *http.Server, manager *session.Manager) error {
	ctx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()

	var errs []error
	if err := server.Shutdown(ctx); err != nil {
		errs = append(errs, fmt.Errorf("engined: http server shutdown: %w", err))
	}
	if err := manager.Shutdown(ctx); err != nil {
		errs = append(errs, fmt.Errorf("engined: session manager shutdown: %w", err))
	}
	if len(errs) > 0 {
		return errors.Join(errs...)
	}
	logger.Info("engined: shutdown complete")
	return nil
}

// handleHealthz reports that the process is up. It does not (yet) check any
// dependency health; deeper session-manager wiring lands alongside later
// phases.
func handleHealthz(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	if err := json.NewEncoder(w).Encode(map[string]string{"status": "ok"}); err != nil {
		slog.Error("engined: healthz encode", "err", err)
	}
}
