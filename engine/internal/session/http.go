package session

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
)

// Handler exposes Manager's create/stop lifecycle as the plan §14 task 8
// HTTP surface: POST /v1/sessions and DELETE /v1/sessions/{id}.
type Handler struct {
	manager *Manager
	logger  *slog.Logger
}

// NewHandler wraps manager as an HTTP surface.
func NewHandler(manager *Manager, logger *slog.Logger) *Handler {
	return &Handler{manager: manager, logger: logger}
}

// Register mounts the session routes on mux. Only cmd/engined is meant to
// call this: it is the module's sole wiring point (plan §3).
func (h *Handler) Register(mux *http.ServeMux) {
	mux.HandleFunc("POST /v1/sessions", h.create)
	mux.HandleFunc("DELETE /v1/sessions/{id}", h.stop)
	mux.HandleFunc("POST /v1/sessions/{id}/transport", h.attachTransport)
}

// createRequest is the POST /v1/sessions request body.
type createRequest struct {
	CandidateID string `json:"candidate_id"`
}

// createResponse is the POST /v1/sessions response body.
//
// TransportOfferURL is the URL the client negotiates media transport
// against. The endpoint it points at lands in plan §14 task 16 (Pion WebRTC
// transport); it is returned now, ahead of that, so client integration has
// a stable shape to build against.
type createResponse struct {
	SessionID         string `json:"session_id"`
	TransportOfferURL string `json:"transport_offer_url"`
}

// errorResponse is the JSON body of every non-2xx response this handler
// produces.
type errorResponse struct {
	Error string `json:"error"`
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	var req createRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		h.writeError(w, http.StatusBadRequest, "malformed request body")
		return
	}

	info, err := h.manager.CreateSession(r.Context(), req.CandidateID)
	if err != nil {
		h.writeCreateError(w, err)
		return
	}

	h.writeJSON(w, http.StatusCreated, createResponse{
		SessionID:         info.ID,
		TransportOfferURL: "/v1/sessions/" + info.ID + "/transport",
	})
}

// writeCreateError maps a CreateSession error to an HTTP status. A missing
// candidate id, or a contract that fails to parse, fails validation, or
// pins to an unsupported version (all covered by ErrContractRejected — see
// its doc comment), are all client-supplied-input problems — a bad persona
// is a client problem, not a server crash — so all map to 400 rather than
// 500. Anything else (e.g. the contract source being unreachable) is an
// upstream dependency failure outside the caller's control, mapped to 502.
func (h *Handler) writeCreateError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrEmptyCandidateID), errors.Is(err, ErrContractRejected):
		h.writeError(w, http.StatusBadRequest, err.Error())
	default:
		h.logger.Error("session: create failed", "err", err)
		h.writeError(w, http.StatusBadGateway, "could not create session")
	}
}

// attachTransportRequest is the POST /v1/sessions/{id}/transport request
// body: the client's SDP offer, carried as text (SDP is textual; unlike the
// session id or the answer that comes back, no encoding decision is
// needed).
type attachTransportRequest struct {
	Offer string `json:"offer"`
}

// attachTransportResponse is the POST /v1/sessions/{id}/transport response
// body: the SDP answer.
type attachTransportResponse struct {
	Answer string `json:"answer"`
}

func (h *Handler) attachTransport(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		h.writeError(w, http.StatusBadRequest, "session id is required")
		return
	}
	var req attachTransportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		h.writeError(w, http.StatusBadRequest, "malformed request body")
		return
	}

	answer, err := h.manager.AttachTransport(r.Context(), id, []byte(req.Offer))
	if err != nil {
		h.writeAttachTransportError(w, id, err)
		return
	}

	h.writeJSON(w, http.StatusOK, attachTransportResponse{Answer: string(answer)})
}

// writeAttachTransportError maps an AttachTransport error to an HTTP
// status: an unknown session id is 404, an already-attached transport is
// 409 (the client's own retry racing its first call, not a new attempt to
// service), and anything else — a rejected offer, no transport adapter
// configured — is an upstream/engine-side problem, mapped to 502.
func (h *Handler) writeAttachTransportError(w http.ResponseWriter, id string, err error) {
	switch {
	case errors.Is(err, ErrSessionNotFound):
		h.writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, ErrTransportAlreadyAttached):
		h.writeError(w, http.StatusConflict, err.Error())
	default:
		h.logger.Error("session: attach transport failed", "session_id", id, "err", err)
		h.writeError(w, http.StatusBadGateway, "could not attach transport")
	}
}

func (h *Handler) stop(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		h.writeError(w, http.StatusBadRequest, "session id is required")
		return
	}

	switch err := h.manager.StopSession(r.Context(), id); {
	case err == nil:
		w.WriteHeader(http.StatusNoContent)
	case errors.Is(err, ErrSessionNotFound):
		h.writeError(w, http.StatusNotFound, err.Error())
	default:
		h.logger.Error("session: stop failed", "session_id", id, "err", err)
		h.writeError(w, http.StatusInternalServerError, "could not stop session")
	}
}

func (h *Handler) writeError(w http.ResponseWriter, status int, msg string) {
	h.writeJSON(w, status, errorResponse{Error: msg})
}

func (h *Handler) writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(v); err != nil {
		// The status line and headers are already written at this point;
		// there is nothing left to do but record that the body was
		// incomplete.
		h.logger.Error("session: encode response body", "status", status, "err", err)
	}
}
