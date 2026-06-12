// Command kiff-decide — chargeback-dispute-guard gate server.
package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/kiff/kiff/pkg/kiff/action"
	"github.com/kiff/kiff/pkg/kiff/proposal"
	"github.com/kiff/kiff/pkg/kiff/runtime"
)

type server struct{ rt *runtime.Runtime }

func main() {
	addr := flag.String("addr", ":8081", "listen address")
	flag.Parse()
	rt, err := NewRuntime()
	if err != nil {
		log.Fatalf("kiff-decide: %v", err)
	}
	s := &server{rt: rt}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/proposals/decide", s.decide)
	mux.HandleFunc("POST /v1/events/raw", s.ingest)
	mux.HandleFunc("POST /seed", s.seed)
	mux.HandleFunc("GET /v1/entities/{id}/state", s.state)
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok\n"))
	})
	log.Printf("kiff-decide listening on %s (domain: chargebacks)", *addr)
	if err := http.ListenAndServe(*addr, mux); err != nil {
		log.Fatalf("kiff-decide: %v", err)
	}
}

type decideRequest struct {
	ID               string         `json:"id,omitempty"`
	EntityID         string         `json:"entity_id"`
	EntityType       string         `json:"entity_type"`
	ActionName       string         `json:"action_name"`
	ActorID          string         `json:"actor_id"`
	Parameters       map[string]any `json:"parameters,omitempty"`
	ReasoningSummary string         `json:"reasoning_summary,omitempty"`
	Confidence       float64        `json:"confidence,omitempty"`
}

type decideResponse struct {
	ProposalID string   `json:"proposal_id"`
	Outcome    string   `json:"outcome"`
	Reasons    []string `json:"reasons,omitempty"`
	Message    string   `json:"message,omitempty"`
}

func (s *server) decide(w http.ResponseWriter, r *http.Request) {
	var req decideRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, decideResponse{Outcome: "invalid", Reasons: []string{"invalid_json"}})
		return
	}
	if req.EntityID == "" || req.ActionName == "" {
		writeJSON(w, http.StatusBadRequest, decideResponse{Outcome: "invalid", Reasons: []string{"missing_required_field"}})
		return
	}
	propID := req.ID
	if propID == "" {
		propID = "prop_" + time.Now().UTC().Format("20060102T150405.000000000")
	}
	prop := proposal.ActionProposal{
		ID: propID, EntityID: req.EntityID, EntityType: req.EntityType,
		ActionName: req.ActionName, ReasoningSummary: req.ReasoningSummary,
		Confidence: req.Confidence, ActorID: AgentActor.ID,
		CreatedAt: time.Now().UTC(), Parameters: req.Parameters,
	}
	if s.rt.Decisions != nil {
		_ = s.rt.RecordActionProposal(r.Context(), prop)
	}
	contract, ok := s.rt.Actions.Get(req.ActionName)
	if !ok {
		writeJSON(w, http.StatusBadRequest, decideResponse{
			ProposalID: propID, Outcome: "invalid", Reasons: []string{"unknown_action"},
			Message: fmt.Sprintf("action %q not declared by domain", req.ActionName),
		})
		return
	}
	currentState := ""
	if s.rt.States != nil {
		if st, found, err := s.rt.States.Current(r.Context(), req.EntityID); err == nil && found {
			currentState = st.Value
		}
	}
	err := s.rt.ValidateActionProposal(r.Context(), prop, currentState, AgentActor, contract)
	switch {
	case err == nil:
		writeJSON(w, http.StatusOK, decideResponse{ProposalID: propID, Outcome: "allowed",
			Message: "chargeback submission cleared"})
	case errors.Is(err, action.ErrStateNotAllowed):
		writeJSON(w, http.StatusOK, decideResponse{
			ProposalID: propID, Outcome: "blocked", Reasons: []string{"state_not_allowed"},
			Message: fmt.Sprintf("dispute is in state %q — chargeback already submitted or not yet investigated", currentState),
		})
	case errors.Is(err, action.ErrMissingParameter):
		writeJSON(w, http.StatusOK, decideResponse{ProposalID: propID, Outcome: "blocked", Reasons: []string{"missing_parameter"},
			Message: "reason_code and amount_cents are required"})
	case errors.Is(err, action.ErrPermissionDenied):
		writeJSON(w, http.StatusOK, decideResponse{ProposalID: propID, Outcome: "blocked", Reasons: []string{"permission_denied"}})
	default:
		writeJSON(w, http.StatusOK, decideResponse{ProposalID: propID, Outcome: "blocked", Reasons: []string{"validation_failed"}})
	}
}

type ingestRequest struct {
	DisputeID string         `json:"dispute_id"`
	Type      string         `json:"type"`
	ActorID   string         `json:"actor_id,omitempty"`
	Payload   map[string]any `json:"payload,omitempty"`
}

func (s *server) ingest(w http.ResponseWriter, r *http.Request) {
	var req ingestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.DisputeID == "" || req.Type == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "dispute_id and type are required"})
		return
	}
	actorID := req.ActorID
	if actorID == "" {
		actorID = "system"
	}
	ev := disputeEvent(req.DisputeID, req.Type, actorID, req.Payload)
	if err := s.rt.IngestEvent(r.Context(), ev); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusCreated, map[string]string{"status": "ingested", "type": req.Type})
}

func (s *server) seed(w http.ResponseWriter, r *http.Request) {
	var req ingestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.DisputeID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "dispute_id is required"})
		return
	}
	// Seed as INVESTIGATED (dispute already reviewed, ready for submission)
	filed := disputeEvent(req.DisputeID, EventDisputeFiled, "system", nil)
	if err := s.rt.IngestEvent(r.Context(), filed); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}
	investigated := disputeEvent(req.DisputeID, EventDisputeInvestigated, "system", req.Payload)
	if err := s.rt.IngestEvent(r.Context(), investigated); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}
	writeJSON(w, http.StatusCreated, map[string]string{"status": "seeded", "dispute_id": req.DisputeID, "state": StateInvestigated})
}

func (s *server) state(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	value := ""
	if s.rt.States != nil {
		if st, found, err := s.rt.States.Current(r.Context(), id); err == nil && found {
			value = st.Value
		}
	}
	writeJSON(w, http.StatusOK, map[string]string{"entity_id": id, "state": value})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
