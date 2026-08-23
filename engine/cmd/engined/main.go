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
	"skillbrew/engine/internal/contract"
	"skillbrew/engine/internal/fakes"
	"skillbrew/engine/internal/gate"
	"skillbrew/engine/internal/ledger"
	"skillbrew/engine/internal/obs"
	"skillbrew/engine/internal/session"
	"skillbrew/engine/internal/stall"
	"skillbrew/engine/internal/transport/wsfallback"
	"skillbrew/engine/internal/vendors/gemini"
	"skillbrew/engine/internal/vendors/geminitts"
	"skillbrew/engine/internal/vendors/thinkerllm"
)

// mediaPath is where a client attaches its media socket, using the ticket
// returned in the transport answer. It matches the path the answer implies,
// so changing one without the other silently strands every client.
const mediaPath = "/v1/media/ws"

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

	// cfg is non-nil even if the load below fails (see Load's doc comment):
	// every optional field still carries its default or env-derived value,
	// which is what lets BindFlags register real, well-defaulted flags —
	// and "-h" produce a real usage listing — even when a required key is
	// missing. BindFlags must run before Parse: Parse then overwrites
	// cfg's fields in place with anything the operator passed on the
	// command line. Whether the load itself was fatal is checked only
	// after Parse returns, so "-h" is handled (and exits 0) before that
	// check ever runs.
	cfg, loadErr := config.LoadFromEnv()
	cfg.BindFlags(flag.CommandLine)
	flag.Parse()
	// Flags are parsed after Load, so a required key supplied on the command
	// line is still recorded as missing. ResolveFlagOverrides drops the issues
	// whose variable the operator explicitly overrode and keeps the rest, so a
	// flag can actually satisfy the variable it names.
	if err := config.ResolveFlagOverrides(flag.CommandLine, loadErr); err != nil {
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

	// The WebSocket/PCM transport is process-wide, not per-session: it holds
	// the ticket registry that binds an arriving socket to the MediaConn
	// created for it when the offer was accepted. WebRTC is the intended
	// primary path and lands in a later milestone; this one needs no CGo and
	// no ICE, which is what makes it the transport a client can use today.
	media := wsfallback.New(wsfallback.DefaultConfig(), realClock{}, logger)

	// Session events go to stdout for now. Phase 5 routes them to the
	// per-session JSONL artifact that ships to S3 with the recording.
	events := obs.NewEventLog(os.Stdout)
	// The composition root, and the only place that names concrete
	// implementations. internal/session sees ports; which lexicon, which
	// ledger and which reasoning model back them is decided exactly here.
	//
	// This factory stays cheap and non-network, per DepsFactory's own
	// contract: it hands back ports, it does not dial. There is still no
	// real Transcriber/Judge/StallBank/Recorder/Finalizer adapter yet (those
	// land in later milestones), so those fields are left nil here — legal
	// per the connect failure classification: Speaker and Transport are the
	// two that are fatal once a client actually tries to attach a transport,
	// and the rest degrade.
	newDeps := func(_ context.Context, _ string, c *contract.EngineContract) (session.Deps, error) {
		deps := session.Deps{
			PreGate:        gate.New(c),
			Ledger:         ledger.New(c.PrecompiledBeliefs, time.Now()),
			Transport:      media,
			ConnectTimeout: cfg.ConnectTimeout,
			// The two session-scoped caps. Projected here rather than read
			// in internal/session, which may not import internal/config.
			SilenceTimeout:     cfg.SilenceTimeout,
			SessionDurationCap: cfg.SessionDurationCap,
		}
		// The Speaker is the persona's mouth and is fatal when absent —
		// but absent at *connect* time, not here: a factory that refused
		// to build deps would fail the session before it could report why.
		if cfg.SpeakerModelID != "" && !cfg.GeminiAPIKey.IsZero() {
			deps.Speaker = gemini.New(cfg.SpeakerModelID, cfg.GeminiAPIKey.Reveal(), logger)
		} else {
			logger.Warn("no Speaker configured; sessions will fail on transport attach",
				"have_model_id", cfg.SpeakerModelID != "")
		}
		// The stall bank is per-session: its clips are this persona's, in
		// this persona's frozen voice, pre-synthesized before the first turn
		// that might need one. Without it the opening line has no audio and
		// its duration can only be estimated from the text.
		if cfg.TTSModelID != "" && !cfg.GeminiAPIKey.IsZero() && c.TTSVoiceID != "" {
			deps.Stall = stall.New(
				geminitts.New(cfg.TTSModelID, cfg.GeminiAPIKey.Reveal()),
				c.TTSVoiceID, c.OpeningLine, c.StallPhrases, logger)
		} else {
			logger.Warn("no stall bank; the opening line will be timed from its text",
				"have_model_id", cfg.TTSModelID != "", "have_voice", c.TTSVoiceID != "")
		}
		// The reasoning model is optional at runtime. Without a key or a
		// model id the session runs single-model rather than refusing to
		// open — a live interview degrading is better than one that never
		// starts (plan §11).
		if cfg.ThinkerModelID != "" && !cfg.GeminiAPIKey.IsZero() {
			deps.Thinker = thinkerllm.New(cfg.ThinkerModelID, cfg.GeminiAPIKey.Reveal())
		} else {
			logger.Warn("no Thinker configured; sessions run single-model",
				"have_model_id", cfg.ThinkerModelID != "")
		}
		return deps, nil
	}
	manager := session.NewManager(realClock{}, contractSource, logger, events, newDeps)

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", handleHealthz)
	mux.Handle(mediaPath, media)
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
