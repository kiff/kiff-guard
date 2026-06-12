// Package main — KIFF decide server for chargeback-dispute-guard.
//
// Domain: a Dispute moves FILED -> INVESTIGATED -> SUBMITTED -> RESOLVED.
// SUBMIT_CHARGEBACK is allowed only from INVESTIGATED. Once SUBMITTED,
// all re-submission attempts are blocked (state_not_allowed), preventing
// duplicate chargebacks to Visa/Mastercard which carry penalty fees.
package main

import (
	"context"
	"fmt"
	"time"

	"github.com/kiff/kiff/pkg/kiff/action"
	"github.com/kiff/kiff/pkg/kiff/actor"
	"github.com/kiff/kiff/pkg/kiff/adapter"
	"github.com/kiff/kiff/pkg/kiff/domain"
	"github.com/kiff/kiff/pkg/kiff/event"
	"github.com/kiff/kiff/pkg/kiff/permission"
	"github.com/kiff/kiff/pkg/kiff/runtime"
)

const (
	AdapterDispute = "dispute"
	EntityDispute  = "Dispute"

	EventDisputeFiled      = "DISPUTE_FILED"
	EventDisputeInvestigated = "DISPUTE_INVESTIGATED"
	EventChargebackSubmitted = "CHARGEBACK_SUBMITTED"
	EventDisputeResolved   = "DISPUTE_RESOLVED"

	StateFiled       = "FILED"
	StateInvestigated = "INVESTIGATED"
	StateSubmitted   = "SUBMITTED"
	StateResolved    = "RESOLVED"

	ActionSubmitChargeback = "SUBMIT_CHARGEBACK"

	PermSubmitChargeback permission.Permission = "dispute.submit_chargeback"
)

var AgentActor = actor.Actor{
	ID:          "disputes-agent",
	Type:        actor.TypeAgent,
	DisplayName: "Disputes Agent",
	Roles:       []string{"disputes"},
}

func NewDomainDefinition() (domain.Definition, error) {
	b := domain.New("chargebacks").
		Entity(EntityDispute).
		Event(EventDisputeFiled).
		Event(EventDisputeInvestigated).
		Event(EventChargebackSubmitted).
		Event(EventDisputeResolved).
		Transition(EventDisputeFiled, "", StateFiled).
		Transition(EventDisputeInvestigated, StateFiled, StateInvestigated).
		Transition(EventChargebackSubmitted, StateInvestigated, StateSubmitted).
		Transition(EventDisputeResolved, StateSubmitted, StateResolved).
		Allow(StateInvestigated, ActionSubmitChargeback).
		Action(submitChargebackContract())
	return b.Build()
}

func submitChargebackContract() action.ActionContract {
	return action.ActionContract{
		Name:                ActionSubmitChargeback,
		AllowedStates:       []string{StateInvestigated},
		RequiredParameters:  []string{"reason_code", "amount_cents"},
		RequiredPermissions: []permission.Permission{PermSubmitChargeback},
		Risk:                action.RiskHigh,
		ApprovalRequirement: action.ApprovalNever,
		Executor: func(_ context.Context, ctx action.ActionContext) (action.ActionResult, error) {
			return action.ActionResult{
				ActionName: ActionSubmitChargeback, EntityID: ctx.EntityID,
				Status: action.ExecutionSucceeded, Executed: true,
				Message:        "chargeback cleared; agent submits to card scheme",
				EffectsSummary: "chargeback cleared",
				ExecutedAt:     time.Now().UTC(),
			}, nil
		},
	}
}

func NewPermissionPolicy() *permission.SimplePolicy {
	p := permission.NewSimplePolicy()
	p.GrantRole("disputes", PermSubmitChargeback)
	p.GrantRole("system", PermSubmitChargeback)
	return p
}

func NewInputAdapter() (adapter.Adapter, error) {
	return adapter.NewPassthroughAdapter(AdapterDispute)
}

func NewRuntime() (*runtime.Runtime, error) {
	def, err := NewDomainDefinition()
	if err != nil {
		return nil, err
	}
	in, err := NewInputAdapter()
	if err != nil {
		return nil, err
	}
	return runtime.NewForDomain(def, runtime.Config{
		PermissionPolicy: NewPermissionPolicy(),
		Adapters:         []adapter.Adapter{in},
	})
}

func disputeEvent(disputeID, eventType, actorID string, payload map[string]any) event.Event {
	return event.Event{
		ID:         fmt.Sprintf("evt-%s-%s-%d", eventType, disputeID, time.Now().UnixNano()),
		Type:       eventType,
		EntityID:   disputeID,
		EntityType: EntityDispute,
		Source:     "disputes-app",
		ActorID:    actorID,
		OccurredAt: time.Now().UTC(),
		Payload:    payload,
	}
}
